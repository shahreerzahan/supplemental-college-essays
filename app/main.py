"""The Unwritten Shelf: FastAPI serves the single HTML page in app/static/, the shelf data, and the agents."""

import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import agents, config, guard
from app.models import (
    AskRequest, AskResponse, DecodeRequest, DecodeResponse, RefusalResponse, SessionOut, StoryMapRequest,
    StoryMapResponse,
)
from app.tools import Shelf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
log = logging.getLogger("shelf.api")

app = FastAPI(title="The Unwritten Shelf")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

SESSION_COOKIE = "shelf_session"


def session_id(request: Request, response: Response) -> str:
    """Each browser session gets an id (in a cookie) so its token budget can be counted."""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid or len(sid) > 64:
        sid = uuid.uuid4().hex
        response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax", max_age=12 * 60 * 60)
    return sid


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/shelf")
def shelf() -> FileResponse:
    """Every prompt and essay that worked, straight from data/shelf.json."""
    return FileResponse(config.SHELF_FILE, media_type="application/json")


@app.get("/api/session", response_model=SessionOut)
def session(sid: str = Depends(session_id)) -> SessionOut:
    """How much of this browser session's token budget is used."""
    return guard.session_out(sid)


async def _run(work, what: str):
    """Run an agent call and turn failures into short messages for the page."""
    try:
        return await work
    except config.MissingKey as err:
        log.error("%s: %s", what, err)
        raise HTTPException(503, "The shelf's AI isn't set up on this server (missing Portkey key).") from err
    except Exception as err:
        log.exception("%s failed", what)
        raise HTTPException(502, "The librarians couldn't finish that one. Please try again.") from err


@app.post("/api/ask", response_model=AskResponse | RefusalResponse)
async def ask(req: AskRequest, sid: str = Depends(session_id)):
    """Ask the Librarian a question about the shelf."""
    return await _run(agents.ask_shelf(req.question, req.lean, sid), "ask")


@app.post("/api/decode", response_model=DecodeResponse | RefusalResponse)
async def decode(req: DecodeRequest, sid: str = Depends(session_id)):
    """The Librarian's read of one prompt: what it's really asking, common mistakes, what to read."""
    if req.prompt_id not in Shelf.get().prompts:
        raise HTTPException(404, f"No prompt {req.prompt_id!r} on the shelf.")
    return await _run(agents.decode_prompt(req.prompt_id, req.lean, sid), "decode")


@app.post("/api/story-map", response_model=StoryMapResponse | RefusalResponse)
async def story_map(req: StoryMapRequest, sid: str = Depends(session_id)):
    """The Essay Coach maps the student's stories to their schools' prompts."""
    return await _run(agents.build_story_map(req, sid), "story map")
