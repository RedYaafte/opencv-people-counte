"""OpenCV's built-in pedestrian detector, with overlap suppression."""

from .tracking import Box


def _iou(a: Box, b: Box) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    return overlap / (aw * ah + bw * bh - overlap) if overlap else 0.0


def suppress_overlaps(boxes: list[Box], scores: list[float], threshold: float = 0.4) -> list[Box]:
    kept: list[Box] = []
    for i in sorted(range(len(boxes)), key=lambda n: scores[n], reverse=True):
        if all(_iou(boxes[i], prior) <= threshold for prior in kept):
            kept.append(boxes[i])
    return kept


class HOGPersonDetector:
    def __init__(self, scale: float = 1.05) -> None:
        import cv2

        self.cv2 = cv2
        self.scale = scale
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame) -> list[Box]:
        boxes, scores = self.hog.detectMultiScale(
            frame, winStride=(8, 8), padding=(8, 8), scale=self.scale
        )
        result = [tuple(map(int, box)) for box in boxes]
        return suppress_overlaps(result, [float(score) for score in scores])
