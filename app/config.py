"""Settings: where .env lives, project paths, and the one allowed model."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Look for .env in this repo first, then one folder above it. load_dotenv never
# overwrites a variable that is already set, so the repo's .env wins.
ENV_FILES = (ROOT / ".env", ROOT.parent / ".env")
for env_file in ENV_FILES:
    if env_file.is_file():
        load_dotenv(env_file)

STATIC_DIR = ROOT / "app" / "static"
PROMPTS_DIR = ROOT / "app" / "prompts"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

# Every agent uses gpt-6-luna through Portkey, and nothing else.
MODEL_NAME = "gpt-6-luna"
if os.getenv("MODEL_NAME", MODEL_NAME) != MODEL_NAME:
    raise RuntimeError(f"MODEL_NAME must be {MODEL_NAME!r}; this project only uses gpt-6-luna.")


def portkey_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set; add it to .env in this folder or the one above it.")
    return key
