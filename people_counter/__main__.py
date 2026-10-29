"""Run with: python -m people_counter --source path/to/video.mp4"""

import argparse
import csv
from pathlib import Path

from .detection import HOGPersonDetector
from .tracking import PeopleCounter

ENTRY_COLOR = (70, 210, 70)
EXIT_COLOR = (60, 60, 230)
PENDING_COLOR = (255, 200, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Count people crossing a line in a video")
    parser.add_argument("--source", required=True, help="Video path or camera index (e.g. 0)")
    parser.add_argument("--output", default="outputs/annotated.mp4", help="Annotated MP4 path")
    parser.add_argument("--events", default="outputs/events.csv", help="Crossing events CSV path")
    parser.add_argument("--orientation", choices=("horizontal", "vertical"), default="horizontal")
    parser.add_argument("--line-position", type=float, default=0.5, help="Line position as fraction of frame")
    parser.add_argument("--entry-direction", choices=("forward", "reverse"), default="forward")
    parser.add_argument("--margin", type=int, default=12, help="Dead zone around the line in pixels")
    parser.add_argument("--max-distance", type=float, default=90, help="Maximum track movement in pixels")
    parser.add_argument("--max-missed", type=int, default=8, help="Frames a track can disappear")
    return parser.parse_args()


def draw_overlay(frame, counter: PeopleCounter, cv2) -> None:
    height, width = frame.shape[:2]
    location = round((height if counter.orientation == "horizontal" else width) * counter.line_position)
    start, end = ((0, location), (width, location)) if counter.orientation == "horizontal" else ((location, 0), (location, height))
    cv2.line(frame, start, end, (0, 220, 255), 2)

    def draw_side_label(label: str, center: tuple[int, int]) -> None:
        color = ENTRY_COLOR if label == "ENTRADA" else EXIT_COLOR
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size, baseline = cv2.getTextSize(label, font, 0.65, 2)
        text_width, text_height = text_size
        x = max(4, min(width - text_width - 4, center[0] - text_width // 2))
        y = max(text_height + 5, min(height - baseline - 5, center[1]))
        cv2.rectangle(frame, (x - 4, y - text_height - 4), (x + text_width + 4, y + baseline + 4), (25, 25, 25), -1)
        cv2.putText(frame, label, (x, y), font, 0.65, color, 2)

    negative_label = "SALIDA" if counter.entry_direction == "forward" else "ENTRADA"
    positive_label = "ENTRADA" if counter.entry_direction == "forward" else "SALIDA"
    if counter.orientation == "horizontal":
        draw_side_label(negative_label, (width // 2, location // 2))
        draw_side_label(positive_label, (width // 2, (location + height) // 2))
    else:
        draw_side_label(negative_label, (location // 2, height // 2))
        draw_side_label(positive_label, ((location + width) // 2, height // 2))

    for track in counter.tracks.values():
        if track.missed:
            continue
        x, y, w, h = track.box
        color = EXIT_COLOR if track.last_direction == "exit" else ENTRY_COLOR if track.last_direction == "entry" else PENDING_COLOR
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        cv2.putText(frame, f"ID {track.id}", (x, max(20, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.rectangle(frame, (0, 0), (min(width, 315), 42), (25, 25, 25), -1)
    cv2.putText(frame, f"IN {counter.entries}  OUT {counter.exits}", (10, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)


def main() -> int:
    args = parse_args()
    try:
        import cv2
        counter = PeopleCounter(args.orientation, args.line_position, args.margin, args.max_distance, args.max_missed, args.entry_direction)
        detector = HOGPersonDetector()
    except (ImportError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    source = int(args.source) if args.source.isdecimal() else args.source
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise SystemExit(f"Could not open video source: {args.source}")

    output_path, events_path = Path(args.output), Path(args.events)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    writer = None
    frames = 0
    try:
        with events_path.open("w", newline="", encoding="utf-8") as event_file:
            csv_writer = csv.writer(event_file)
            csv_writer.writerow(("time_seconds", "frame", "track_id", "direction"))
            try:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    height, width = frame.shape[:2]
                    if writer is None:
                        writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                        if not writer.isOpened():
                            raise RuntimeError(f"Could not create output video: {output_path}")
                    frames += 1
                    events = counter.update(detector.detect(frame), (width, height))
                    for event in events:
                        csv_writer.writerow((f"{(frames - 1) / fps:.3f}", frames, event.track_id, event.direction))
                    draw_overlay(frame, counter, cv2)
                    writer.write(frame)
            except KeyboardInterrupt:
                pass
    finally:
        capture.release()
        if writer is not None:
            writer.release()

    if not frames:
        raise SystemExit("The source opened, but it contained no frames")
    print(f"Frames: {frames} | Entries: {counter.entries} | Exits: {counter.exits}")
    print(f"Video: {output_path} | Events: {events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
