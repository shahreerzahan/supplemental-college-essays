"""Append-only audit trail at output/audit_trail.json (a JSON list of entries).

Every agent step is recorded: guard decisions, the student's input, each tool call and result,
validator retries, the final output, and errors. Entries are only ever added.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.messages import (
    ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart,
)

from app.config import AUDIT_TRAIL

MAX_FIELD_CHARS = 300
_lock = threading.Lock()


def short(value: Any) -> str:
    """Compact one-line text, cut to MAX_FIELD_CHARS."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, separators=(",", ":"))
    text = " ".join(text.split())
    return text if len(text) <= MAX_FIELD_CHARS else text[: MAX_FIELD_CHARS - 3] + "..."


def append(entries: list[dict]) -> None:
    """Add entries to the trail. Existing entries are never changed or removed.

    If the file exists but isn't a JSON list, raise instead of overwriting it.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with _lock:
        AUDIT_TRAIL.parent.mkdir(parents=True, exist_ok=True)
        trail: list = []
        if AUDIT_TRAIL.exists() and AUDIT_TRAIL.stat().st_size > 0:
            trail = json.loads(AUDIT_TRAIL.read_text())
            if not isinstance(trail, list):
                raise RuntimeError(f"{AUDIT_TRAIL} is not a JSON list; refusing to overwrite it.")
        trail.extend({"time": now, **e} for e in entries)
        tmp = AUDIT_TRAIL.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trail, indent=2, ensure_ascii=False))
        os.replace(tmp, AUDIT_TRAIL)


def steps_from_messages(messages: list) -> list[dict]:
    """Turn a PydanticAI run's messages into audit steps (the fixed system prompt is left out)."""
    steps = []
    for m in messages:
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart):
                    steps.append({"kind": "input", "content": short(p.content)})
                elif isinstance(p, ToolReturnPart):
                    steps.append({"kind": "tool_result", "tool": p.tool_name, "content": short(p.content)})
                elif isinstance(p, RetryPromptPart):
                    steps.append({"kind": "retry", "tool": p.tool_name, "content": short(p.content)})
        elif isinstance(m, ModelResponse):
            for p in m.parts:
                if isinstance(p, ToolCallPart):
                    final = p.tool_name.startswith("final_result")
                    steps.append({"kind": "output" if final else "tool_call", "tool": p.tool_name,
                                  "args": short(p.args)})
                elif isinstance(p, TextPart) and p.content.strip():
                    steps.append({"kind": "model_text", "content": short(p.content)})
    return steps


def record(run_id: str, session: str, agent: str, job: str, steps: list[dict]) -> None:
    """Number the steps of one run and append them."""
    append([{"run_id": run_id, "session": session, "agent": agent, "job": job, "step": i, **s}
            for i, s in enumerate(steps, 1)])
