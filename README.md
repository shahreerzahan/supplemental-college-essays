# The Unwritten Shelf

Browse supplemental essay prompts for top US colleges, plus Oxford and Cambridge, as books on a bookshelf. AI agents help students find prompts and plan which of their stories fit which prompts.

> Work in progress: project setup only, no features yet.

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

- `app/`: FastAPI app (`main.py`), settings (`config.py`), agent prompts (`prompts/`), and the single HTML page (`static/`)
- `data/`: essay prompt data
- `output/`: generated output and screenshots
- `tests/`: tests
