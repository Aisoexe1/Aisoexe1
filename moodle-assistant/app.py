"""FastAPI backend for Moodle Assistant."""
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from moodle import MoodleClient
import solver as solver_module

# ── State (single-user local app) ─────────────────────────────────────────────
moodle = MoodleClient()

state: dict = {
    "assignments": [],
    "details": {},    # id -> {description, submitted, can_submit}
    "solutions": {},  # id -> full text
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await moodle.start()
    yield
    await moodle.stop()


app = FastAPI(lifespan=lifespan)

# Serve static files
_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Models ─────────────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    username: str
    password: str


class SubmitBody(BaseModel):
    answer: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = (_static / "index.html").read_text()
    return HTMLResponse(html)


@app.get("/api/status")
async def status():
    return {
        "logged_in": moodle.logged_in,
        "username": moodle.username,
        "assignments_count": len(state["assignments"]),
    }


@app.post("/api/login")
async def login(body: LoginBody):
    result = await moodle.login(body.username, body.password)
    return result


@app.post("/api/logout")
async def logout():
    await moodle.logout()
    state["assignments"] = []
    state["details"] = {}
    state["solutions"] = {}
    return {"success": True}


@app.post("/api/scan")
async def scan():
    if not moodle.logged_in:
        raise HTTPException(401, "Not logged in")
    assignments = await moodle.get_assignments()
    state["assignments"] = assignments
    return {"assignments": assignments, "count": len(assignments)}


@app.get("/api/assignments")
async def get_assignments():
    return {"assignments": state["assignments"]}


@app.get("/api/assignment/{assignment_id}/details")
async def get_details(assignment_id: str):
    if assignment_id in state["details"]:
        d = state["details"][assignment_id]
        d["solution"] = state["solutions"].get(assignment_id, "")
        return d

    assignment = _find(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    details = await moodle.get_details(assignment["url"])
    state["details"][assignment_id] = details
    details["solution"] = state["solutions"].get(assignment_id, "")
    return details


@app.get("/api/solve/{assignment_id}")
async def solve(assignment_id: str):
    """SSE stream: Gemini solves the assignment."""
    if not moodle.logged_in:
        raise HTTPException(401, "Not logged in")

    assignment = _find(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    # Fetch details if not cached
    if assignment_id not in state["details"]:
        details = await moodle.get_details(assignment["url"])
        state["details"][assignment_id] = details
    else:
        details = state["details"][assignment_id]

    async def event_stream():
        full = ""
        try:
            async for chunk in solver_module.solve_stream(
                title=assignment["title"],
                description=details.get("description", ""),
                course=assignment.get("course", ""),
            ):
                full += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            state["solutions"][assignment_id] = full
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/debug")
async def debug():
    """Diagnostic endpoint — returns what Playwright sees during a scan attempt."""
    if not moodle.logged_in:
        raise HTTPException(401, "Not logged in")
    return await moodle.debug_scan()


@app.post("/api/submit/{assignment_id}")
async def submit(assignment_id: str, body: SubmitBody):
    if not moodle.logged_in:
        raise HTTPException(401, "Not logged in")

    assignment = _find(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    result = await moodle.submit(assignment["url"], body.answer)

    if result["success"]:
        # Mark as submitted
        for a in state["assignments"]:
            if a["id"] == assignment_id:
                a["submitted"] = True
        if assignment_id in state["details"]:
            state["details"][assignment_id]["submitted"] = True

    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find(assignment_id: str) -> dict | None:
    return next((a for a in state["assignments"] if a["id"] == assignment_id), None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8888, reload=False)
