"""Settings: where .env lives, project paths, and the one allowed model."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Keep PydanticAI's startup banner out of the server log.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

# Look for .env in this repo first, then one folder above it. load_dotenv never
# overwrites a variable that is already set, so the repo's .env wins.
ENV_FILES = (ROOT / ".env", ROOT.parent / ".env")
for env_file in ENV_FILES:
    if env_file.is_file():
        load_dotenv(env_file)

STATIC_DIR = ROOT / "app" / "static"
TOKEN_LOG = ROOT / "output" / "token_log.json"
PROMPTS_DIR = ROOT / "app" / "prompts"
DATA_DIR = ROOT / "data"
SHELF_FILE = DATA_DIR / "shelf.json"
OUTPUT_DIR = ROOT / "output"

# Every agent uses gpt-6-luna through Portkey, and nothing else.
MODEL_NAME = "gpt-6-luna"
if os.getenv("MODEL_NAME", MODEL_NAME) != MODEL_NAME:
    raise RuntimeError(f"MODEL_NAME must be {MODEL_NAME!r}; this project only uses gpt-6-luna.")


# ---------------------------------------------------------------------------------------------
# TODO(shahreer): fill in gpt-6-luna's prices, in US dollars per 1 million tokens.
# Take them from Portkey's or the model provider's price sheet. Until the three required prices
# are set, the app shows token counts but says the cost isn't set.
PRICE_PER_MILLION_INPUT: float | None = None         # TODO: input tokens not served from the cache
PRICE_PER_MILLION_CACHED_INPUT: float | None = None  # TODO: input tokens read from the prompt cache
PRICE_PER_MILLION_OUTPUT: float | None = None        # TODO: output tokens (reasoning tokens count as output)
# Optional: only if gpt-6-luna bills cache writes at their own rate. None bills them as input.
PRICE_PER_MILLION_CACHE_WRITE: float | None = None
# ---------------------------------------------------------------------------------------------

# How many books an answer may light up, normally and in lean mode.
MAX_RESULTS = 8
LEAN_RESULTS = 3

# Safety budgets.
MAX_REQUESTS_PER_RUN = 6      # model requests per agent run (a Story Map's Librarian handoff counts too)
MAX_INPUT_CHARS = 1_500       # characters a student can send in one request
SESSION_TOKEN_CAP = 20_000    # billed tokens per browser session
# Typical tokens one run uses (from measured runs). A run only starts if the session has this much
# left; once started it always finishes, even if it ends up a little past the cap.
RUN_TOKEN_ESTIMATE = {"ask": 5_000, "decode": 5_000, "story-map": 12_000}

AUDIT_TRAIL = ROOT / "output" / "audit_trail.json"


class MissingKey(RuntimeError):
    pass


def portkey_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise MissingKey("PORTKEY_API_KEY is not set; add it to .env in this folder or the one above it.")
    return key
