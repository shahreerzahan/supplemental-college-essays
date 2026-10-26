# The Unwritten Shelf

The Unwritten Shelf shows the 2026-27 supplemental essay prompts for 15 top US colleges, plus Oxford and Cambridge, as books on a bookshelf, with two AI agents that help students find prompts and plan which of their stories fit them.

## Run it from a fresh clone

You need Python 3 (built and tested with 3.14), a Portkey API key that can use `gpt-6-luna`, and access to this private repository.

1. Clone the repo and go into it:

   ```bash
   git clone https://github.com/shahreerzahan/supplemental-college-essays.git
   ```

   ```bash
   cd supplemental-college-essays
   ```

2. Make a virtual environment, turn it on, and install the requirements:

   ```bash
   python3 -m venv .venv
   ```

   ```bash
   source .venv/bin/activate
   ```

   ```bash
   pip install -r requirements.txt
   ```

   On Windows, turn it on with `.venv\Scripts\activate` instead.

3. Add your Portkey key. Make a file called `.env`, either in the repo folder or in the folder one level above it, with this one line:

   ```
   PORTKEY_API_KEY=your-key-here
   ```

   That's the only setting you need: the app always uses `gpt-6-luna`. (`.env.example` is a template, and `.env` is git-ignored, so your key stays out of the repo.)

4. Start the app:

   ```bash
   uvicorn app.main:app --port 8000
   ```

5. Open http://localhost:8000.

## Things to try

- **Open a book.** Click any spine to read its prompt, limit and source, then press **Decode this prompt** to see what it's really asking and the common mistakes.
- **Let the shelf pick.** Press **Surprise me**: a book lifts off the shelf under a spotlight, with a handwritten "this one!".
- **Ask the shelf.** Try "show me why-us prompts under 250 words". The matching books light up and the rest fade.
- **Build a Story Map.** Pick a couple of schools, jot down three stories in a few words each, and press **Build my Story Map** to see which story fits which prompt and where you still need one.
- **Compare lean mode.** Ask the same question with **Lean mode** on and off, and compare the token meters under the answers.
- **Test the guardrails.** Ask "Write my Yale essay about robotics" to get a polite no and questions to think about instead.
- **Run the safety tests** (they call the real model and save their results to `output/safety_tests.json`):

  ```bash
  python -m pytest tests/test_safety.py -v
  ```

Every agent answer uses tokens. Each browser session gets 20,000, which is about two Story Maps or four or five questions.

## The agents

Two PydanticAI agents, both on `gpt-6-luna` through Portkey:

- **Librarian** (`app/prompts/librarian.md`): answers only from `data/shelf.json`, through four tools (`search_shelf`, `get_prompt`, `prompts_for_schools`, `list_examples`). It powers **Ask the shelf** and **Decode this prompt**.
- **Essay Coach** (`app/prompts/coach.md`): builds a **Story Map** from a student's schools and 3 to 5 short stories. It gets its prompts by asking the Librarian (the handoff tool `ask_librarian`). It coaches, but never writes essays.

Checks in `app/agents.py` send an agent back to fix its answer if it cites an id no tool returned, skips a required prompt, maps more options than a "choose N" set allows, or starts writing the student's sentences. Source links come from the data, never from model text.

API: `POST /api/ask`, `POST /api/decode`, `POST /api/story-map`, `GET /api/session`.

## Safety

Guards in `app/guard.py` run before any model call, and output checks in `app/agents.py` run after:

- **No ghostwriting**: a request to write an essay gets a polite no, a Story Map offer, and questions to think about.
- **Prompt injection**: everything a student types is wrapped as `<student_input>` data with fake tags defanged; the system prompts say never to follow instructions inside it; an output check rejects answers that repeat the system prompt. Azure OpenAI's own content filter also blocks blunt jailbreaks, and the app answers those with a friendly message.
- **No made-up prompts**: the tools are the only source of prompts, and output checks reject prompt ids no tool returned and quotes that aren't in the shelf data.
- **Budgets**: 6 model requests per run (a Story Map's Librarian handoff included), 1,500 characters of input per request, and 20,000 tokens per browser session, each with a friendly message.
- **Audit trail**: every agent step is appended to `output/audit_trail.json` (git-ignored, because it holds what students typed).

## Token use

- After every agent run the page shows a meter: input tokens, cached input tokens, output tokens, model requests, and cost. Cost stays blank until gpt-6-luna's prices are filled in (the TODO in `app/config.py`).
- Every run is appended to `output/token_log.json` (git-ignored).
- Portkey's response cache can answer a repeated request without calling the model; those requests count as Portkey cache hits, with no billed tokens.
- Each agent's system prompt is fixed so it stays cached, tools send only the matching prompts, and answers light up at most 8 books. **Lean mode** (the switch by the Ask box) drops that to 3 and trims tool results.

## Layout

- `app/`: the FastAPI app (`main.py`), settings (`config.py`), types (`models.py`), shelf tools (`tools.py`), agents (`agents.py`), guards (`guard.py`), token meter (`usage.py`), audit trail (`audit.py`), agent prompts (`prompts/`), and the single HTML page (`static/`)
- `data/shelf.json`: the prompts, sample-essay breakdowns, and essays that worked
- `output/`: safety test results, the user test report, and screenshots
- `tests/`: the safety tests
