
import subprocess
import imageio_ffmpeg
import argparse
import json
import logging
import os
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
    add_rim_anchors,
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
    mark_not_measurable,
)
from backend.app.shot_detection.recording_jumps import (
    jump_during_shot,
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
from backend.app.database.recordings import save_recording
from backend.app.pipeline.analyze_recording import analyze_attempts
from backend.app.pipeline.video_input import (
    WrongUploadModeError,
    prepare_video,
)
from backend.app.shot_detection.multi_shot import (
    find_shots_in_video,
)
import tempfile


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


def prepare_hoop_tracking(video_path, output_dir):
    if os.getenv("ROBOFLOW_API_KEY"):
        try:
            detect_hoop(video_path=video_path, output_dir=output_dir)
            if (output_dir / "hoop_detection.json").is_file():
                add_rim_anchors(video_path, output_dir)
        except Exception as exc:
            logging.warning("Hoop detection unavailable (%s)", type(exc).__name__)
    else:
        logging.warning("ROBOFLOW_API_KEY is not set: shot outcomes will be unknown")
    hoop_path = output_dir / "hoop_detection.json"
    if hoop_path.is_file():
        track_hoop(video_path=video_path, hoop_json_path=hoop_path, output_csv=output_dir / "hoop_track.csv")


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

def convert_feedback_videos(output_dir):
    # The analysis is usable even if browser-compatible video encoding fails.
    previews = []
    for filename in ("annotated_angles.mp4", "ball_tracking.mp4"):
        try:
            previews.append(convert_video_for_web(output_dir / filename))
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            logging.warning("Unable to convert %s: %s", filename, error)
            previews.append(None)
    return previews


def refuse_multi_shot_video(video_path):
    """
    Raise WrongUploadModeError if the video contains more than
    one shot. Uses the practice-video shot finder on a 30 fps
    copy (a few seconds for a short video). If no shot is found
    the video is still accepted: the single-shot analysis has
    its own way of finding the shot.
    """

    work_dir = Path(tempfile.mkdtemp(prefix="shotcoach_check_"))

    try:
        _, _, shots = find_shots_in_video(video_path, work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if len(shots) >= 2:
        raise WrongUploadModeError(
            f"This video contains {len(shots)} shots. Please "
            "upload it as 'Several shots (practice video)'."
        )


def process_single_shot_video(
    video_path: str,
    player_name: str,
    shooting_arm: str = "right",
    original_filename: str | None = None,
    session_id: int | None = None,
    source_sha256: str | None = None,
    *,
    session_name: str | None = None,
    ball_arrival_frame: int | None = None,
) -> dict:
    """
    Run the complete basketball video-analysis pipeline
    and store the processed shot in SQLite.

    Uses a unique video ID to prevent overwriting
    previous analysis results.

    source_sha256: for a clip cut from a multi-shot video,
    the fingerprint of the uploaded video. It is stored with
    the shot instead of the clip's own fingerprint, and the
    duplicate check is skipped (the caller already did it).

    ball_arrival_frame: for such a clip, the frame where the
    ball reaches the hoop. Used to check that the recording
    was not paused or cut during the shot.
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
    if source_sha256 is not None:
        video_sha256 = source_sha256
    else:
        video_sha256 = file_sha256(source_video)
        existing = find_duplicate(player_name, video_sha256)

        if existing is not None:
            raise DuplicateVideoError(existing)

        # A direct "One shot" upload must contain one shot.
        # (Clips cut from a practice video skip this: they were
        # already found as single shots.)
        refuse_multi_shot_video(source_video)

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

    prepare_hoop_tracking(stored_video, output_dir)

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

    # If the video jumps during the shot (recording paused and
    # resumed, a cut, a sudden zoom), part of the shot is missing
    # and its form values would be wrong: keep the shot, but
    # mark its form as not measurable.
    jump = jump_during_shot(
        stored_video,
        json.loads(events_path.read_text(encoding="utf-8")),
        ball_arrival_frame=ball_arrival_frame,
    )

    if jump is not None:
        mark_not_measurable(
            output_dir / "shot_features.csv",
            reason=(
                f"The video jumps at frame {jump}, during the shot "
                "(recording paused, cut or zoomed), so part of the "
                "shot is missing."
            ),
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

    saved_session_id = save_shot(
        video_id=video_id,
        player_name=player_name,
        session_id=session_id,
        video_sha256=video_sha256,
        original_filename=original_filename,
        session_name=session_name,
    )


    # --------------------------------------------------
    # 10. Convert visual feedback videos for browsers
    # --------------------------------------------------

    pose_web_video, ball_web_video = convert_feedback_videos(output_dir)

    print("\n=== PIPELINE COMPLETED ===")

    result = {
        "status": "success",
        "player_name": player_name,
        "video_id": video_id,
        "session_id": saved_session_id,
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



def process_uploaded_video(
    video_path: str,
    player_name: str,
    shooting_arm: str = "right",
    original_filename: str | None = None,
    session_id: int | None = None,
    session_name: str | None = None,
    *,
    progress=None,
) -> dict:
    """Analyze attempts in a continuous recording and save them in SQLite."""

    def report(stage, done=0, total=0):
        if progress is not None:
            progress(stage, done, total)

    report("Checking the recording")
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

    report("Preparing the video")
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

    report("Measuring shooting form")
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

    report("Detecting the basketball")
    print("Detecting basketballs across the recording...")
    detect_basketball(
        video_path=stored_video,
        output_dir=output_dir,
        write_video=False,
        progress=lambda done, total: report("Detecting the basketball", done, total),
    )
    require_file(output_dir / "ball_detections.csv")

    report("Tracking the rim")
    print("Finding and tracking the rim...")
    prepare_hoop_tracking(stored_video, output_dir)

    report("Measuring shooting attempts")
    print("Separating attempts and measuring each shot...")
    analyses, processing, trajectory = analyze_attempts(video_id, output_dir, shooting_arm)
    analysis = analyses[0] if analyses else {}
    analysis_path = output_dir / "shot_analysis.json"
    report("Saving the recording")
    session_id = save_recording(
        video_id, player_name, session_id, video_sha256, original_filename, analyses, processing,
        session_name=session_name,
    )
    report("Preparing video previews")
    if not trajectory.empty:
        try:
            track_ball(stored_video, output_dir / "ball_detections.csv", output_dir, trajectory=trajectory)
        except (OSError, RuntimeError) as exc:
            logging.warning("Tracking preview unavailable (%s)", type(exc).__name__)

    # --------------------------------------------------
    # 10. Convert visual feedback videos for browsers
    # --------------------------------------------------

    pose_web_video, ball_web_video = convert_feedback_videos(output_dir)

    print("\n=== PIPELINE COMPLETED ===")

    result = {
        "status": "success",
        "player_name": player_name,
        "video_id": video_id,
        "session_id": session_id,
        "attempt_count": processing["attempt_count"],
        "review_candidate_count": processing["review_candidate_count"],
        "analysis_status": analysis.get(
            "analysis_status", "unknown"
        ),
        "shot_outcome": analysis.get(
            "shot_outcome", {}
        ),
        "analysis_file": str(analysis_path) if analysis_path.is_file() else None,

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
    parser.add_argument("--full-recording", action="store_true", help="Analyze attempts in one continuous recording")

    args = parser.parse_args()

    analyze = process_uploaded_video if args.full_recording else process_single_shot_video
    result = analyze(
        video_path=args.video_path,
        player_name=args.player_name,
        shooting_arm=args.shooting_arm,
        session_id=args.session_id,
    )

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))
