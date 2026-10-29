import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3

from people_counter.store import LineConfig, SessionStore
from people_counter.tracking import Crossing


class SessionStoreTests(unittest.TestCase):
    def test_session_events_and_occupancy_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.sqlite3"
            store = SessionStore(path)
            session_id = store.create("upload", "sample.mp4", LineConfig("vertical", 0.6, "reverse"))
            store.set_status(session_id, "running")
            store.set_total_frames(session_id, 4)
            store.record_frame(session_id, 2, 0.5, 1, 0, [Crossing(1, "entry")])
            store.record_frame(session_id, 4, 1.0, 1, 1, [Crossing(2, "exit")])
            store.set_status(session_id, "completed", output_available=True)

            reopened = SessionStore(path)
            session = reopened.get(session_id)
            self.assertEqual((session["entries"], session["exits"], session["occupancy"]), (1, 1, 0))
            self.assertEqual((session["status"], session["frames"], session["total_frames"]), ("completed", 4, 4))
            self.assertTrue(session["output_available"])
            self.assertEqual([event["direction"] for event in reopened.events(session_id)], ["entry", "exit"])

    def test_interrupted_sessions_are_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session_id = store.create("camera", "Browser camera", LineConfig())
            store.mark_interrupted()
            self.assertEqual(store.get(session_id)["status"], "failed")

    def test_matching_uploads_respects_source_settings_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            config = LineConfig()
            session_id = store.create("upload", "source.mp4", config, "a" * 64, ".mp4", "v1")
            store.set_status(session_id, "completed", output_available=True)
            self.assertEqual(store.matching_uploads("a" * 64, config, "v1")[0]["id"], session_id)
            self.assertEqual(store.matching_uploads("b" * 64, config, "v1"), [])
            self.assertEqual(store.matching_uploads("a" * 64, LineConfig(line_position=0.6), "v1"), [])
            self.assertEqual(store.matching_uploads("a" * 64, config, "v2"), [])

    def test_delete_removes_events_and_keeps_shared_source_until_last_session(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            first = store.create("upload", "sample.mp4", LineConfig(), "a" * 64, ".mp4")
            second = store.create("upload", "sample.mp4", LineConfig(line_position=0.6),
                                  "a" * 64, ".mp4")
            store.record_frame(first, 1, 0.0, 1, 0, [Crossing(1, "entry")])
            store.set_status(first, "completed", output_available=True)
            store.set_status(second, "completed", output_available=True)

            deleted, source_unused = store.delete(first)
            self.assertEqual(deleted["id"], first)
            self.assertFalse(source_unused)
            self.assertIsNone(store.get(first))
            self.assertEqual(store.events(first), [])
            self.assertIsNotNone(store.get(second))
            self.assertTrue(store.delete(second)[1])
            self.assertIsNone(store.delete(second))

    def test_running_session_cannot_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session_id = store.create("camera", "Browser camera", LineConfig())
            with self.assertRaisesRegex(ValueError, "Stop the analysis"):
                store.delete(session_id)
            self.assertIsNotNone(store.get(session_id))

    def test_existing_database_is_migrated_without_losing_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.sqlite3"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("""
                    CREATE TABLE sessions (
                        id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_name TEXT NOT NULL,
                        status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT,
                        orientation TEXT NOT NULL, line_position REAL NOT NULL,
                        entry_direction TEXT NOT NULL, frames INTEGER NOT NULL DEFAULT 0,
                        total_frames INTEGER NOT NULL DEFAULT 0, elapsed_seconds REAL NOT NULL DEFAULT 0,
                        entries INTEGER NOT NULL DEFAULT 0, exits INTEGER NOT NULL DEFAULT 0,
                        output_available INTEGER NOT NULL DEFAULT 0, error TEXT
                    )
                """)
                db.execute("""
                    INSERT INTO sessions (id, source_type, source_name, status, created_at,
                                          orientation, line_position, entry_direction)
                    VALUES ('old', 'upload', 'old.mp4', 'completed', '2026-01-01',
                            'horizontal', 0.5, 'forward')
                """)
            store = SessionStore(path)
            self.assertEqual(store.get("old")["source_name"], "old.mp4")
            self.assertIsNone(store.get("old")["source_sha256"])


if __name__ == "__main__":
    unittest.main()
