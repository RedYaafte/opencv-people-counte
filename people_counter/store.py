"""SQLite storage for analysis sessions and crossing events."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from .tracking import Crossing


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class LineConfig:
    orientation: str = "horizontal"
    line_position: float = 0.5
    entry_direction: str = "forward"

    def __post_init__(self) -> None:
        if self.orientation not in ("horizontal", "vertical"):
            raise ValueError("Invalid line orientation")
        if not 0.05 <= self.line_position <= 0.95:
            raise ValueError("Line position must be between 0.05 and 0.95")
        if self.entry_direction not in ("forward", "reverse"):
            raise ValueError("Invalid entry direction")


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    orientation TEXT NOT NULL,
                    line_position REAL NOT NULL,
                    entry_direction TEXT NOT NULL,
                    frames INTEGER NOT NULL DEFAULT 0,
                    total_frames INTEGER NOT NULL DEFAULT 0,
                    elapsed_seconds REAL NOT NULL DEFAULT 0,
                    entries INTEGER NOT NULL DEFAULT 0,
                    exits INTEGER NOT NULL DEFAULT 0,
                    output_available INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    time_seconds REAL NOT NULL,
                    frame INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    direction TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session_time ON events(session_id, time_seconds);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, source_type: str, source_name: str, config: LineConfig) -> str:
        if source_type not in ("upload", "camera"):
            raise ValueError("Invalid source type")
        session_id = str(uuid4())
        with self.connection() as db:
            db.execute("""
                INSERT INTO sessions (id, source_type, source_name, status, created_at,
                                      orientation, line_position, entry_direction)
                VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
            """, (session_id, source_type, source_name, utc_now(), config.orientation,
                  config.line_position, config.entry_direction))
        return session_id

    def get(self, session_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["occupancy"] = result["entries"] - result["exits"]
        result["output_available"] = bool(result["output_available"])
        return result

    def recent(self, limit: int = 10) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT id FROM sessions ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self.get(row["id"]) for row in rows]

    def events(self, session_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("""
                SELECT time_seconds, frame, track_id, direction FROM events
                WHERE session_id = ? ORDER BY id
            """, (session_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, session_id: str, status: str, error: str | None = None,
                   output_available: bool = False) -> None:
        if status not in ("running", "completed", "failed"):
            raise ValueError("Invalid session status")
        finished_at = utc_now() if status != "running" else None
        with self.connection() as db:
            db.execute("""
                UPDATE sessions SET status = ?, finished_at = ?, error = ?, output_available = ?
                WHERE id = ?
            """, (status, finished_at, error, int(output_available), session_id))

    def set_total_frames(self, session_id: str, total_frames: int) -> None:
        with self.connection() as db:
            db.execute("UPDATE sessions SET total_frames = ? WHERE id = ?", (max(total_frames, 0), session_id))

    def mark_interrupted(self) -> None:
        """Close sessions left running when the local server was stopped."""
        with self.connection() as db:
            db.execute("""
                UPDATE sessions SET status = 'failed', finished_at = ?,
                    error = 'Analysis was interrupted when the server stopped'
                WHERE status IN ('queued', 'running')
            """, (utc_now(),))

    def record_frame(self, session_id: str, frame: int, time_seconds: float,
                     entries: int, exits: int, events: list[Crossing]) -> None:
        with self.connection() as db:
            db.execute("""
                UPDATE sessions SET frames = ?, elapsed_seconds = ?, entries = ?, exits = ?
                WHERE id = ?
            """, (frame, time_seconds, entries, exits, session_id))
            db.executemany("""
                INSERT INTO events (session_id, time_seconds, frame, track_id, direction)
                VALUES (?, ?, ?, ?, ?)
            """, [(session_id, time_seconds, frame, event.track_id, event.direction)
                  for event in events])
