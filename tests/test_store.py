import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
