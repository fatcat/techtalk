#!/usr/bin/env python3
"""Build a clean distribution package of the KB viewer UI."""

import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
UI_DIR = PROJECT_ROOT / "ui"
OUTPUT_DIR = PROJECT_ROOT / "output"
DIST_DIR = PROJECT_ROOT / "dist"

KB_INDEX_JSON = OUTPUT_DIR / "kb_index.json"

# Files to include in the distribution
DIST_FILES = [
    ("ui/index.html", "index.html"),
    ("ui/css/style.css", "css/style.css"),
    ("ui/js/app.js", "js/app.js"),
    ("ui/js/state.js", "js/state.js"),
    ("ui/js/search.js", "js/search.js"),
    ("ui/js/render.js", "js/render.js"),
    ("ui/lib/minisearch.min.js", "lib/minisearch.min.js"),
]


def build():
    # Check that kb_index.json exists
    if not KB_INDEX_JSON.exists():
        print(f"ERROR: {KB_INDEX_JSON} not found. Run the pipeline first (python cli.py curate).")
        sys.exit(1)

    # Clean dist
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    # Copy UI files
    for src_rel, dst_rel in DIST_FILES:
        src = PROJECT_ROOT / src_rel
        dst = DIST_DIR / dst_rel
        if not src.exists():
            print(f"ERROR: Missing source file: {src}")
            sys.exit(1)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Generate kb_data.js from kb_index.json
    data_dir = DIST_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    kb_data = json.loads(KB_INDEX_JSON.read_text(encoding="utf-8"))

    with open(data_dir / "kb_data.js", "w", encoding="utf-8") as f:
        f.write("window.__KB_DATA__ = ")
        json.dump(kb_data, f, ensure_ascii=False, default=str)
        f.write(";\n")

    # Also copy the raw JSON for HTTP-served usage
    shutil.copy2(KB_INDEX_JSON, data_dir / "kb_index.json")

    # Create zip in a temp location, then move to dist after cleaning
    timestamp = datetime.now().strftime("%m%d%y-%H%M")
    zip_name = f"techtalk-kb-{timestamp}.zip"
    zip_tmp = PROJECT_ROOT / zip_name
    with zipfile.ZipFile(zip_tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(DIST_DIR.rglob("*")):
            if f.is_file():
                zf.write(f, f"techtalk-kb/{f.relative_to(DIST_DIR)}")

    articles = len(kb_data.get("articles", []))

    # Clean dist and leave only the zip
    shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()
    zip_path = DIST_DIR / zip_name
    shutil.move(str(zip_tmp), str(zip_path))

    print(f"dist/{zip_name}: {zip_path.stat().st_size / 1024:.0f} KB ({articles} articles)")


if __name__ == "__main__":
    build()
