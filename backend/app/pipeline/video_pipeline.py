
import argparse
import json
import shutil
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

from backend.app.computer_vision.pose_estimator import (
    process_video,
)
from backend.app.shot_detection.auto_segment import (
    detect_shot_events,
)
from backend.app.ball_detection.ball_detector import (
    detect_basketball,
)
from backend.app.ball_detection.ball_tracker import (
    track_ball,
)
from backend.app.ball_detection.hoop_detector import (
    detect_hoop,
)
from backend.app.ball_detection.shot_outcome import (
    analyze_outcome,
)
from backend.app.measurements.shot_features import (
    extract_shot_features,
)
from backend.app.analysis.shot_analysis import (
    build_shot_analysis,
)
from backend.app.database.save_shot import (
    save_shot,
)


# Project root: AI-Powered-Basketball-Coach/
ROOT = Path(__file__).resolve().parents[3]

POSE_MODEL = (
    ROOT / "backend" / "models" /
    "pose_landmarker_lite.task"
)


def require_file(path: Path):
    """Make sure a processing stage created its output."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected output was not created: {path}"
        )


def process_uploaded_video(
    video_path: str,
    player_name: str,
    shooting_arm: str = "right",
) -> dict:
    """
    Run the complete basketball video-analysis pipeline
    and store the processed shot in SQLite.

    Uses a unique video ID to prevent overwriting
    previous analysis results.
    """

    source_video = Path(video_path).resolve()

    if not source_video.is_file():
        raise FileNotFoundError(
            f"Video file not found: {source_video}"
        )

    if not POSE_MODEL.is_file():
        raise FileNotFoundError(
            f"MediaPipe model not found: {POSE_MODEL}"
        )

    if not player_name.strip():
        raise ValueError("Player name cannot be empty.")

    if shooting_arm not in ("left", "right"):
        raise ValueError(
            "shooting_arm must be 'left' or 'right'."
        )

    # Create a unique identifier for this upload.
    video_id = f"shot_{uuid4().hex[:12]}"

    output_dir = ROOT / "outputs" / video_id
    output_dir.mkdir(parents=True, exist_ok=False)

    # Keep a processing copy in a predictable location.
    upload_dir = ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_video = (
        upload_dir / f"{video_id}{source_video.suffix}"
    )

    shutil.copy2(source_video, stored_video)

    print("\n=== BASKETBALL VIDEO PIPELINE ===")
    print(f"Player: {player_name}")
    print(f"Video ID: {video_id}")

    # --------------------------------------------------
    # 1. Pose estimation
    # --------------------------------------------------

    print("\n[1/9] Running pose estimation...")

    process_video(
        input_path=stored_video,
        output_path=(
            output_dir / "annotated_angles.mp4"
        ),
        model_path=POSE_MODEL,
        csv_path=output_dir / "joint_angles.csv",
    )

    require_file(output_dir / "joint_angles.csv")

    # --------------------------------------------------
    # 2. Shot segmentation
    # --------------------------------------------------

    print("\n[2/9] Detecting shot events...")

    detect_shot_events(
        csv_path=output_dir / "joint_angles.csv",
        output_path=(
            output_dir / "predicted_shot_events.json"
        ),
    )

    require_file(
        output_dir / "predicted_shot_events.json"
    )

    # --------------------------------------------------
    # 3. Ball detection
    # --------------------------------------------------

    print("\n[3/9] Detecting basketball...")

    detect_basketball(
        video_path=stored_video,
        output_dir=output_dir,
    )

    require_file(
        output_dir / "ball_detections.csv"
    )

    # --------------------------------------------------
    # 4. Ball tracking
    # --------------------------------------------------

    print("\n[4/9] Tracking basketball...")

    track_ball(
        video_path=stored_video,
        csv_path=output_dir / "ball_detections.csv",
        output_dir=output_dir,
    )

    require_file(
        output_dir / "ball_trajectory.csv"
    )

    # --------------------------------------------------
    # 5. Hoop detection
    # --------------------------------------------------

    print("\n[5/9] Detecting basketball hoop...")

    detect_hoop(
        video_path=stored_video,
        output_dir=output_dir,
    )

    require_file(
        output_dir / "hoop_detection.json"
    )

    # --------------------------------------------------
    # 6. Biomechanical measurements
    # --------------------------------------------------

    print("\n[6/9] Extracting biomechanics...")

    extract_shot_features(
        angles_path=output_dir / "joint_angles.csv",
        annotation_path=(
            output_dir / "predicted_shot_events.json"
        ),
        output_path=output_dir / "shot_features.csv",
        shooting_arm=shooting_arm,
        video_id=video_id,
    )

    require_file(
        output_dir / "shot_features.json"
    )

    # --------------------------------------------------
    # 7. Shot outcome
    # --------------------------------------------------

    print("\n[7/9] Estimating shot outcome...")

    analyze_outcome(
        video_name=video_id,
        output_dir=output_dir,
    )

    require_file(
        output_dir / "shot_outcome.json"
    )

    # --------------------------------------------------
    # 8. Combine the analysis
    # --------------------------------------------------

    print("\n[8/9] Building combined analysis...")

    build_shot_analysis(video_id)

    analysis_path = (
        output_dir / "shot_analysis.json"
    )

    require_file(analysis_path)

    analysis = json.loads(
        analysis_path.read_text(encoding="utf-8")
    )

    # --------------------------------------------------
    # 9. Save to SQLite
    # --------------------------------------------------

    print("\n[9/9] Saving shot to database...")

    save_shot(
        video_id=video_id,
        player_name=player_name,
    )

    print("\n=== PIPELINE COMPLETED ===")

    result = {
        "status": "success",
        "player_name": player_name,
        "video_id": video_id,
        "analysis_status": analysis.get(
            "analysis_status", "unknown"
        ),
        "shot_outcome": analysis.get(
            "shot_outcome", {}
        ),
        "analysis_file": str(analysis_path),
        "annotated_video": str(
            output_dir / "annotated_angles.mp4"
        ),
        "ball_tracking_video": str(
            output_dir / "ball_tracking.mp4"
        ),
    }

    return result


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Process a basketball video and save "
            "the analysis to SQLite."
        )
    )

    parser.add_argument(
        "video_path",
        help="Path to the free-throw video",
    )

    parser.add_argument(
        "player_name",
        help="Player name",
    )

    parser.add_argument(
        "--shooting-arm",
        choices=["left", "right"],
        default="right",
    )

    args = parser.parse_args()

    result = process_uploaded_video(
        video_path=args.video_path,
        player_name=args.player_name,
        shooting_arm=args.shooting_arm,
    )

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))
