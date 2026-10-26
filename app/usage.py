"""Token meter, cost, and the token log (output/token_log.json) for every agent run.

Portkey has a response cache: an identical request comes back as a saved answer
(header x-portkey-cache-status: HIT) without reaching the model, but its body still carries the
original token counts. So we record every model response during a run and count only the
tokens of the ones that actually reached the model.
"""

import json
import logging
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import httpx

from app import config
from app.models import UsageOut

log = logging.getLogger("shelf.usage")
_lock = threading.Lock()

FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "requests", "tool_calls")

# Model responses seen during the current agent run: [{"hit": bool, "usage": {...}}, ...]
_calls: ContextVar[list[dict] | None] = ContextVar("agent_model_calls", default=None)


def counts(usage: Any) -> dict[str, int]:
    """The numbers we track from a PydanticAI RunUsage."""
    return {f: int(getattr(usage, f, 0) or 0) for f in FIELDS}


async def record_response(response: httpx.Response) -> None:
    """httpx response hook on the model client: note Portkey's cache status and the reported usage."""
    calls = _calls.get()
    if calls is None or "/responses" not in response.url.path:
        return
    usage: dict = {}
    try:
        await response.aread()
        usage = (response.json() or {}).get("usage") or {}
    except Exception:  # not JSON, or an error body: nothing to count
        pass
    calls.append({"hit": response.headers.get("x-portkey-cache-status", "").upper() == "HIT", "usage": usage})


def track():
    """Start recording model responses for one agent run. Returns a token for untrack()."""
    return _calls.set([])


def untrack(token) -> list[dict]:
    calls = _calls.get() or []
    _calls.reset(token)
    return calls


def current_calls() -> list[dict]:
    return _calls.get() or []


def billed(c: dict[str, int], calls: list[dict]) -> tuple[dict[str, int], int]:
    """Take out the tokens Portkey replayed from its cache. Returns (billed counts, cache hits)."""
    out = dict(c)
    hits = [x["usage"] for x in calls if x["hit"]]
    for u in hits:
        details = u.get("input_tokens_details") or {}
        out["input_tokens"] -= int(u.get("input_tokens") or 0)
        out["cache_read_tokens"] -= int(details.get("cached_tokens") or 0)
        out["cache_write_tokens"] -= int(details.get("cache_write_tokens") or details.get("cache_creation_tokens") or 0)
        out["output_tokens"] -= int(u.get("output_tokens") or 0)
    for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"):
        out[k] = max(0, out[k])
    return out, len(hits)


def cost_usd(c: dict[str, int]) -> float | None:
    """Cost from the prices in app/config.py, or None while they're still TODO.

    input_tokens counts every input token; cache reads and cache writes are the parts of it that
    were read from or written to the prompt cache.
    """
    p_in, p_cached, p_out = (config.PRICE_PER_MILLION_INPUT, config.PRICE_PER_MILLION_CACHED_INPUT,
                             config.PRICE_PER_MILLION_OUTPUT)
    if p_in is None or p_cached is None or p_out is None:
        return None
    p_write = config.PRICE_PER_MILLION_CACHE_WRITE if config.PRICE_PER_MILLION_CACHE_WRITE is not None else p_in
    fresh = max(0, c["input_tokens"] - c["cache_read_tokens"] - c["cache_write_tokens"])
    dollars = (fresh * p_in + c["cache_read_tokens"] * p_cached + c["cache_write_tokens"] * p_write
               + c["output_tokens"] * p_out) / 1_000_000
    return round(dollars, 6)


def meter(agent: str, c: dict[str, int], lean: bool, handoff: dict[str, int] | None = None,
          portkey_hits: int = 0, handoff_hits: int = 0) -> UsageOut:
    return UsageOut(
        agent=agent, input_tokens=c["input_tokens"], cached_input_tokens=c["cache_read_tokens"],
        cache_write_tokens=c["cache_write_tokens"], output_tokens=c["output_tokens"], requests=c["requests"],
        tool_calls=c["tool_calls"], portkey_cache_hits=portkey_hits, cost_usd=cost_usd(c), lean=lean,
        handoff=meter("librarian (handoff)", handoff, lean, portkey_hits=handoff_hits) if handoff else None,
    )


def reused(agent: str, lean: bool) -> UsageOut:
    """Meter for an answer served from memory: no model call, no tokens."""
    zero = dict.fromkeys(FIELDS, 0)
    return meter(agent, zero, lean).model_copy(update={"from_cache": True, "cost_usd": 0.0})


def log_run(agent: str, job: str, asked: Any, lean: bool, c: dict[str, int] | None,
            handoff: dict[str, int] | None = None, error: str | None = None, portkey_hits: int = 0,
            handoff_hits: int = 0) -> None:
    """Append one run to output/token_log.json (a JSON list, newest last). Tokens are billed tokens:
    responses Portkey served from its cache are counted under portkey_cache_hits instead."""
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agent": agent,
        "job": job,
        "lean": lean,
        "asked": asked,
        "tokens": {
            "input": c["input_tokens"], "cached_input": c["cache_read_tokens"],
            "cache_write": c["cache_write_tokens"], "output": c["output_tokens"],
            "requests": c["requests"], "portkey_cache_hits": portkey_hits, "tool_calls": c["tool_calls"],
        } if c else None,
        "cost_usd": cost_usd(c) if c else None,
    }
    if handoff:
        entry["of_which_librarian_handoff"] = {"input": handoff["input_tokens"], "cached_input": handoff["cache_read_tokens"],
                                              "output": handoff["output_tokens"], "requests": handoff["requests"],
                                              "portkey_cache_hits": handoff_hits}
    if error:
        entry["error"] = error
    path = config.TOKEN_LOG
    with _lock:
        try:
            runs = json.loads(path.read_text()) if path.exists() else []
            if not isinstance(runs, list):
                runs = []
        except json.JSONDecodeError:
            log.warning("token log was not valid JSON; starting a new one")
            runs = []
        runs.append(entry)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(runs, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(path)
