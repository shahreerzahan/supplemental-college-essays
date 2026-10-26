"""The Unwritten Shelf: FastAPI serves the single HTML page in app/static/ and the shelf data."""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config

app = FastAPI(title="The Unwritten Shelf")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/shelf")
def shelf() -> FileResponse:
    """Every prompt and essay that worked, straight from data/shelf.json."""
    return FileResponse(config.SHELF_FILE, media_type="application/json")
