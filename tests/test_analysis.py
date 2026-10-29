import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

from people_counter.analysis import AnalysisService
from people_counter.store import LineConfig, SessionStore


class FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        centers = (20, 60, 100)
        y = centers[min(self.calls, len(centers) - 1)]
        self.calls += 1
        return [(50, y - 20, 20, 40)]


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class AnalysisServiceTests(unittest.TestCase):
    def test_uploaded_video_is_annotated_and_events_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 5, (128, 128))
            self.assertTrue(writer.isOpened())
            for _ in range(3):
                writer.write(np.zeros((128, 128, 3), dtype=np.uint8))
            writer.release()

            store = SessionStore(root / "data" / "sessions.sqlite3")
            service = AnalysisService(store, root / "data")
            session_id = store.create("upload", "input.mp4", LineConfig())
            with patch("people_counter.analysis.HOGPersonDetector", return_value=FakeDetector()):
                service.process_upload(session_id, source)

            session = store.get(session_id)
            self.assertEqual(session["status"], "completed")
            self.assertEqual((session["frames"], session["entries"], session["exits"]), (3, 1, 0))
            self.assertEqual([event["direction"] for event in store.events(session_id)], ["entry"])
            self.assertTrue(service.output_path(session_id).is_file())
            self.assertFalse(source.exists())

    def test_camera_frames_update_counts_without_recording_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "data" / "sessions.sqlite3")
            service = AnalysisService(store, root / "data")
            session_id = store.create("camera", "Browser camera", LineConfig())
            ok, encoded = cv2.imencode(".jpg", np.zeros((128, 128, 3), dtype=np.uint8))
            self.assertTrue(ok)
            with patch("people_counter.analysis.HOGPersonDetector", return_value=FakeDetector()):
                analyzer = service.start_camera(session_id)
                for second in (0.0, 0.2, 0.4):
                    preview = service.process_camera_frame(session_id, analyzer, encoded.tobytes(), second)
                    self.assertTrue(preview.startswith(b"\xff\xd8"))
                service.stop_camera(session_id)

            session = store.get(session_id)
            self.assertEqual((session["status"], session["entries"], session["exits"]), ("completed", 1, 0))
            self.assertEqual([event["direction"] for event in store.events(session_id)], ["entry"])
            self.assertFalse(service.output_path(session_id).exists())


if __name__ == "__main__":
    unittest.main()
