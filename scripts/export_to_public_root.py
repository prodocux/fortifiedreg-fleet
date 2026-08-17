#!/usr/bin/env python3
"""
Clean Allowlist Exporter for FortifiedReg Fleet (v0.3.0).
Exports files from an incubator/labs workspace to the public standalone repository root
according to an explicit allowlist and denylist manifest.
"""
import argparse
import fnmatch
import json
import os
from pathlib import Path
import shutil
import sys
from typing import List, Set


def is_denylisted(rel_path: str, denylist_patterns: List[str]) -> bool:
    posix_path = rel_path.replace("\\", "/")
    for pat in denylist_patterns:
        if fnmatch.fnmatch(posix_path, pat) or fnmatch.fnmatch(Path(posix_path).name, pat):
            return True
        if f"/{pat.strip('*/')}/" in f"/{posix_path}/":
            return True
    return False


def collect_export_files(source_root: Path, allowlist_roots: List[str], denylist_patterns: List[str]) -> List[Path]:
    files_to_copy: List[Path] = []
    for item_name in allowlist_roots:
        item_path = source_root / item_name
        if not item_path.exists():
            continue
        if item_path.is_file():
            rel_str = str(item_path.relative_to(source_root))
            if not is_denylisted(rel_str, denylist_patterns):
                files_to_copy.append(item_path)
        elif item_path.is_dir():
            for root, dirs, files in os.walk(item_path):
                # Filter dirs in-place to avoid descending into denylisted folders
                dirs[:] = [
                    d for d in dirs
                    if not is_denylisted(str((Path(root) / d).relative_to(source_root)), denylist_patterns)
                ]
                for file in files:
                    file_path = Path(root) / file
                    rel_str = str(file_path.relative_to(source_root))
                    if not is_denylisted(rel_str, denylist_patterns):
                        files_to_copy.append(file_path)
    return files_to_copy


def export_files(
    source_root: Path,
    target_root: Path,
    manifest_path: Path,
    dry_run: bool = False,
) -> int:
    if not manifest_path.exists():
        print(f"Error: Manifest file '{manifest_path}' not found.", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    allowlist_roots = manifest.get("allowlist_roots", [])
    denylist_patterns = manifest.get("denylist_patterns", [])

    files = collect_export_files(source_root, allowlist_roots, denylist_patterns)
    print(f"Discovered {len(files)} files to export from '{source_root}' to '{target_root}'")

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    total_bytes = 0

    for src_file in files:
        rel_path = src_file.relative_to(source_root)
        dest_file = target_root / rel_path
        size = src_file.stat().st_size
        total_bytes += size

        if dry_run:
            print(f"[DRY-RUN] {rel_path} ({size} bytes)")
        else:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)
            copied_count += 1

    action = "Previewed" if dry_run else "Successfully copied"
    print(f"{action} {len(files)} files ({total_bytes / (1024 * 1024):.2f} MB) into '{target_root}'")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Export allowlisted files to public root.")
    parser.add_argument("--source", required=True, type=Path, help="Source workspace path")
    parser.add_argument("--target", required=True, type=Path, help="Target standalone public repo path")
    parser.add_argument("--manifest", required=True, type=Path, help="Path to public export manifest JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simulate export without writing files")

    args = parser.parse_args()
    sys.exit(export_files(args.source.resolve(), args.target.resolve(), args.manifest.resolve(), args.dry_run))


if __name__ == "__main__":
    main()
