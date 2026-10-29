"""Small, dependency-free centroid tracker and line-crossing counter."""

from dataclasses import dataclass
from math import hypot

Box = tuple[int, int, int, int]  # x, y, width, height


@dataclass
class Track:
    id: int
    box: Box
    center: tuple[float, float]
    missed: int = 0
    stable_side: int = 0
    last_direction: str | None = None


@dataclass(frozen=True)
class Crossing:
    track_id: int
    direction: str


class PeopleCounter:
    """Count a track once whenever it crosses a horizontal or vertical line.

    Forward means top-to-bottom for a horizontal line and left-to-right for a
    vertical line. A dead zone around the line suppresses jitter.
    """

    def __init__(
        self,
        orientation: str = "horizontal",
        line_position: float = 0.5,
        margin: int = 12,
        max_distance: float = 90,
        max_missed: int = 8,
        entry_direction: str = "forward",
    ) -> None:
        if orientation not in ("horizontal", "vertical"):
            raise ValueError("orientation must be horizontal or vertical")
        if not 0 < line_position < 1:
            raise ValueError("line_position must be between 0 and 1")
        if margin < 0 or max_distance <= 0 or max_missed < 0:
            raise ValueError("margin/max_missed must be nonnegative; max_distance positive")
        if entry_direction not in ("forward", "reverse"):
            raise ValueError("entry_direction must be forward or reverse")
        self.orientation = orientation
        self.line_position = line_position
        self.margin = margin
        self.max_distance = max_distance
        self.max_missed = max_missed
        self.entry_direction = entry_direction
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.entries = 0
        self.exits = 0

    def _side(self, center: tuple[float, float], frame_size: tuple[int, int]) -> int:
        width, height = frame_size
        coordinate = center[1] if self.orientation == "horizontal" else center[0]
        extent = height if self.orientation == "horizontal" else width
        offset = coordinate - extent * self.line_position
        return 1 if offset > self.margin else -1 if offset < -self.margin else 0

    def update(self, boxes: list[Box], frame_size: tuple[int, int]) -> list[Crossing]:
        """Associate detections and return crossings in this frame."""
        if frame_size[0] <= 0 or frame_size[1] <= 0:
            raise ValueError("frame_size must contain positive dimensions")
        centers = [(x + w / 2, y + h / 2) for x, y, w, h in boxes]
        candidates = sorted(
            (hypot(track.center[0] - center[0], track.center[1] - center[1]), tid, i)
            for tid, track in self.tracks.items()
            for i, center in enumerate(centers)
        )
        matched_tracks: set[int] = set()
        matched_boxes: set[int] = set()
        events: list[Crossing] = []

        for distance, tid, i in candidates:
            if distance > self.max_distance:
                break
            if tid in matched_tracks or i in matched_boxes:
                continue
            matched_tracks.add(tid)
            matched_boxes.add(i)
            track = self.tracks[tid]
            track.box = boxes[i]
            track.center = centers[i]
            track.missed = 0
            side = self._side(track.center, frame_size)
            if side:
                if track.stable_side and side != track.stable_side:
                    movement = "forward" if side == 1 else "reverse"
                    direction = "entry" if movement == self.entry_direction else "exit"
                    if direction == "entry":
                        self.entries += 1
                    else:
                        self.exits += 1
                    track.last_direction = direction
                    events.append(Crossing(tid, direction))
                track.stable_side = side

        for tid in list(self.tracks):
            if tid not in matched_tracks:
                self.tracks[tid].missed += 1
                if self.tracks[tid].missed > self.max_missed:
                    del self.tracks[tid]

        for i, box in enumerate(boxes):
            if i not in matched_boxes:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = Track(tid, box, centers[i], stable_side=self._side(centers[i], frame_size))
        return events
