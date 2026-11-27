"""Draw focused, camera-plane annotations using saved measurements and landmarks."""

import math
from typing import Literal

import cv2

from backend.app.measurements.joint_angles import JOINT_LANDMARKS, calculate_angle

Focus = Literal["", "elbow", "knee", "alignment"]
HIGHLIGHT = (255, 231, 110)
MOVEMENT = (110, 214, 255)
OUTLINE = (25, 25, 25)


def measured_angle(row, side, focus):
    try:
        angle = float(row.get(f"{side}_{focus}_angle", ""))
    except (ValueError, TypeError):
        return None
    return angle if 0 <= angle <= 180 else None


def position(landmarks, index, width, height):
    point = landmarks.get(str(index))
    if (not isinstance(point, list) or len(point) != 2
            or not all(type(value) in (float, int) and 0 <= value < 1 for value in point)):
        return None
    return point[0] * width, point[1] * height


def pixel(point):
    return tuple(map(round, point))


def joint_arc(image, points, angle, focus):
    a, vertex, c = points
    start = math.degrees(math.atan2(a[1] - vertex[1], a[0] - vertex[0]))
    end = math.degrees(math.atan2(c[1] - vertex[1], c[0] - vertex[0]))
    sweep = (end - start + 180) % 360 - 180
    radius = max(8, min(28, round(min(math.dist(a, vertex), math.dist(c, vertex)) * 0.4)))
    cv2.ellipse(image, pixel(vertex), (radius, radius), start, min(0, sweep), max(0, sweep),
                HIGHLIGHT, 2, cv2.LINE_AA)
    height, width = image.shape[:2]
    label = f"{focus.capitalize()} {angle:g} deg"
    size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
    x = max(2, min(round(vertex[0]) + radius + 5, width - size[0] - 3))
    y = max(size[1] + 4, min(round(vertex[1]) - 6, height - 4))
    cv2.putText(image, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, OUTLINE, 4, cv2.LINE_AA)
    cv2.putText(image, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, HIGHLIGHT, 1, cv2.LINE_AA)


def annotate(image, landmarks, annotation, previous):
    """Record the marks and measurement that are actually shown."""
    side, focus = annotation["side"], annotation["focus"]
    indices = JOINT_LANDMARKS.get(side, {}).get(focus)
    if not indices:
        return
    height, width = image.shape[:2]
    points = [position(landmarks, index, width, height) for index in indices]
    marks = annotation["marks"]
    for a, b in zip(points, points[1:]):
        if a is not None and b is not None:
            cv2.line(image, pixel(a), pixel(b), OUTLINE, 5, cv2.LINE_AA)
            cv2.line(image, pixel(a), pixel(b), HIGHLIGHT, 2, cv2.LINE_AA)
            if "alignment_lines" not in marks:
                marks.append("alignment_lines")
    for point in points:
        if point is not None:
            cv2.circle(image, pixel(point), 6, OUTLINE, -1, cv2.LINE_AA)
            cv2.circle(image, pixel(point), 4, HIGHLIGHT, -1, cv2.LINE_AA)
    if any(point is not None for point in points):
        marks.append("joint_markers")
    if focus != "alignment" and all(point is not None for point in points):
        geometry = calculate_angle(*points)
        if geometry is not None:
            angle = annotation["angle_deg"]
            if angle is None or abs(geometry - angle) > 1:
                # A replay of a legacy pose pass can yield slightly different geometry.
                # In that case measure the landmarks actually drawn and identify the source.
                angle = round(geometry, 1)
                annotation.update(angle_deg=angle, angle_source="saved_landmarks")
            joint_arc(image, points, angle, focus)
            marks.append("angle_arc")
    if previous and focus != "alignment" and points[1] is not None:
        origin = position(previous, indices[1], width, height)
        if origin is not None and math.dist(origin, points[1]) >= max(10, 0.02 * max(width, height)):
            cv2.arrowedLine(image, pixel(origin), pixel(points[1]), OUTLINE, 5, cv2.LINE_AA, tipLength=0.28)
            cv2.arrowedLine(image, pixel(origin), pixel(points[1]), MOVEMENT, 2, cv2.LINE_AA, tipLength=0.28)
            marks.append("image_plane_displacement")
