"""Exercise upload reuse and reanalysis through the FastAPI route functions."""

import asyncio
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

from test_analysis import FakeDetector


class VideoRequest:
    def __init__(self, data: bytes):
        self.data = data

    async def stream(self):
        midpoint = len(self.data) // 2
        yield self.data[:midpoint]
        yield self.data[midpoint:]


class Tasks:
    def __init__(self):
        self.pending = []

    def add_task(self, function, *args):
        self.pending.append((function, args))

    def run(self):
        for function, args in self.pending:
            function(*args)


@unittest.skipIf(cv2 is None or importlib.util.find_spec("fastapi") is None
                 or not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                 "OpenCV, FastAPI, and FFmpeg are required")
class WebReuseTests(unittest.TestCase):
    def test_same_video_reuses_result_and_new_line_creates_session(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("PEOPLE_COUNTER_DATA_DIR")
            os.environ["PEOPLE_COUNTER_DATA_DIR"] = str(Path(directory) / "data")
            try:
                web = importlib.import_module("people_counter.web")
                web.store = web.SessionStore(Path(directory) / "data" / "sessions.sqlite3")
                web.service = web.AnalysisService(web.store, Path(directory) / "data")

                source = Path(directory) / "sample.mp4"
                writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 5, (128, 128))
                self.assertTrue(writer.isOpened())
                for _ in range(3):
                    writer.write(np.zeros((128, 128, 3), dtype=np.uint8))
                writer.release()
                video_bytes = source.read_bytes()

                with patch("people_counter.analysis.HOGPersonDetector", return_value=FakeDetector()):
                    tasks = Tasks()
                    first = asyncio.run(web.upload_video(VideoRequest(video_bytes), tasks,
                                                         "sample.mp4", "horizontal", 0.5, "forward"))
                    tasks.run()
                    self.assertEqual(web.store.get(first["id"])["status"], "completed")

                    tasks = Tasks()
                    reused = asyncio.run(web.upload_video(VideoRequest(video_bytes), tasks,
                                                          "sample.mp4", "horizontal", 0.5, "forward"))
                    self.assertEqual((reused["id"], reused["reused"], len(tasks.pending)),
                                     (first["id"], True, 0))

                    stored_source = web.service.source_path(reused["source_sha256"], ".mp4")
                    stored_source.unlink()
                    tasks = Tasks()
                    restored = asyncio.run(web.upload_video(VideoRequest(video_bytes), tasks,
                                                            "sample.mp4", "horizontal", 0.5, "forward"))
                    self.assertEqual((restored["id"], restored["reused"], stored_source.is_file()),
                                     (first["id"], True, True))

                    tasks = Tasks()
                    changed = web.CameraRequest(orientation="horizontal", line_position=0.6,
                                                entry_direction="forward")
                    second = web.reanalyze_upload(first["id"], changed, tasks)
                    tasks.run()
                    self.assertNotEqual(first["id"], second["id"])
                    self.assertEqual(web.store.get(second["id"])["status"], "completed")

                    tasks = Tasks()
                    cached_second = web.reanalyze_upload(first["id"], changed, tasks)
                    self.assertEqual((cached_second["id"], cached_second["reused"], len(tasks.pending)),
                                     (second["id"], True, 0))

                response = web.session_video(first["id"])
                self.assertEqual(response.status_code, 200)
                self.assertTrue(Path(response.path).is_file())
                codec = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                     "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
                     response.path], text=True,
                ).strip()
                self.assertEqual(codec, "h264")

                # Saved outputs from before browser playback support are converted on demand.
                shutil.copyfile(source, response.path)
                replay = web.session_video(first["id"])
                legacy_codec = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                     "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
                     replay.path], text=True,
                ).strip()
                self.assertEqual(legacy_codec, "h264")
                self.assertEqual(len(web.store.recent()), 2)
                self.assertEqual(len(list((Path(directory) / "data" / "sources").iterdir())), 1)

                self.assertEqual(web.delete_session(first["id"]).status_code, 204)
                self.assertIsNone(web.store.get(first["id"]))
                self.assertFalse(web.service.output_path(first["id"]).exists())
                self.assertTrue(stored_source.exists())
                self.assertEqual(web.delete_session(second["id"]).status_code, 204)
                self.assertFalse(web.service.output_path(second["id"]).exists())
                self.assertFalse(stored_source.exists())
                with self.assertRaises(web.HTTPException) as missing:
                    web.delete_session(first["id"])
                self.assertEqual(missing.exception.status_code, 404)

                active = web.store.create("camera", "Browser camera", web.LineConfig())
                with self.assertRaises(web.HTTPException) as conflict:
                    web.delete_session(active)
                self.assertEqual(conflict.exception.status_code, 409)
                web.store.set_status(active, "completed")
                self.assertEqual(web.delete_session(active).status_code, 204)
            finally:
                if previous is None:
                    os.environ.pop("PEOPLE_COUNTER_DATA_DIR", None)
                else:
                    os.environ["PEOPLE_COUNTER_DATA_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
