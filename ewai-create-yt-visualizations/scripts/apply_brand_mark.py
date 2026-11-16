#!/usr/bin/env python3
"""Embed the approved Everyday With AI corner logo in each package HTML file."""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path


CSS_START = "/* EAI_BRAND_START */"
CSS_END = "/* EAI_BRAND_END */"
BRAND_CSS = f"""{CSS_START}
.sheet{{position:relative}}
.eai-brand{{position:absolute;right:20px;bottom:10px;width:72px;height:72px;border-radius:50%;overflow:hidden;pointer-events:none;z-index:10;opacity:.96;background:#fff;border:1px solid rgba(32,37,43,.12);box-shadow:0 5px 16px rgba(32,37,43,.10)}}
.eai-brand .eai-logo{{position:absolute;width:240px;max-width:none;height:auto;left:-77px;top:-24px;mix-blend-mode:multiply;display:block}}
footer{{padding-right:92px;border-top:0}}
@media(max-width:900px){{.eai-brand{{display:none}}footer{{padding-right:0}}}}
{CSS_END}"""


def brand_markup(data: str) -> str:
    return (
        '<div class="eai-brand" data-layout-allow-overflow data-eai-brand="corner-logo" '
        'aria-label="Everyday with AI">'
        f'<img class="eai-logo" data-layout-allow-overflow src="data:image/png;base64,{data}" alt="">'
        "</div>"
    )


def apply_brand(html: str, data: str) -> str:
    markup = brand_markup(data)

    css_pattern = re.compile(
        re.escape(CSS_START) + r".*?" + re.escape(CSS_END), flags=re.S
    )
    if css_pattern.search(html):
        html = css_pattern.sub(BRAND_CSS, html)
    elif "</style>" in html:
        html = html.replace("</style>", BRAND_CSS + "\n</style>", 1)
    else:
        raise ValueError("missing </style>")

    markup_pattern = re.compile(
        r'<div\s+class="eai-brand"(?:\s+data-layout-allow-overflow)?\s+data-eai-brand="corner-logo".*?</div>',
        flags=re.I | re.S,
    )
    if markup_pattern.search(html):
        html = markup_pattern.sub(markup, html, count=1)
    else:
        main_pattern = re.compile(r'(<main\b[^>]*\bclass="[^"]*\bsheet\b[^"]*"[^>]*>)', re.I)
        if not main_pattern.search(html):
            raise ValueError('missing <main class="sheet">')
        html = main_pattern.sub(r"\1\n" + markup, html, count=1)

    # The logo replaces a footer used only as a written channel wordmark.
    html = re.sub(
        r'<p\s+class="takeaway"[^>]*>\s*Everyday\s+with\s+AI\s*</p>',
        '<p class="takeaway" aria-hidden="true"></p>',
        html,
        count=1,
        flags=re.I,
    )
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Path to yt_video_vizualizations_vN")
    parser.add_argument(
        "--logo",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "everyday-with-ai-logo.png",
        help="Approved logo PNG; defaults to the skill asset",
    )
    args = parser.parse_args()

    package = args.package.resolve()
    logo = args.logo.resolve()
    if not package.is_dir():
        print(f"ERROR: package directory does not exist: {package}")
        return 1
    if not logo.is_file():
        print(f"ERROR: logo does not exist: {logo}")
        return 1

    encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
    files = sorted(package.glob("*.html"))
    if not files:
        print(f"ERROR: no HTML files found in {package}")
        return 1

    failures = 0
    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
            updated = apply_brand(original, encoded)
            path.write_text(updated, encoding="utf-8")
            print(f"BRANDED: {path.name}")
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"ERROR: {path.name}: {exc}")

    if failures:
        print(f"FAIL: {failures} file(s) could not be branded")
        return 1
    print(f"PASS: embedded the approved logo in {len(files)} HTML file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
