# The Unwritten Shelf

Browse supplemental essay prompts for top US colleges, plus Oxford and Cambridge, as books on a bookshelf. AI agents help students find prompts and plan which of their stories fit which prompts.

## The agents

Two PydanticAI agents, both on `gpt-6-luna` through Portkey:

- **Librarian** (`app/prompts/librarian.md`): answers only from `data/shelf.json` through four tools (`search_shelf`, `get_prompt`, `prompts_for_schools`, `list_examples`). It powers **Ask the shelf** (returns prompt ids, and the page lights up those books) and **Decode this prompt** on each reading card.
- **Essay Coach** (`app/prompts/coach.md`): builds a **Story Map** from a student's schools and 3 to 5 short stories. It gets its prompts by asking the Librarian (the handoff tool `ask_librarian`). It coaches but never writes essays.

Checks in `app/agents.py` send an agent back to fix its answer if it cites an id no tool returned, skips a required prompt, maps more options than a "choose N" set allows, or starts writing the student's sentences. Source links are attached from the data, never from model text. Schools that aren't on the shelf are reported as such.

API: `POST /api/ask`, `POST /api/decode`, `POST /api/story-map`.

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
