#!/usr/bin/env python3
"""Print the next versioned output directory for an EAI visualization package."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VERSION_RE = re.compile(r"^yt_video_vizualizations_v([1-9]\d*)$")
LEGACY_NAME = "yt_video_vizualizations"


def next_output_dir(project: Path) -> Path:
    versions: list[tuple[int, Path]] = []
    for child in project.iterdir():
        if not child.is_dir():
            continue
        match = VERSION_RE.fullmatch(child.name)
        if match:
            versions.append((int(match.group(1)), child))

    if versions:
        highest_version, highest_path = max(versions, key=lambda item: item[0])
        if not any(highest_path.iterdir()):
            return highest_path
        next_version = highest_version + 1
    elif (project / LEGACY_NAME).is_dir():
        next_version = 2
    else:
        next_version = 1

    return project / f"yt_video_vizualizations_v{next_version}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Project directory to inspect")
    args = parser.parse_args()
    project = args.project.resolve()

    if not project.is_dir():
        print(f"ERROR: project directory does not exist: {project}", file=sys.stderr)
        return 1

    print(next_output_dir(project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
