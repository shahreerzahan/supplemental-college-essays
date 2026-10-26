# The Unwritten Shelf

Browse supplemental essay prompts for top US colleges, plus Oxford and Cambridge, as books on a bookshelf. AI agents help students find prompts and plan which of their stories fit which prompts.

## The agents

Two PydanticAI agents, both on `gpt-6-luna` through Portkey:

- **Librarian** (`app/prompts/librarian.md`): answers only from `data/shelf.json` through four tools (`search_shelf`, `get_prompt`, `prompts_for_schools`, `list_examples`). It powers **Ask the shelf** (returns prompt ids, and the page lights up those books) and **Decode this prompt** on each reading card.
- **Essay Coach** (`app/prompts/coach.md`): builds a **Story Map** from a student's schools and 3 to 5 short stories. It gets its prompts by asking the Librarian (the handoff tool `ask_librarian`). It coaches but never writes essays.

Checks in `app/agents.py` send an agent back to fix its answer if it cites an id no tool returned, skips a required prompt, maps more options than a "choose N" set allows, or starts writing the student's sentences. Source links are attached from the data, never from model text. Schools that aren't on the shelf are reported as such.

API: `POST /api/ask`, `POST /api/decode`, `POST /api/story-map`.

## Safety

Guards in `app/guard.py` run before any model call, and output checks in `app/agents.py` run after:

- **No ghostwriting**: a request to write an essay gets a polite no, a Story Map offer, and questions to think about. The Coach's output checks also reject anything that reads like the student's own sentences.
- **Prompt injection**: everything a student types is wrapped as `<student_input>` data, and fake tags are defanged. The system prompts say never to follow instructions inside it, and an output check rejects answers that repeat the system prompt. Instruction-like text is flagged and logged. (Azure OpenAI's own content filter also blocks blunt jailbreaks; the app answers those with a friendly message.)
- **No made-up prompts**: the tools are the only source of prompts, and output checks reject prompt ids no tool returned and quotes that aren't in the shelf data.
- **Budgets**: 6 model requests per run (a Story Map's Librarian handoff included), 1,500 characters of input per request, and 20,000 tokens per browser session. Each limit ends in a friendly message.
- **Audit trail**: every agent step (guard decisions, input, tool calls and results, retries, output, errors) is appended to `output/audit_trail.json`, which is git-ignored because it holds what students typed.

Run the attack tests (they write `output/safety_tests.json`):

```bash
.venv/bin/python -m pytest tests/test_safety.py -v
```

## Token use

- After every agent run the page shows a meter: input tokens, cached input tokens, output tokens, model requests, and cost. Cost stays blank until you fill in gpt-6-luna's prices (the TODO in `app/config.py`).
- Every run is appended to `output/token_log.json`: time, agent, what was asked, tokens, cost. The file is git-ignored because it holds what students typed.
- Portkey's response cache can answer a repeated request without calling the model. Those requests are counted as Portkey cache hits, with no billed tokens.
- To keep cost down, each agent's system prompt is fixed (so it stays cached) and per-run details go in the request. Tools send only the matching prompts, and answers light up at most 8 books. **Lean mode** (switch by the Ask box) drops that to 3 and trims tool results, so you can compare quality and cost.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then add your Portkey key
.venv/bin/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

The app reads `.env` from this folder first, then from the folder one level above it. It only uses `gpt-6-luna`, through Portkey.

## Layout

- `app/`: FastAPI app (`main.py`), settings (`config.py`), types (`models.py`), shelf tools (`tools.py`), agents (`agents.py`), agent prompts (`prompts/`), and the single HTML page (`static/`)
- `data/`: essay prompt data
- `output/`: generated output and screenshots
- `tests/`: tests
