"""
Tests for preparing uploaded videos (MP4 and iPhone-style MOV).
Test videos are made from a sample video in a temporary folder.
"""

import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg
import pytest

from backend.app.pipeline.video_input import (
    UnsupportedVideoError,
    prepare_video,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_videos" / "free_throw_01.mp4"


def make_video(destination, *codec_args):
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y", "-loglevel", "error",
            "-i", str(SAMPLE),
            *codec_args,
            str(destination),
        ],
        check=True,
    )


def frame_info(path):
    capture = cv2.VideoCapture(str(path))
    info = (
        int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        round(capture.get(cv2.CAP_PROP_FPS)),
    )
    capture.release()
    return info


def test_readable_mp4_is_copied_unchanged(tmp_path):
    destination = tmp_path / "out.mp4"

    converted = prepare_video(SAMPLE, destination)

    assert converted is False
    assert destination.read_bytes() == SAMPLE.read_bytes()


@pytest.mark.parametrize(
    "name, codec_args",
    [
        ("iphone_hevc.mov", ["-c:v", "libx265", "-tag:v", "hvc1"]),
        ("h264.mov", ["-c:v", "libx264"]),
    ],
)
def test_mov_is_converted_to_readable_mp4(tmp_path, name, codec_args):
    source = tmp_path / name
    make_video(source, *codec_args)

    destination = tmp_path / "out.mp4"
    converted = prepare_video(source, destination)

    assert converted is True
    assert destination.is_file()

    # Same length and frame rate as the original recording.
    assert frame_info(destination) == frame_info(SAMPLE)


def test_unsupported_extension_is_rejected(tmp_path):
    source = tmp_path / "clip.avi"
    source.write_bytes(b"not a video")

    with pytest.raises(UnsupportedVideoError):
        prepare_video(source, tmp_path / "out.mp4")


def test_broken_mov_is_rejected(tmp_path):
    source = tmp_path / "broken.mov"
    source.write_bytes(b"this is not really a video")

    destination = tmp_path / "out.mp4"

    with pytest.raises(UnsupportedVideoError):
        prepare_video(source, destination)

    assert not destination.exists()
