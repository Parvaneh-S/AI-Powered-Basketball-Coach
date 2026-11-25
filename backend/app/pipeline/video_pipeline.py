
import subprocess
import imageio_ffmpeg
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
from backend.app.shot_detection.release import (
    refine_release,
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
from backend.app.ball_detection.hoop_tracker import (
    track_hoop,
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
from backend.app.database.duplicates import (
    DuplicateVideoError,
    file_sha256,
    find_duplicate,
)
from backend.app.database.sessions import (
    validate_session,
)
from backend.app.pipeline.video_input import (
    prepare_video,
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


def convert_video_for_web(source_path: Path) -> Path:
    """
    Convert an OpenCV-generated MP4 into a browser-compatible
    H.264 MP4 without modifying the original file.
    """
    source_path = Path(source_path)

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Video not found: {source_path}"
        )

    destination = source_path.with_name(
        f"{source_path.stem}_web.mp4"
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i", str(source_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(
            f"Converted video was not created: {destination}"
        )

    return destination

def process_uploaded_video(
    video_path: str,
    player_name: str,
    shooting_arm: str = "right",
    original_filename: str | None = None,
    session_id: int | None = None,
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

    if original_filename is None:
        original_filename = source_video.name

    # A chosen session must exist and belong to this player.
    # None starts a new session.
    validate_session(player_name, session_id)

    # Stop early if this player already has this exact video,
    # before spending minutes on the analysis.
    video_sha256 = file_sha256(source_video)
    existing = find_duplicate(player_name, video_sha256)

    if existing is not None:
        raise DuplicateVideoError(existing)

    # Create a unique identifier for this upload.
    video_id = f"shot_{uuid4().hex[:12]}"

    # Keep a processing copy in a predictable location,
    # always as an H.264 MP4 that OpenCV can read. MOV and
    # unreadable MP4 files (e.g. HEVC from iPhones) are
    # converted; readable MP4 files are copied unchanged.
    upload_dir = ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_video = upload_dir / f"{video_id}.mp4"

    converted = prepare_video(source_video, stored_video)

    if converted:
        print(f"Converted {original_filename} to H.264 MP4")

    output_dir = ROOT / "outputs" / video_id
    output_dir.mkdir(parents=True, exist_ok=False)

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
    # 4. Hoop detection (before ball tracking, which
    #    uses the hoop to correct for camera movement)
    # --------------------------------------------------

    print("\n[4/9] Detecting basketball hoop...")

    detect_hoop(
        video_path=stored_video,
        output_dir=output_dir,
    )

    require_file(
        output_dir / "hoop_detection.json"
    )

    # Follow the hoop in every frame, in case the camera
    # moves (runs locally; nothing is sent to Roboflow).
    track_hoop(
        video_path=stored_video,
        hoop_json_path=output_dir / "hoop_detection.json",
        output_csv=output_dir / "hoop_track.csv",
    )

    # --------------------------------------------------
    # 5. Ball tracking
    # --------------------------------------------------

    print("\n[5/9] Tracking basketball...")

    # Follow only this shot's ball, from the knee dip on
    # (in the hands, then in flight).
    events_path = output_dir / "predicted_shot_events.json"
    knee_min_frame = json.loads(
        events_path.read_text(encoding="utf-8")
    )["knee_min_frame"]

    track_ball(
        video_path=stored_video,
        csv_path=output_dir / "ball_detections.csv",
        output_dir=output_dir,
        start_frame=knee_min_frame,
        hoop_track_path=output_dir / "hoop_track.csv",
    )

    require_file(
        output_dir / "ball_trajectory.csv"
    )

    # Correct the release frame with the moment the ball
    # leaves the hands (the pose-only estimate can be late
    # when the shooter hops).
    refine_release(
        events_path=events_path,
        angles_csv=output_dir / "joint_angles.csv",
        trajectory_csv=output_dir / "ball_trajectory.csv",
        detections_csv=output_dir / "ball_detections.csv",
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
        session_id=session_id,
        video_sha256=video_sha256,
        original_filename=original_filename,
    )


    # --------------------------------------------------
    # 10. Convert visual feedback videos for browsers
    # --------------------------------------------------

    print("\nConverting visual feedback videos for browsers...")

    pose_web_video = output_dir / "annotated_angles_web.mp4"
    ball_web_video = output_dir / "ball_tracking_web.mp4"

    # Conversion is optional for the shot analysis.
    # If conversion fails, the analysis remains valid
    # and the shot is still saved in SQLite.
    try:
        pose_web_video = convert_video_for_web(
            output_dir / "annotated_angles.mp4"
        )
        print(f"Pose video converted: {pose_web_video}")

    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"WARNING: Pose video conversion failed: {error}")
        pose_web_video = None

    try:
        ball_web_video = convert_video_for_web(
            output_dir / "ball_tracking.mp4"
        )
        print(f"Ball tracking video converted: {ball_web_video}")

    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"WARNING: Ball tracking video conversion failed: {error}")
        ball_web_video = None

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

        # Original OpenCV videos
        "annotated_video": str(
            output_dir / "annotated_angles.mp4"
        ),
        "ball_tracking_video": str(
            output_dir / "ball_tracking.mp4"
        ),

        # Browser-compatible H.264 videos
        "annotated_video_web": (
            str(pose_web_video)
            if pose_web_video is not None
            else None
        ),
        "ball_tracking_video_web": (
            str(ball_web_video)
            if ball_web_video is not None
            else None
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

    parser.add_argument(
        "--session-id",
        type=int,
        default=None,
        help="Add the shot to this practice session "
             "(default: start a new session)",
    )

    args = parser.parse_args()

    result = process_uploaded_video(
        video_path=args.video_path,
        player_name=args.player_name,
        shooting_arm=args.shooting_arm,
        session_id=args.session_id,
    )

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))
