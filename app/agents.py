"""The two agents: the Librarian answers from the shelf; the Essay Coach builds Story Maps.

- Both run on gpt-6-luna through Portkey, and nothing else.
- The Librarian's tools are the only way to the shelf data (app/tools.py).
- The Coach gets its prompts by asking the Librarian (the handoff in tools.ask_librarian).
- Output checks send the model back to fix answers that cite ids no tool returned, skip
  required prompts, or start writing the student's essay.
- Source links are added here from the data, never taken from model text.
"""

import asyncio
import logging
import re
from functools import lru_cache
from urllib.parse import urlparse

from openai import AsyncOpenAI
from portkey_ai import PORTKEY_GATEWAY_URL
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from app import config
from app.models import (
    AskResponse, CoachDeps, DecodeResponse, LibrarianDeps, MapRowOut, PromptDecode, PromptList, ReadThisOut,
    SharedStory, ShelfAnswer, Source, StoryMapPlan, StoryMapRequest, StoryMapResponse,
)
from app.tools import Shelf, ask_librarian, get_prompt, list_examples, prompts_for_schools, search_shelf

log = logging.getLogger("shelf.agents")

SETTINGS = OpenAIResponsesModelSettings(openai_reasoning_effort="low")
LIBRARIAN_LIMITS = UsageLimits(request_limit=8, tool_calls_limit=10, total_tokens_limit=80_000)
# The Coach's budget also covers the Librarian's work during the handoff.
COACH_LIMITS = UsageLimits(request_limit=24, tool_calls_limit=16, total_tokens_limit=250_000)
RUNS = asyncio.Semaphore(3)  # at most three agent runs at once

UCAS_WORDS = round(4000 / 6)  # one shared 4,000-character statement per school
SHORT_TAKE_WORDS = 60         # rows this short don't need a story, so they aren't gaps


@lru_cache
def model() -> OpenAIResponsesModel:
    key = config.portkey_api_key()
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_GATEWAY_URL, default_headers={"x-portkey-api-key": key})
    return OpenAIResponsesModel(config.MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text()


# One Librarian, three jobs. Each run says which job it is (deps.job and run instructions);
# the output check makes sure the answer has that job's shape.
librarian = Agent(
    name="librarian",
    deps_type=LibrarianDeps,
    output_type=[ShelfAnswer, PromptDecode, PromptList],
    instructions=load_prompt("librarian"),
    tools=[search_shelf, get_prompt, prompts_for_schools, list_examples],
    retries=2,
)
JOB_OUTPUT = {"ask": ShelfAnswer, "decode": PromptDecode, "handoff": PromptList}
JOB_NOTE = {
    "ask": "This run is job 1, Ask the shelf: return a ShelfAnswer.",
    "decode": "This run is job 2, Decode this prompt: return a PromptDecode.",
    "handoff": "This run is job 3, a handoff from the Essay Coach: return a PromptList.",
}

coach = Agent(
    name="coach",
    deps_type=CoachDeps,
    output_type=StoryMapPlan,
    instructions=load_prompt("coach"),
    tools=[ask_librarian],
    retries=3,
)


# ---------- Output checks ----------

@librarian.output_validator
def check_librarian(ctx: RunContext[LibrarianDeps], out):
    deps = ctx.deps
    if not isinstance(out, JOB_OUTPUT[deps.job]):
        raise ModelRetry(f"{JOB_NOTE[deps.job]} You returned a {type(out).__name__}.")
    if not deps.tool_calls:
        raise ModelRetry("Look this up with the shelf tools first, and answer only from what they return.")

    if isinstance(out, ShelfAnswer):
        bad = [i for i in out.prompt_ids if i not in deps.seen_prompt_ids]
        bad += [i for i in out.example_ids if i not in deps.seen_example_ids]
        if bad:
            raise ModelRetry(f"These ids didn't come from your tools: {bad}. Only list ids the tools returned.")
        # Trust the tools on which schools are missing; drop any the shelf does have.
        named = set(out.not_on_shelf) | deps.not_on_shelf
        out.not_on_shelf = sorted(n for n in named if not deps.shelf.resolve_schools([n])[0])

    elif isinstance(out, PromptDecode):
        if deps.focus and deps.focus not in deps.seen_prompt_ids:
            raise ModelRetry(f"Call get_prompt for {deps.focus} first, and decode that prompt.")
        bad = [r.example_id for r in out.read_these if r.example_id not in deps.seen_example_ids]
        if bad:
            raise ModelRetry(f"These example ids didn't come from list_examples: {bad}.")
        if not 2 <= len(out.common_mistakes) <= 5:
            raise ModelRetry("Give 3-4 common mistakes.")

    elif isinstance(out, PromptList):
        bad = [i for i in out.prompt_ids if i not in deps.seen_prompt_ids]
        if bad:
            raise ModelRetry(f"These ids didn't come from your tools: {bad}.")
        expected = [i for i, p in deps.shelf.prompts.items() if p["school"] in deps.schools_looked_up]
        missing = [i for i in expected if i not in out.prompt_ids]
        if missing:
            raise ModelRetry(f"Return every prompt for the schools you looked up. Missing: {missing}.")
        out.not_on_shelf = sorted(set(out.not_on_shelf) | deps.not_on_shelf)
    return out


FIRST_PERSON = re.compile(r"(^|[.!?]\s+)(I|I'm|I've|I'd|My|Me)\b")


def _coaching_problems(plan: StoryMapPlan) -> list[str]:
    """The Coach coaches: short notes to "you", never lines of the student's essay."""
    fields = [(f"row {r.prompt_id} why", r.why, 45) for r in plan.rows]
    fields += [(f"row {r.prompt_id} coaching", r.coaching, 50) for r in plan.rows]
    fields += [(f"shared story {s.story}", s.how_to_vary, 50) for s in plan.shared]
    fields += [(f"advice {i + 1}", a, 40) for i, a in enumerate(plan.advice)]
    problems = [f"{name} is too long; keep it under {cap} words." for name, text, cap in fields if len(text.split()) > cap]
    problems += [f"{name} reads like the student's own essay. Coach them as 'you'; don't write their sentences."
                 for name, text, _ in fields if FIRST_PERSON.search(text)]
    if len(plan.advice) > 3:
        problems.append("Give at most 3 pieces of advice.")
    return problems


@coach.output_validator
def check_map(ctx: RunContext[CoachDeps], plan: StoryMapPlan) -> StoryMapPlan:
    deps, shelf = ctx.deps, ctx.deps.shelf
    if not deps.handoff_ids:
        if deps.not_on_shelf and not plan.rows:
            return plan  # none of the schools are on the shelf
        raise ModelRetry("Call ask_librarian first: it's your only source of prompts.")

    problems = []
    ids = [r.prompt_id for r in plan.rows]
    if unknown := [i for i in ids if i not in deps.handoff_ids]:
        problems.append(f"These prompt ids didn't come from the Librarian: {unknown}.")
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"One row per prompt; these appear twice: {dupes}.")
    if bad := [r.prompt_id for r in plan.rows if r.story is not None and not 1 <= r.story <= len(deps.stories)]:
        problems.append(f"Story numbers must be 1 to {len(deps.stories)}; check rows {bad}.")
    for r in plan.rows:
        if r.story is None:
            r.fit = None

    # Every prompt the student has to write must have a row.
    chosen = set(ids)
    handed = [shelf.prompts[i] for i in deps.handoff_ids]
    for school in sorted({p["school"] for p in handed}):
        mine = [p for p in handed if p["school"] == school]
        problems += [f"Missing required prompt {p['id']}." for p in mine
                     if p["required"] == "required" and not p.get("choice_group") and not Shelf.audience(p)
                     and p["id"] not in chosen]
        groups: dict[str, tuple[int, bool, list[str]]] = {}
        for p in mine:
            if cg := p.get("choice_group"):
                groups.setdefault(cg["id"], (cg["pick"], p["required"] == "required", []))[2].append(p["id"])
        for gid, (pick, required, members) in groups.items():
            got = sum(m in chosen for m in members)
            if required and got < pick:
                problems.append(f"Pick {pick - got} more from {gid}: {members}.")
            if got > pick:
                problems.append(f"{gid} allows {'' if required else 'up to '}{pick}; you mapped {got}. "
                                f"Keep only the best {pick}.")
        problems += [f"Optional prompt {p['id']} has no story; leave it out." for p in mine
                     if p["required"] == "optional" and p["id"] in chosen
                     and next(r for r in plan.rows if r.prompt_id == p["id"]).story is None]
        programs: dict[str, list[str]] = {}
        for p in mine:
            if a := Shelf.audience(p):
                programs.setdefault(a, []).append(p["id"])
        if programs:
            picked = [a for a, members in programs.items() if chosen & set(members)]
            if not picked:
                problems.append(f"Pick one {shelf.schools[school]['name']} program and map all its prompts. "
                                f"Programs: {list(programs)}.")
            for a in picked:
                if left := [m for m in programs[a] if m not in chosen]:
                    problems.append(f"You picked '{a}', so also map {left}.")

    problems += _coaching_problems(plan)
    if problems:
        log.info("coach retry: %s", problems)
        raise ModelRetry("Fix these and return the whole map again:\n- " + "\n- ".join(problems))
    return plan


# ---------- What the API calls ----------

def _source(label: str, url: str) -> Source:
    return Source(label=f"{label} · {urlparse(url).netloc.removeprefix('www.')}", url=url)


async def ask_shelf(question: str) -> AskResponse:
    shelf = Shelf.get()
    deps = LibrarianDeps(shelf=shelf, job="ask")
    async with RUNS:
        result = await librarian.run(question, deps=deps, instructions=JOB_NOTE["ask"], model=model(),
                                     model_settings=SETTINGS, usage_limits=LIBRARIAN_LIMITS)
    out: ShelfAnswer = result.output
    log.info("ask: %r -> %d prompts, tools %s, %s", question, len(out.prompt_ids), deps.tool_calls, result.usage)

    sources: dict[str, Source] = {}
    for pid in out.prompt_ids:
        p = shelf.prompts[pid]
        sources.setdefault(p["source_url"], _source(shelf.schools[p["school"]]["name"], p["source_url"]))
    for ex_id in out.example_ids:
        if ex := shelf.example(ex_id):
            sources.setdefault(ex.source_url, _source(ex.title, ex.source_url))
    return AskResponse(answer=out.answer, prompt_ids=out.prompt_ids, not_on_shelf=out.not_on_shelf,
                       sources=list(sources.values()))


_decoded: dict[tuple[str, float], DecodeResponse] = {}


async def decode_prompt(prompt_id: str) -> DecodeResponse:
    shelf = Shelf.get()
    if (prompt_id, shelf.mtime) in _decoded:
        return _decoded[(prompt_id, shelf.mtime)]
    deps = LibrarianDeps(shelf=shelf, job="decode", focus=prompt_id)
    async with RUNS:
        result = await librarian.run(f"Decode this prompt: {prompt_id}", deps=deps, instructions=JOB_NOTE["decode"],
                                     model=model(), model_settings=SETTINGS, usage_limits=LIBRARIAN_LIMITS)
    out: PromptDecode = result.output
    log.info("decode %s: tools %s, %s", prompt_id, deps.tool_calls, result.usage)

    read = []
    for r in out.read_these:
        ex = shelf.example(r.example_id)
        read.append(ReadThisOut(id=ex.id, kind=ex.kind, title=ex.title, why=r.why, source_url=ex.source_url,
                                open_id=ex.for_prompts[0] if ex.kind == "sample" else ex.id))
    decoded = DecodeResponse(prompt_id=prompt_id, really_asking=out.really_asking,
                             common_mistakes=out.common_mistakes, read_these=read,
                             source_url=shelf.prompts[prompt_id]["source_url"])
    _decoded[(prompt_id, shelf.mtime)] = decoded
    return decoded


async def build_story_map(req: StoryMapRequest) -> StoryMapResponse:
    shelf = Shelf.get()
    deps = CoachDeps(shelf=shelf, librarian=librarian, stories=req.stories, applying_to=req.applying_to)
    stories = "\n".join(f"{i}. {s}" for i, s in enumerate(req.stories, 1))
    request = (f"My schools: {', '.join(req.schools)}\n"
               f"Applying to (college, school or major): {req.applying_to or 'not sure yet'}\n"
               f"My stories:\n{stories}")
    async with RUNS:
        result = await coach.run(request, deps=deps, model=model(), model_settings=SETTINGS, usage_limits=COACH_LIMITS)
    plan: StoryMapPlan = result.output
    log.info("story map: %d rows, not on shelf %s, %s", len(plan.rows), deps.not_on_shelf, result.usage)

    order = {pid: i for i, pid in enumerate(shelf.prompts)}
    rows = []
    for r in sorted(plan.rows, key=lambda r: order[r.prompt_id]):
        b = shelf.brief(shelf.prompts[r.prompt_id])
        rows.append(MapRowOut(prompt_id=b.id, school=b.school, school_name=b.school_name, type=b.type,
                              prompt=b.prompt, limit=b.limit, limit_words=b.limit_words, required=b.required,
                              choice=b.choice, source_url=b.source_url, story=r.story, fit=r.fit,
                              why=r.why, coaching=r.coaching))

    # Shared stories and totals come from the rows, not from the model's arithmetic.
    vary = {s.story: s.how_to_vary for s in plan.shared}
    uses: dict[int, list[str]] = {}
    for r in rows:
        if r.story is not None:
            uses.setdefault(r.story, []).append(r.prompt_id)
    shared = [SharedStory(story=k, prompt_ids=v,
                          how_to_vary=vary.get(k, "Use a different moment or lesson from this story for each prompt."))
              for k, v in sorted(uses.items()) if len(v) > 1]

    total, no_limit, ucas_schools = 0, 0, set()
    for r in rows:
        if r.type == "UCAS":
            if r.school not in ucas_schools:
                total += UCAS_WORDS
                ucas_schools.add(r.school)
        elif r.limit_words is None:
            no_limit += 1
        else:
            total += r.limit_words
    optional = sum(1 for r in rows if not r.required)
    note = [f"About {total:,} words across {len(rows)} prompts, at each prompt's limit"
            + (f", including {optional} optional prompt{'s' if optional > 1 else ''} the coach suggests." if optional else ".")]
    if any(r.limit.endswith("characters") or r.type == "UCAS" for r in rows):
        note.append("Character limits are counted at about 6 characters per word.")
    if ucas_schools:
        note.append("The UCAS statement is one 4,000-character text shared by all three questions.")
    if no_limit:
        note.append(f"{no_limit} prompt{'s have' if no_limit > 1 else ' has'} no stated limit and isn't counted.")
    gaps = sum(1 for r in rows if r.story is None and r.type != "short take"
               and (r.limit_words is None or r.limit_words > SHORT_TAKE_WORDS))

    found = [shelf.schools[k]["name"] for k in dict.fromkeys(p["school"] for i, p in shelf.prompts.items()
                                                              if i in deps.handoff_ids)]
    return StoryMapResponse(stories=req.stories, schools=found, not_on_shelf=deps.not_on_shelf, rows=rows,
                            shared=shared, gaps=gaps, total_words=total, total_note=" ".join(note),
                            advice=plan.advice)
