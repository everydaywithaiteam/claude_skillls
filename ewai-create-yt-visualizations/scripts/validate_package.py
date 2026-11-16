#!/usr/bin/env python3
"""Validate an Everyday With AI HTML visualization package."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


NAME_RE = re.compile(r"^(\d{2})_([a-z0-9]+(?:_[a-z0-9]+)*)\.html$")
PACKAGE_RE = re.compile(r"^yt_video_vizualizations_v([1-9]\d*)$")
REQUIRED_SNIPPETS = (
    "<!doctype html>",
    '<meta name="viewport"',
    "--ink:#20252b",
    "--paper:#f7f8fa",
    "--blue:#2868d8",
    "--teal:#138b82",
    "--orange:#d47727",
    'class="sheet"',
    'class="stage"',
    'class="takeaway"',
    'class="note"',
    'data-composition-id="main"',
    "data-no-timeline",
    'data-width="1920"',
    'data-height="1080"',
    'data-eai-background="scatter-drift"',
    'data-eai-brand="corner-logo"',
    'src="data:image/png;base64,',
    "translate(-76px,-46px)",
    "border-top:0",
    "border-radius:50%",
    "right:20px",
    "bottom:10px",
    "width:72px",
    "height:72px",
    "left:-77px",
    "top:-24px",
    "Everyday With AI",
)


def visible_word_count(html: str) -> int:
    without_code = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_code)
    return len(re.findall(r"\b[\w’'-]+\b", without_tags))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Path to yt_video_vizualizations_vN")
    args = parser.parse_args()
    package = args.package.resolve()

    errors: list[str] = []
    warnings: list[str] = []

    if not package.is_dir():
        print(f"ERROR: package directory does not exist: {package}")
        return 1
    if not PACKAGE_RE.fullmatch(package.name):
        errors.append("output directory must be named yt_video_vizualizations_vN, where N is a positive integer without leading zeros")

    files = sorted(path for path in package.iterdir() if path.is_file())
    if not files:
        errors.append("package is empty")

    non_html = [path.name for path in files if path.suffix.lower() != ".html"]
    if non_html:
        errors.append("non-HTML files present: " + ", ".join(non_html))

    html_files = [path for path in files if path.suffix.lower() == ".html"]
    indexes: list[int] = []
    for path in html_files:
        match = NAME_RE.fullmatch(path.name)
        if not match:
            errors.append(f"invalid filename: {path.name}")
            continue
        indexes.append(int(match.group(1)))

        html = path.read_text(encoding="utf-8")
        compact = re.sub(r"\s+", "", html.lower())
        for snippet in REQUIRED_SNIPPETS:
            if re.sub(r"\s+", "", snippet.lower()) not in compact:
                errors.append(f"{path.name}: missing required house-style marker {snippet!r}")

        if not re.search(r"<title>\s*[^<]+\s*</title>", html, flags=re.I):
            errors.append(f"{path.name}: missing meaningful <title>")
        if re.search(r"https?://|file://|(?:href|src)\s*=\s*[\"']//", html, flags=re.I):
            errors.append(f"{path.name}: contains an external network reference")
        if re.search(r"<(iframe|link|video|audio)\b", html, flags=re.I):
            errors.append(f"{path.name}: contains non-self-contained embedded content")
        if re.search(r"<script\b[^>]*\bsrc\s*=", html, flags=re.I):
            errors.append(f"{path.name}: contains an external script reference")
        images = re.findall(r"<img\b[^>]*>", html, flags=re.I)
        if len(images) != 1:
            errors.append(f"{path.name}: expected exactly one embedded logo image; found {len(images)}")
        elif not (
            re.search(r'class="eai-logo"', images[0], flags=re.I)
            and re.search(r'src="data:image/png;base64,', images[0], flags=re.I)
        ):
            errors.append(f"{path.name}: image must be the embedded eai-logo PNG")
        if "aspect-ratio:16/9" not in compact:
            errors.append(f"{path.name}: .sheet must retain a 16:9 aspect ratio")
        if not re.search(r'data-duration="\d+(?:\.\d+)?"', html, flags=re.I):
            errors.append(f"{path.name}: missing numeric HyperFrames data-duration")
        if "infinite" in compact:
            errors.append(f"{path.name}: contains an infinite animation; HyperFrames motion must be finite")
        if re.search(r'class="mesh-dot\s+(?:blue|teal|orange)"', html, flags=re.I):
            errors.append(f"{path.name}: Scatter Drift dots must remain neutral gray")
        if "#858f98" not in compact:
            errors.append(f"{path.name}: missing canonical Scatter Drift dot color")
        if re.search(r'mesh-line|rhombus-grid|M0\s*63L80\s*0L160\s*63L80\s*126Z', html, flags=re.I):
            errors.append(f"{path.name}: legacy mesh lines or rhombi are not allowed")
        dot_count = len(re.findall(r'<circle\s+class="mesh-dot"', html, flags=re.I))
        if dot_count != 10:
            errors.append(f"{path.name}: Scatter Drift must use the canonical 10-dot pattern; found {dot_count}")
        if re.search(
            r'footer\s*\{[^}]*border-top\s*:(?!\s*(?:0|none)\b)[^;}]+',
            html,
            flags=re.I | re.S,
        ):
            errors.append(f"{path.name}: footer must not draw a horizontal rule")

        placeholders = (
            "Visualization title",
            "One clear idea.",
            "Replace this panel",
            "State the conclusion",
            "Video N",
        )
        for placeholder in placeholders:
            if placeholder in html:
                errors.append(f"{path.name}: unresolved template placeholder {placeholder!r}")

        words = visible_word_count(html)
        if re.search(r'class="dek"', html, flags=re.I):
            warnings.append(f"{path.name}: includes header deck copy; remove unless essential")
        if words > 170:
            errors.append(f"{path.name}: {words} visible words; too dense for the house style")
        elif words > 125:
            warnings.append(f"{path.name}: {words} visible words; simplify if possible")

    expected = list(range(1, len(indexes) + 1))
    if indexes and indexes != expected:
        errors.append(f"file numbering must be consecutive from 01; found {indexes}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"PASS: {len(html_files)} HTML visualization(s), {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
