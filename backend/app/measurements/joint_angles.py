
import numpy as np

POSE_FILENAME = "pose_landmarks.json"
JOINT_LANDMARKS = {
    "left": {"elbow": (11, 13, 15), "knee": (23, 25, 27), "alignment": (11, 23, 27)},
    "right": {"elbow": (12, 14, 16), "knee": (24, 26, 28), "alignment": (12, 24, 28)},
}


def calculate_angle(point_a, point_b, point_c):
    """
    Calculate the angle ABC in degrees.

    point_b is the vertex of the angle.
    Each point is a (x, y) coordinate.
    """

    a = np.array(point_a, dtype=float)
    b = np.array(point_b, dtype=float)
    c = np.array(point_c, dtype=float)

    vector_ba = a - b
    vector_bc = c - b

    length_ba = np.linalg.norm(vector_ba)
    length_bc = np.linalg.norm(vector_bc)

    if length_ba < 1e-8 or length_bc < 1e-8:
        return None

    cosine = np.dot(vector_ba, vector_bc) / (
        length_ba * length_bc
    )

    # Avoid numerical errors outside [-1, 1].
    cosine = np.clip(cosine, -1.0, 1.0)

    angle = np.degrees(np.arccos(cosine))

    return float(angle)
