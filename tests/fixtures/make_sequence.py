"""Create deterministic JPEG sequences for end-to-end tests."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


FRAME_SIZE = (320, 180)
FRAME_COUNT = 24
GROUP_SIZE = FRAME_COUNT // 2
FIRST_MTIME = 1_704_067_200
DARK_FRAME_INDEX = 5
REJECT_CANDIDATE_INDEX = 8


@dataclass(frozen=True)
class SequenceFixture:
    source_dir: Path
    frames: tuple[Path, ...]
    groups: tuple[tuple[Path, ...], tuple[Path, ...]]
    brightness: dict[str, int]
    dark_frame: Path
    reject_candidate: Path


def create_sequence(source_dir: Path) -> SequenceFixture:
    """Write 24 EXIF-free JPEGs with stable content and two capture groups."""
    source_dir = Path(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    brightness = {}
    for index in range(FRAME_COUNT):
        value = 32 + index * 8
        if index == DARK_FRAME_INDEX:
            value = 6
        frame = source_dir / f"frame_{index:03d}.jpg"
        Image.new("RGB", FRAME_SIZE, (value, value, value)).save(frame, format="JPEG", quality=95)
        timestamp = FIRST_MTIME + index if index < GROUP_SIZE else FIRST_MTIME + 600 + index
        os.utime(frame, (timestamp, timestamp))
        frames.append(frame)
        brightness[frame.name] = value

    paths = tuple(frames)
    return SequenceFixture(
        source_dir=source_dir,
        frames=paths,
        groups=(paths[:GROUP_SIZE], paths[GROUP_SIZE:]),
        brightness=brightness,
        dark_frame=paths[DARK_FRAME_INDEX],
        reject_candidate=paths[REJECT_CANDIDATE_INDEX],
    )
