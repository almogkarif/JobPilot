#!/usr/bin/env python3
"""Create a small shareable JobPilot source ZIP.

Unlike Finder's "Compress", this exports only Git-tracked files plus non-ignored
new source files. Local virtualenvs, .git history, browser profiles, SQLite data,
screenshots, .env secrets and patch files are excluded by the repository's
.gitignore rules.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def export_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a lightweight JobPilot source ZIP")
    parser.add_argument("output", nargs="?", help="Destination ZIP path")
    args = parser.parse_args()

    root = repository_root()
    default_name = f"jobpilot-source-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    output = Path(args.output).expanduser().resolve() if args.output else root.parent / default_name
    files = export_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            source = root / relative
            if source.is_file():
                archive.write(source, arcname=f"jobpilot/{relative}")

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Created {output} ({size_mb:.1f} MB, {len(files)} source files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
