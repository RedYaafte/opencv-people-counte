"""Shared frame analysis for uploaded files and browser camera sessions."""

from math import isfinite
import os
from pathlib import Path
import shutil
import subprocess
from threading import Lock
from uuid import uuid4

from .__main__ import draw_overlay
from .detection import HOGPersonDetector
from .store import LineConfig, SessionStore
from .tracking import PeopleCounter

# Bump this when detection, counting, or rendered output changes.
ANALYSIS_VERSION = "hog-centroid-v1"


class FrameAnalyzer:
    def __init__(self, config: LineConfig) -> None:
        self.detector = HOGPersonDetector()
        self.counter = PeopleCounter(
            orientation=config.orientation,
            line_position=config.line_position,
            entry_direction=config.entry_direction,
        )
        self.frames = 0

    def process(self, frame):
        import cv2

        height, width = frame.shape[:2]
        events = self.counter.update(self.detector.detect(frame), (width, height))
        self.frames += 1
        draw_overlay(frame, self.counter, cv2, language="en")
        return frame, events


class AnalysisService:
    def __init__(self, store: SessionStore, data_dir: Path) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "sources").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "outputs").mkdir(parents=True, exist_ok=True)
        self.latest_frames: dict[str, bytes] = {}
        self.active_camera: set[str] = set()
        self.lock = Lock()
        self.video_lock = Lock()

    def output_path(self, session_id: str) -> Path:
        return self.data_dir / "outputs" / f"{session_id}.mp4"

    def source_path(self, source_sha256: str, source_suffix: str) -> Path:
        return self.data_dir / "sources" / f"{source_sha256}{source_suffix}"

    def browser_video(self, session_id: str) -> Path:
        """Make old and new OpenCV MP4 outputs playable in browsers."""
        path = self.output_path(session_id)
        with self.video_lock:
            ffprobe = shutil.which("ffprobe")
            ffmpeg = shutil.which("ffmpeg")
            if not ffprobe or not ffmpeg:
                raise RuntimeError("FFmpeg and FFprobe are required to prepare browser playback")
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True,
            )
            if probe.returncode != 0:
                raise RuntimeError("Could not inspect the annotated video")
            if probe.stdout.strip() == "h264":
                return path
            temporary = path.with_name(f"{path.stem}.{uuid4().hex}.mp4")
            try:
                result = subprocess.run(
                    [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                     "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                     "-an", str(temporary)],
                    capture_output=True, text=True,
                )
                if result.returncode != 0 or not temporary.is_file():
                    raise RuntimeError("FFmpeg could not encode the video for browser playback")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            return path

    def latest_frame(self, session_id: str) -> bytes | None:
        with self.lock:
            return self.latest_frames.get(session_id)

    def _save_preview(self, session_id: str, frame) -> bytes:
        import cv2

        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if not ok:
            raise RuntimeError("Could not encode preview frame")
        result = encoded.tobytes()
        with self.lock:
            self.latest_frames[session_id] = result
        return result

    def process_upload(self, session_id: str, source_path: Path) -> None:
        import cv2

        capture = None
        writer = None
        completed = False
        try:
            session = self.store.get(session_id)
            config = LineConfig(session["orientation"], session["line_position"], session["entry_direction"])
            analyzer = FrameAnalyzer(config)
            capture = cv2.VideoCapture(str(source_path))
            if not capture.isOpened():
                raise ValueError("The uploaded file is not a readable video")
            reported_frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            total = int(reported_frames) if isfinite(reported_frames) and reported_frames > 0 else 0
            self.store.set_total_frames(session_id, total)
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not isfinite(fps) or fps <= 0:
                fps = 30.0
            self.store.set_status(session_id, "running")
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                height, width = frame.shape[:2]
                if writer is None:
                    writer = cv2.VideoWriter(str(self.output_path(session_id)),
                                             cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                    if not writer.isOpened():
                        raise RuntimeError("Could not create annotated video")
                frame, events = analyzer.process(frame)
                writer.write(frame)
                elapsed = (analyzer.frames - 1) / fps
                self.store.record_frame(session_id, analyzer.frames, elapsed,
                                        analyzer.counter.entries, analyzer.counter.exits, events)
                self._save_preview(session_id, frame)
            if analyzer.frames == 0:
                raise ValueError("The uploaded video has no readable frames")
            writer.release()
            writer = None
            self.browser_video(session_id)
            self.store.set_status(session_id, "completed", output_available=True)
            completed = True
        except Exception as exc:
            self.store.set_status(session_id, "failed", error=str(exc)[:300])
        finally:
            if capture is not None:
                capture.release()
            if writer is not None:
                writer.release()
            if not completed:
                self.output_path(session_id).unlink(missing_ok=True)

    def start_camera(self, session_id: str) -> FrameAnalyzer:
        session = self.store.get(session_id)
        if session is None or session["source_type"] != "camera" or session["status"] != "queued":
            raise ValueError("Camera session is not available")
        with self.lock:
            if session_id in self.active_camera:
                raise ValueError("Camera session is already active")
            self.active_camera.add(session_id)
        try:
            config = LineConfig(session["orientation"], session["line_position"], session["entry_direction"])
            analyzer = FrameAnalyzer(config)
            self.store.set_status(session_id, "running")
            return analyzer
        except Exception:
            with self.lock:
                self.active_camera.discard(session_id)
            raise

    def process_camera_frame(self, session_id: str, analyzer: FrameAnalyzer, encoded: bytes,
                             elapsed_seconds: float) -> bytes:
        import cv2
        import numpy as np

        if len(encoded) > 2_000_000:
            raise ValueError("Camera frame is too large")
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode camera frame")
        height, width = frame.shape[:2]
        if width > 1280 or height > 720:
            raise ValueError("Camera frame exceeds 1280x720")
        frame, events = analyzer.process(frame)
        self.store.record_frame(session_id, analyzer.frames, elapsed_seconds,
                                analyzer.counter.entries, analyzer.counter.exits, events)
        return self._save_preview(session_id, frame)

    def stop_camera(self, session_id: str, error: str | None = None) -> None:
        with self.lock:
            self.active_camera.discard(session_id)
        self.store.set_status(session_id, "failed" if error else "completed", error=error)
