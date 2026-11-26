"""
Prepare uploaded videos for analysis.

Phones record in different formats: iPhones use MOV, often
with HEVC (H.265) compression that OpenCV cannot read on
Windows. Every upload is turned into a standard H.264 MP4
before analysis, but readable MP4 files are kept as they are.
"""

import shutil
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg


SUPPORTED_EXTENSIONS = (".mp4", ".mov")


class UnsupportedVideoError(ValueError):
    """Raised when an upload cannot be turned into a usable video."""


class WrongUploadModeError(UnsupportedVideoError):
    """
    Raised when the video does not match the chosen upload mode:
    several shots uploaded as "One shot", or a single shot
    uploaded as "Several shots".
    """


def opencv_can_read(path):
    """Return True if OpenCV can open the video and read a frame."""

    capture = cv2.VideoCapture(str(path))

    try:
        if not capture.isOpened():
            return False

        ok, frame = capture.read()

        return bool(ok) and frame is not None

    finally:
        capture.release()


def convert_to_h264_mp4(source, destination):
    """
    Re-encode any video into an H.264 MP4 at a constant frame
    rate. ffmpeg also applies phone rotation metadata, so the
    frames come out upright. Audio is not needed and is dropped.
    """

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i", str(source),
            "-map", "0:v:0",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-fps_mode", "cfr",
            "-an",
            "-movflags", "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise UnsupportedVideoError(
            "The video could not be converted. "
            "Please upload an MP4 or MOV video file."
        )


def is_hdr(source):
    """
    True if the video is HDR (iPhones record HLG HDR by
    default). HDR colours look washed out unless converted.
    """

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    # Without an output file ffmpeg only prints the stream
    # information (and exits with an error, which is expected).
    info = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(source)],
        capture_output=True,
        text=True,
        errors="replace",
    ).stderr

    return "arib-std-b67" in info or "smpte2084" in info


# Multi-shot videos are analysed at 30 frames per second and at
# most 1920 px wide/high: the ball and pose are still clear, and
# a 4K 60 fps phone video becomes about 8 times faster to analyse.
ANALYSIS_FPS = 30
ANALYSIS_MAX_SIDE = 1920


def convert_for_analysis(source, destination):
    """
    Re-encode a (long) video to an H.264 MP4 at 30 fps and at
    most 1920 px, turning HDR into normal (SDR) colours.
    """

    scale = (
        f"scale=w='min({ANALYSIS_MAX_SIDE},iw)'"
        f":h='min({ANALYSIS_MAX_SIDE},ih)'"
        ":force_original_aspect_ratio=decrease"
        ":force_divisible_by=2"
    )

    filters = f"fps={ANALYSIS_FPS},{scale}"

    if is_hdr(source):
        filters += (
            ",zscale=t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv"
        )

    filters += ",format=yuv420p"

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel", "error",
            "-i", str(source),
            "-map", "0:v:0",
            "-vf", filters,
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "veryfast",
            "-an",
            "-movflags", "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )

    if result.returncode != 0 or not opencv_can_read(destination):
        Path(destination).unlink(missing_ok=True)

        raise UnsupportedVideoError(
            "The video could not be converted. "
            "Please upload an MP4 or MOV video file."
        )


def prepare_video(source, destination):
    """
    Put an analysable H.264 MP4 at destination.

    Returns True if the video was converted, False if a
    readable MP4 was copied unchanged.
    """

    source = Path(source)
    destination = Path(destination)

    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedVideoError(
            "Only MP4 and MOV videos are supported."
        )

    if source.suffix.lower() == ".mp4" and opencv_can_read(source):
        shutil.copy2(source, destination)
        return False

    convert_to_h264_mp4(source, destination)

    if not opencv_can_read(destination):
        destination.unlink(missing_ok=True)

        raise UnsupportedVideoError(
            "The converted video could not be read."
        )

    return True
