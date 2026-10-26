"""The shelf data and the agents' tools.

Every fact an agent can use comes through these functions, straight from data/shelf.json.
Each tool records the ids it returned, so the agents' output checks can reject anything else.
"""

import difflib
import json
import logging
import re
from pathlib import Path

from pydantic_ai import RunContext, capture_run_messages

from app import audit, config
from app.guard import as_data, normalize
from app.usage import counts, current_calls
from app.models import (
    CoachDeps, Example, ExamplesResult, LibrarianDeps, PromptBrief, PromptFull, PromptList,
    SchoolPrompts, SchoolsResult, SearchResult,
)

log = logging.getLogger("shelf.tools")

CHARS_PER_WORD = 6
TYPES = ["why us", "intellectual curiosity", "community", "activity", "challenge", "short take", "UCAS"]
TYPE_ALIASES = {
    "why us": "why us", "why-us": "why us", "why school": "why us", "why this school": "why us",
    "intellectual curiosity": "intellectual curiosity", "curiosity": "intellectual curiosity",
    "academic": "intellectual curiosity", "community": "community", "identity": "community",
    "activity": "activity", "extracurricular": "activity", "challenge": "challenge",
    "short take": "short take", "short": "short take", "short answer": "short take", "ucas": "UCAS",
}
# Extra names students use, on top of each school's key and full name.
SCHOOL_ALIASES = {
    "yale": ["yale"], "harvard": ["harvard", "harvard college"], "princeton": ["princeton"],
    "stanford": ["stanford"], "mit": ["mit", "massachusetts institute of technology"],
    "columbia": ["columbia", "columbia college", "columbia engineering"],
    "upenn": ["penn", "upenn", "u penn", "university of pennsylvania", "wharton"],
    "brown": ["brown"], "dartmouth": ["dartmouth"], "cornell": ["cornell"], "duke": ["duke"],
    "jhu": ["jhu", "johns hopkins", "hopkins"], "uchicago": ["uchicago", "chicago", "u chicago"],
    "northwestern": ["northwestern"], "caltech": ["caltech", "cal tech", "california institute of technology"],
    "oxford": ["oxford", "oxford university"], "cambridge": ["cambridge", "cambridge university"],
}
STOPWORDS = set("a an the and or of for to in on at by with about me my show find list give prompts prompt "
                "essay essays question questions that what which are is any all some under over words word".split())


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    s = re.sub(r"\b(the|university|of|college)\b", " ", s)
    return " ".join(s.split())


class Shelf:
    """data/shelf.json with indexes. Use Shelf.get(), which reloads when the file changes."""

    _cached: "Shelf | None" = None

    @classmethod
    def get(cls) -> "Shelf":
        mtime = config.SHELF_FILE.stat().st_mtime
        if cls._cached is None or cls._cached.mtime != mtime:
            cls._cached = cls(config.SHELF_FILE, mtime)
        return cls._cached

    def __init__(self, path: Path, mtime: float = 0.0):
        self.mtime = mtime
        data = json.loads(path.read_text())
        self.schools = {s["key"]: s for s in data["schools"]}
        self.prompts = {p["id"]: p for p in data["prompts"]}
        self.samples = {s["id"]: s for s in data.get("sample_essays", [])}
        self.essays = {e["id"]: e for e in data["essays_that_worked"]}
        self.aliases: dict[str, str] = {}
        for key, s in self.schools.items():
            for name in [key, s["name"], *SCHOOL_ALIASES.get(key, [])]:
                self.aliases[_norm(name)] = key
        # Every piece of text on the shelf, normalized: a quote in an answer must come from here.
        texts = [p["prompt"] for p in self.prompts.values()] + [n for s in self.schools.values() for n in s.get("notes", [])]
        texts += [s.get("prompt_answered") or "" for s in self.samples.values()]
        texts += [e.get("prompt_answered") or "" for e in self.essays.values()] + [e.get("title") or "" for e in self.essays.values()]
        self.corpus = "\n".join(normalize(t) for t in texts if t)

    # ----- lookups -----

    def resolve_schools(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Map what a student typed to school keys. Returns (keys found, names not on the shelf)."""
        found, missing = [], []
        for name in names:
            n = _norm(name)
            key = self.aliases.get(n)
            if not key and n:
                close = difflib.get_close_matches(n, list(self.aliases), n=1, cutoff=0.85)
                key = self.aliases[close[0]] if close else None
            if key and key not in found:
                found.append(key)
            elif not key and name.strip():
                missing.append(name.strip())
        return found, missing

    @staticmethod
    def limit_words(p: dict) -> int | None:
        lim = p.get("limit")
        if not lim:
            return None
        return lim["max"] if lim["unit"] == "words" else round(lim["max"] / CHARS_PER_WORD)

    @staticmethod
    def limit_text(p: dict) -> str:
        lim = p.get("limit")
        if not lim:
            return "No stated limit"
        n = f"{lim['min']:,}-{lim['max']:,}" if lim.get("min") else f"{lim['max']:,}"
        text = f"{n} {lim['unit']}"
        return f"{text}, shared across the 3 UCAS answers" if p["type"] == "UCAS" else text

    @staticmethod
    def choice_text(p: dict) -> str | None:
        cg = p.get("choice_group")
        if not cg:
            return None
        if p["required"] == "optional":
            return f"Optional: answer up to {cg['pick']} of {cg['of']} (group {cg['id']})"
        return f"Choose {cg['pick']} of {cg['of']} (group {cg['id']})"

    @staticmethod
    def audience(p: dict) -> str | None:
        """'Only for applicants to …' notes mark prompts for one program within a university."""
        notes = p.get("notes") or ""
        if notes.startswith("Only for"):
            # First clause only; "A.B. degree" must not split, so break on ";" or ". Capital".
            return re.split(r";|\.\s+(?=[A-Z])", notes, maxsplit=1)[0].rstrip(".")
        return None

    def brief(self, p: dict, max_chars: int | None = None) -> PromptBrief:
        text = p["prompt"]
        if max_chars and len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
        return PromptBrief(
            id=p["id"], school=p["school"], school_name=self.schools[p["school"]]["name"], type=p["type"],
            prompt=text, limit=self.limit_text(p), limit_words=self.limit_words(p),
            required=p["required"] == "required", choice=self.choice_text(p), audience=self.audience(p),
            source_url=p["source_url"],
        )

    def full(self, prompt_id: str) -> PromptFull | None:
        p = self.prompts.get(prompt_id)
        if not p:
            return None
        school_name = self.schools[p["school"]]["name"]
        return PromptFull(
            **self.brief(p).model_dump(), notes=p.get("notes") or None,
            sample_ids=[s["id"] for s in self.samples.values() if prompt_id in s["prompt_ids"]],
            essay_ids=[e["id"] for e in self.essays.values() if e.get("school") == school_name],
        )

    def example(self, ex_id: str) -> Example | None:
        if s := self.samples.get(ex_id):
            school = self.schools[s["school"]]["name"]
            written = s.get("written_for")
            title = f"Sample for {', '.join(s['prompt_ids'])}" + (f" (written for {written})" if written else "")
            return Example(id=ex_id, kind="sample", school_name=school, title=title, for_prompts=s["prompt_ids"],
                           summary=s["what_the_writer_did"], why_it_works=s["why_it_works"], source_url=s["source_url"])
        if e := self.essays.get(ex_id):
            title = e.get("title") or e.get("author") or "An essay that worked"
            return Example(id=ex_id, kind="essay", school_name=e.get("school") or e["publisher"], title=title,
                           for_prompts=[], summary=e["about"], why_it_works=[], source_url=e["source_url"])
        return None


def _note(ctx: RunContext[LibrarianDeps], tool: str, prompts=(), examples=()) -> None:
    ctx.deps.tool_calls.append(tool)
    ctx.deps.seen_prompt_ids.update(p.id for p in prompts)
    ctx.deps.seen_example_ids.update(e.id for e in examples)
    log.info("librarian tool %s -> %d prompts, %d examples", tool, len(prompts), len(examples))


# ---------- Librarian tools ----------

async def search_shelf(
    ctx: RunContext[LibrarianDeps],
    keywords: str | None = None,
    types: list[str] | None = None,
    schools: list[str] | None = None,
    max_words: int | None = None,
    min_words: int | None = None,
    required_only: bool = False,
    limit: int = 8,
) -> SearchResult:
    """Find prompts on the shelf by type, school, word limit and keywords. All filters are optional.

    Returns only the matching prompts, best first, capped at a few results (total_matches says how
    many matched in all).

    Args:
        keywords: words to look for in the prompt text, e.g. "joy" or "community roommate".
        types: any of: why us, intellectual curiosity, community, activity, challenge, short take, UCAS.
        schools: school names as the student wrote them, e.g. ["Penn", "Hopkins"].
        max_words: keep prompts whose word limit is at most this (character limits count ~6 characters a word).
        min_words: keep prompts whose word limit is at least this.
        required_only: keep only required prompts.
        limit: maximum number of matches to return.
    """
    limit = max(1, min(limit, ctx.deps.cap))
    shelf = ctx.deps.shelf
    pool = list(shelf.prompts.values())
    note = []
    not_on_shelf: list[str] = []
    if schools:
        keys, not_on_shelf = shelf.resolve_schools(schools)
        ctx.deps.not_on_shelf.update(not_on_shelf)
        pool = [p for p in pool if p["school"] in keys]
    if types:
        wanted = {TYPE_ALIASES.get(t.strip().lower(), t.strip()) for t in types}
        unknown = wanted - set(TYPES)
        if unknown:
            note.append(f"Unknown types ignored: {sorted(unknown)}. Types are: {TYPES}.")
        pool = [p for p in pool if p["type"] in wanted]
    if max_words is not None or min_words is not None:
        no_limit = [p for p in pool if shelf.limit_words(p) is None]
        pool = [p for p in pool if shelf.limit_words(p) is not None
                and (max_words is None or shelf.limit_words(p) <= max_words)
                and (min_words is None or shelf.limit_words(p) >= min_words)]
        if no_limit:
            note.append(f"{len(no_limit)} matching prompts have no stated limit and were left out.")
    if required_only:
        pool = [p for p in pool if p["required"] == "required"]
    if keywords:
        terms = [w for w in re.findall(r"[a-z0-9']+", keywords.lower()) if w not in STOPWORDS]
        if terms:
            scored = [(sum(t in (p["prompt"] + " " + (p.get("notes") or "")).lower() for t in terms), p) for p in pool]
            pool = [p for score, p in sorted(scored, key=lambda x: -x[0]) if score > 0]
    matches = [shelf.brief(p, max_chars=160 if ctx.deps.lean else 260) for p in pool[:limit]]
    _note(ctx, "search_shelf", prompts=matches)
    return SearchResult(matches=matches, total_matches=len(pool), not_on_shelf=not_on_shelf, note=" ".join(note) or None)


async def get_prompt(ctx: RunContext[LibrarianDeps], prompt_id: str) -> PromptFull | str:
    """Get one prompt in full: its exact text, limit, notes, source link, and which examples exist for it.

    Args:
        prompt_id: a prompt id such as "duke-01".
    """
    found = ctx.deps.shelf.full(prompt_id)
    if not found:
        _note(ctx, "get_prompt")
        return f"No prompt with id {prompt_id!r} is on the shelf."
    _note(ctx, "get_prompt", prompts=[found])
    return found


async def prompts_for_schools(
    ctx: RunContext[LibrarianDeps],
    schools: list[str],
    include_text: bool = True,
    include_notes: bool = False,
) -> SchoolsResult:
    """Get the 2026-27 prompts for the named schools.

    Args:
        schools: school names as the student wrote them, e.g. ["Yale", "UChicago", "Rice"].
        include_text: false returns ids, types and limits with only a short preview of each prompt.
        include_notes: true adds each school's application notes (deadlines, tests, interviews).
    """
    shelf = ctx.deps.shelf
    keys, missing = shelf.resolve_schools(schools)
    ctx.deps.not_on_shelf.update(missing)
    ctx.deps.schools_looked_up.update(keys)
    # A handoff needs every prompt; answers to students show a few at most.
    cap = None if ctx.deps.job == "handoff" else ctx.deps.cap
    chars = None if include_text else 70
    out, total = [], 0
    for k in keys:
        mine = [p for p in shelf.prompts.values() if p["school"] == k]
        total += len(mine)
        out.append(SchoolPrompts(school=k, school_name=shelf.schools[k]["name"],
                                 prompts=[shelf.brief(p, max_chars=chars) for p in mine],
                                 school_notes=shelf.schools[k].get("notes", []) if include_notes else []))
    note = None
    if cap is not None and total > cap:
        kept = 0
        for s in out:
            s.prompts = s.prompts[:max(0, cap - kept)]
            kept += len(s.prompts)
        note = f"Showing {cap} of {total} prompts; use search_shelf to narrow them down."
    _note(ctx, "prompts_for_schools", prompts=[p for s in out for p in s.prompts])
    return SchoolsResult(schools=out, not_on_shelf=missing, note=note)


async def list_examples(
    ctx: RunContext[LibrarianDeps],
    prompt_id: str | None = None,
    school: str | None = None,
    kind: str = "both",
    limit: int = 6,
) -> ExamplesResult:
    """List examples to read: College Essay Guy sample breakdowns ("sample") and essays that worked ("essay").

    Args:
        prompt_id: samples written for this prompt, plus essays that worked from its school.
        school: examples for this school (if no prompt_id).
        kind: "sample", "essay", or "both".
        limit: maximum number of examples.
    """
    limit = max(1, min(limit, ctx.deps.cap))
    shelf = ctx.deps.shelf
    ids: list[str] = []
    note = None
    school_key = None
    if prompt_id and prompt_id in shelf.prompts:
        school_key = shelf.prompts[prompt_id]["school"]
        ids += [s["id"] for s in shelf.samples.values() if prompt_id in s["prompt_ids"]]
    elif school:
        keys, missing = shelf.resolve_schools([school])
        school_key = keys[0] if keys else None
        if missing:
            ctx.deps.not_on_shelf.update(missing)
            note = f"{school} isn't on the shelf."
        if school_key:
            ids += [s["id"] for s in shelf.samples.values() if s["school"] == school_key]
    if school_key:
        name = shelf.schools[school_key]["name"]
        ids += [e["id"] for e in shelf.essays.values() if e.get("school") == name]
    if not ids and not school_key and not note:
        ids = list(shelf.essays)  # nothing specific asked: general essays that worked
    examples = [ex for i in ids if (ex := shelf.example(i))]
    if kind in ("sample", "essay"):
        examples = [ex for ex in examples if ex.kind == kind]
    examples = examples[:limit]
    if not examples and not note:
        note = "No examples on the shelf for that."
    _note(ctx, "list_examples", examples=examples)
    return ExamplesResult(examples=examples, note=note)


# ---------- Coach tool: the handoff ----------

async def ask_librarian(ctx: RunContext[CoachDeps], schools: list[str]) -> SchoolsResult:
    """Ask the Librarian for every prompt at the student's schools. This is your only source of prompts.

    Args:
        schools: the student's schools, as they wrote them.
    """
    lib_deps = LibrarianDeps(shelf=ctx.deps.shelf, job="handoff", lean=ctx.deps.lean)
    # The job note lives in the request, so the Librarian's system prompt stays fixed and cacheable.
    # School names come from the student, so they go in as data.
    request = ("Job 3, a handoff from the Essay Coach: return a PromptList. Call prompts_for_schools with "
               "include_text=false and list every prompt id for the schools named in the student input.\n\n"
               f"<student_input>\n{as_data(', '.join(schools))}\n</student_input>")
    before, first_call = counts(ctx.usage), len(current_calls())
    # The handoff shares the Coach's usage and limits, so the whole Story Map stays in one budget.
    with capture_run_messages() as messages:
        try:
            result = await ctx.deps.librarian.run(
                request, deps=lib_deps, model=ctx.model, model_settings=ctx.model_settings,
                usage=ctx.usage, usage_limits=ctx.usage_limits,
            )
        finally:
            audit.record(ctx.deps.run_id, ctx.deps.session, "librarian", "handoff",
                         audit.steps_from_messages(list(messages)))
    after = counts(ctx.usage)
    ctx.deps.handoff_usage = {k: after[k] - before[k] for k in after}
    ctx.deps.handoff_calls = current_calls()[first_call:]
    handoff: PromptList = result.output
    shelf = ctx.deps.shelf
    ctx.deps.handoff_ids.update(handoff.prompt_ids)
    ctx.deps.not_on_shelf = sorted(set(handoff.not_on_shelf) | lib_deps.not_on_shelf)
    log.info("handoff: librarian returned %d prompts; not on shelf: %s; tokens %s",
             len(handoff.prompt_ids), ctx.deps.not_on_shelf, ctx.deps.handoff_usage)

    # The coach gets the prompt details straight from the data (only the matching prompts, no
    # school notes). Lean mode trims long prompts.
    by_school: dict[str, list[PromptBrief]] = {}
    for pid in handoff.prompt_ids:
        p = shelf.prompts[pid]
        by_school.setdefault(p["school"], []).append(shelf.brief(p, max_chars=220 if ctx.deps.lean else None))
    return SchoolsResult(
        schools=[SchoolPrompts(school=k, school_name=shelf.schools[k]["name"], prompts=v, school_notes=[])
                 for k, v in by_school.items()],
        not_on_shelf=ctx.deps.not_on_shelf,
    )
