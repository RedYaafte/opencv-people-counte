"""Local FastAPI interface for uploaded videos and browser camera analysis."""

import asyncio
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import AnalysisService
from .store import LineConfig, SessionStore

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PEOPLE_COUNTER_DATA_DIR", ROOT / "data"))
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

store = SessionStore(DATA_DIR / "sessions.sqlite3")
store.mark_interrupted()
service = AnalysisService(store, DATA_DIR)
app = FastAPI(title="OpenCV People Counter", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")


class CameraRequest(BaseModel):
    orientation: str = "horizontal"
    line_position: float = 0.5
    entry_direction: str = "forward"


def validate_config(orientation: str, line_position: float, entry_direction: str) -> LineConfig:
    try:
        return LineConfig(orientation, line_position, entry_direction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def require_session(session_id: str) -> dict:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/sessions")
def recent_sessions():
    return store.recent()


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    session = require_session(session_id)
    session["events"] = store.events(session_id)
    return session


@app.get("/api/sessions/{session_id}/frame")
def session_frame(session_id: str):
    require_session(session_id)
    frame = service.latest_frame(session_id)
    if frame is None:
        return Response(status_code=204)
    return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/sessions/{session_id}/video")
def session_video(session_id: str):
    session = require_session(session_id)
    path = service.output_path(session_id)
    if not session["output_available"] or not path.is_file():
        raise HTTPException(status_code=404, detail="Annotated video is not ready")
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/sessions/upload", status_code=202)
async def upload_video(
    request: Request,
    background_tasks: BackgroundTasks,
    filename: str = "video.mp4",
    orientation: str = "horizontal",
    line_position: float = 0.5,
    entry_direction: str = "forward",
):
    config = validate_config(orientation, line_position, entry_direction)
    source_name = filename.replace("\\", "/").split("/")[-1]
    suffix = Path(source_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload an MP4, MOV, AVI, MKV, or WebM video")
    temporary_path = service.data_dir / "uploads" / f"{uuid4()}{suffix}"
    size = 0
    try:
        with temporary_path.open("wb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video exceeds the 250 MB limit")
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded video is empty")
        session_id = store.create("upload", source_name, config)
        background_tasks.add_task(service.process_upload, session_id, temporary_path)
        return store.get(session_id)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


@app.post("/api/sessions/camera", status_code=201)
def create_camera_session(request: CameraRequest):
    config = validate_config(request.orientation, request.line_position, request.entry_direction)
    session_id = store.create("camera", "Browser camera", config)
    return store.get(session_id)


@app.post("/api/sessions/{session_id}/cancel")
def cancel_queued_camera(session_id: str):
    session = require_session(session_id)
    if session["source_type"] != "camera":
        raise HTTPException(status_code=409, detail="Only camera sessions can be cancelled")
    if session["status"] == "queued":
        store.set_status(session_id, "completed")
    return store.get(session_id)


@app.websocket("/ws/sessions/{session_id}")
async def camera_stream(websocket: WebSocket, session_id: str):
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and origin not in (f"http://{host}", f"https://{host}"):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        analyzer = await asyncio.to_thread(service.start_camera, session_id)
    except ValueError as exc:
        await websocket.send_json({"error": str(exc)})
        await websocket.close(code=1008)
        return

    started = monotonic()
    error = None
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect" or message.get("text") == "stop":
                break
            encoded = message.get("bytes")
            if not encoded:
                continue
            elapsed = monotonic() - started
            preview = await asyncio.to_thread(service.process_camera_frame, session_id, analyzer, encoded, elapsed)
            await websocket.send_json({"session": store.get(session_id), "events": store.events(session_id)})
            await websocket.send_bytes(preview)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        error = str(exc)[:300]
        try:
            await websocket.send_json({"error": error})
        except Exception:
            pass
    finally:
        await asyncio.to_thread(service.stop_camera, session_id, error)
        try:
            await websocket.close()
        except Exception:
            pass
