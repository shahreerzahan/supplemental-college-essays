"""Types shared by the tools, the two agents, and the API."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from app.tools import Shelf


# ---------- What the tools return ----------

class PromptBrief(BaseModel):
    """One prompt as the tools describe it. Text and source always come from data/shelf.json."""

    id: str
    school: str
    school_name: str
    type: str
    prompt: str
    limit: str = Field(description='Human-readable limit, e.g. "250 words" or "No stated limit".')
    limit_words: int | None = Field(description="Word limit (character limits converted at ~6 characters per word).")
    required: bool
    choice: str | None = Field(description='e.g. "Choose 1 of 3 (group yale-essay)" when the prompt is one option in a set.')
    audience: str | None = Field(description="Set when only some applicants answer it, e.g. one college within a university.")
    source_url: str


class PromptFull(PromptBrief):
    notes: str | None
    sample_ids: list[str] = Field(description="College Essay Guy sample breakdowns for this prompt (use list_examples).")
    essay_ids: list[str] = Field(description="Essays that worked from the same school (use list_examples).")


class SearchResult(BaseModel):
    matches: list[PromptBrief]
    total_matches: int
    not_on_shelf: list[str] = Field(description="Schools asked about that the shelf doesn't have.")
    note: str | None = None


class SchoolPrompts(BaseModel):
    school: str
    school_name: str
    prompts: list[PromptBrief]
    school_notes: list[str]


class SchoolsResult(BaseModel):
    schools: list[SchoolPrompts]
    not_on_shelf: list[str]
    note: str | None = None


class Example(BaseModel):
    id: str
    kind: Literal["sample", "essay"] = Field(description="sample = College Essay Guy breakdown; essay = an essay that worked.")
    school_name: str | None
    title: str
    for_prompts: list[str] = Field(description="Prompt ids this example answers (samples only).")
    summary: str
    why_it_works: list[str]
    source_url: str


class ExamplesResult(BaseModel):
    examples: list[Example]
    note: str | None = None


# ---------- What the agents return ----------

class ShelfAnswer(BaseModel):
    """The Librarian's answer to a question typed into "Ask the shelf"."""

    answer: str = Field(description="2-4 plain sentences, based only on tool results. Mention any school not on the shelf.")
    prompt_ids: list[str] = Field(description="Ids of the prompts that answer the question; the site lights these books up.")
    example_ids: list[str] = Field(default_factory=list, description="Ids of any samples or essays the answer cites.")
    not_on_shelf: list[str] = Field(default_factory=list, description="Schools the student asked about that the shelf doesn't have.")


class ReadThis(BaseModel):
    example_id: str
    why: str = Field(description="One short sentence: what to look for in it.")


class PromptDecode(BaseModel):
    """The Librarian's "Decode this prompt" read of one prompt."""

    really_asking: str = Field(description="2-3 sentences: what the admissions office is really trying to learn.")
    common_mistakes: list[str] = Field(description="3-4 short, specific mistakes students make with this prompt.")
    read_these: list[ReadThis] = Field(description="1-3 example ids from list_examples, best first. Empty if none exist.")


class PromptList(BaseModel):
    """The Librarian's handoff to the Coach: which prompts apply to a student's schools."""

    prompt_ids: list[str]
    not_on_shelf: list[str] = Field(default_factory=list)


class MapRow(BaseModel):
    prompt_id: str
    story: int | None = Field(description="1-based number of the student's story for this prompt, or null if none fits (a gap).")
    fit: Literal["strong", "good", "stretch"] | None = Field(description="How well the story fits; null for a gap.")
    why: str = Field(description="Max ~30 words: why the story fits, or for a gap why none of the stories do.")
    coaching: str = Field(description="Max ~35 words, addressed to the student as 'you': an angle or a question to think about. Never essay sentences.")


class SharedStory(BaseModel):
    story: int
    prompt_ids: list[str]
    how_to_vary: str = Field(description="Max ~35 words: how to tell the same story differently for each prompt.")


class StoryMapPlan(BaseModel):
    """The Coach's Story Map."""

    declined: str | None = Field(default=None, description=(
        "Only if the student asked you to write, draft or rewrite an essay or part of one: one or two polite "
        "sentences saying you won't, and that the map and questions are here to help instead. Otherwise null."))
    rows: list[MapRow] = Field(description="One row per prompt the student should write, gaps included.")
    shared: list[SharedStory] = Field(default_factory=list, description="Stories used for more than one prompt.")
    advice: list[str] = Field(default_factory=list, description="Up to 3 short next steps, addressed to the student.")


# ---------- Run-time dependencies ----------

@dataclass
class LibrarianDeps:
    shelf: "Shelf"
    job: Literal["ask", "decode", "handoff"] = "ask"
    focus: str | None = None  # the prompt being decoded, if any
    lean: bool = False
    cap: int = 8              # most books/examples a tool returns (3 in lean mode)
    tool_calls: list[str] = field(default_factory=list)
    schools_looked_up: set[str] = field(default_factory=set)
    seen_prompt_ids: set[str] = field(default_factory=set)
    seen_example_ids: set[str] = field(default_factory=set)
    not_on_shelf: set[str] = field(default_factory=set)


@dataclass
class CoachDeps:
    shelf: "Shelf"
    librarian: Any  # the Librarian agent; passed in so tools.py needn't import agents.py
    stories: list[str]
    applying_to: str | None = None
    lean: bool = False
    run_id: str = ""   # for the audit trail
    session: str = ""
    handoff_ids: set[str] = field(default_factory=set)
    not_on_shelf: list[str] = field(default_factory=list)
    handoff_usage: dict[str, int] = field(default_factory=dict)  # the Librarian's share of the tokens
    handoff_calls: list[dict] = field(default_factory=list)      # its model responses (for Portkey cache hits)


# ---------- API requests and responses ----------

class UsageOut(BaseModel):
    """The token meter shown after every agent run."""

    agent: str
    input_tokens: int = Field(description="All billed input tokens, cached ones included.")
    cached_input_tokens: int = Field(description="Input tokens read from the prompt cache.")
    cache_write_tokens: int
    output_tokens: int
    requests: int = Field(description="Model requests in the run.")
    portkey_cache_hits: int = Field(default=0, description="Requests Portkey answered from its cache (no new tokens).")
    tool_calls: int
    cost_usd: float | None = Field(description="None until the prices in app/config.py are filled in.")
    lean: bool
    from_cache: bool = Field(default=False, description="True when an earlier answer was reused with no model call.")
    handoff: "UsageOut | None" = Field(default=None, description="The Librarian's share of a Story Map run.")


class SessionOut(BaseModel):
    """This browser session's token budget."""

    used: int
    cap: int
    remaining: int


class Refusal(BaseModel):
    """A friendly no: why, what to do instead."""

    reason: Literal["ghostwriting", "too_long", "run_budget", "session_budget", "content_filter"]
    message: str
    questions: list[str] = Field(default_factory=list, description="Questions to think about instead (ghostwriting).")
    offer_story_map: bool = False


class RefusalResponse(BaseModel):
    refusal: Refusal
    session: SessionOut


class AskRequest(BaseModel):
    # Generous here so the guard can answer an over-long question with a friendly message.
    question: str = Field(min_length=3, max_length=20_000)
    lean: bool = False


class Source(BaseModel):
    label: str
    url: str


class AskResponse(BaseModel):
    answer: str
    prompt_ids: list[str]
    not_on_shelf: list[str]
    sources: list[Source]
    usage: UsageOut
    session: SessionOut
    flagged_injection: bool = Field(default=False, description="The question had instruction-like text, treated as data.")


class DecodeRequest(BaseModel):
    prompt_id: str = Field(max_length=40)
    lean: bool = False


class ReadThisOut(BaseModel):
    id: str
    kind: Literal["sample", "essay"]
    title: str
    why: str
    open_id: str = Field(description="The book to open on the site: the prompt a sample belongs to, or the essay itself.")
    source_url: str


class DecodeResponse(BaseModel):
    prompt_id: str
    really_asking: str
    common_mistakes: list[str]
    read_these: list[ReadThisOut]
    source_url: str
    usage: UsageOut
    session: SessionOut


class StoryMapRequest(BaseModel):
    # Lengths are checked by the guard (config.MAX_INPUT_CHARS for the whole request), which answers
    # with a friendly message instead of a validation error.
    schools: list[str] = Field(min_length=1, max_length=10)
    stories: list[str] = Field(min_length=3, max_length=5)
    applying_to: str | None = Field(default=None, max_length=5_000)
    lean: bool = False

    @field_validator("stories")
    @classmethod
    def short_stories(cls, stories: list[str]) -> list[str]:
        cleaned = [" ".join(s.split()) for s in stories]
        if any(len(s) < 2 for s in cleaned):
            raise ValueError("Each story needs a few words.")
        return cleaned

    @field_validator("schools")
    @classmethod
    def clean_schools(cls, schools: list[str]) -> list[str]:
        cleaned = [" ".join(s.split()) for s in schools if s.strip()]
        if not cleaned:
            raise ValueError("Pick at least one school.")
        return cleaned


class MapRowOut(BaseModel):
    prompt_id: str
    school: str
    school_name: str
    type: str
    prompt: str
    limit: str
    limit_words: int | None
    required: bool
    choice: str | None
    source_url: str
    story: int | None
    fit: str | None
    why: str
    coaching: str


class StoryMapResponse(BaseModel):
    stories: list[str]
    schools: list[str]
    not_on_shelf: list[str]
    rows: list[MapRowOut]
    shared: list[SharedStory]
    gaps: int
    total_words: int
    total_note: str
    advice: list[str]
    declined: str | None = None
    usage: UsageOut
    session: SessionOut
    flagged_injection: bool = False
