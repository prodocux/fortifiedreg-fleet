#!/usr/bin/env python3
"""
Security, Cleanliness, and Absolute Path Scanner (v0.3.0).
Performs static analysis and repository hygiene audits before and after clean export.
Verifies zero leaks of internal absolute paths, credentials, oversized binaries, or unallowlisted artifacts.
"""
import argparse
import os
from pathlib import Path
import re
import sys
from typing import List, Tuple

# File size limit (50 MB)
MAX_FILE_BYTES = 50 * 1024 * 1024

# Disallowed secret patterns
SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "Google API Key"),
    (re.compile(r"sk-[0-9a-zA-Z]{20,}"), "OpenAI/Anthropic API Key"),
    (re.compile(r"gh[pousr]_[0-9a-zA-Z]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PRIVATE )?KEY-----"), "Private Key Header"),
]

# Disallowed internal path patterns in codebase content
FORBIDDEN_PATH_PATTERNS = [
    (re.compile(r"[a-zA-Z]:\\(?:Users|Documents|Desktop)\\[a-zA-Z0-9_.\\]+", re.IGNORECASE), "Windows User Path"),
    (re.compile(r"[a-zA-Z]:/(?:Users|Documents|Desktop)/[a-zA-Z0-9_./]+", re.IGNORECASE), "Posix-style Windows User Path"),
    (re.compile(r"prodocux-labs\\incubator", re.IGNORECASE), "Internal Incubator Path Reference"),
    (re.compile(r"prodocux-labs/incubator", re.IGNORECASE), "Internal Incubator Posix Reference"),
    (re.compile(r"/home/[a-zA-Z0-9_-]+/(?![\.a-zA-Z0-9_-]+)"), "Unix Home Directory"),
]

# Disallowed file extensions and filenames
FORBIDDEN_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".sqlite", ".sqlite3", ".db", ".key", ".pem", ".log"}
FORBIDDEN_FILE_NAMES = {".env", ".env.local", ".env.production", ".env.staging", ".DS_Store", "Thumbs.db"}


def scan_target(target_root: Path) -> List[Tuple[str, Path, str]]:
    violations: List[Tuple[str, Path, str]] = []

    for root, dirs, files in os.walk(target_root):
        # Check directories
        root_path = Path(root)
        if ".git" in root_path.parts:
            continue

        for d in dirs:
            dir_path = root_path / d
            if dir_path.is_symlink():
                violations.append(("SYMLINK_OR_JUNCTION", dir_path, "Directory is a symlink or junction."))
            if d in ("__pycache__", ".pytest_cache", "runs", "htmlcov"):
                violations.append(("FORBIDDEN_DIR", dir_path, f"Forbidden directory '{d}' present in target."))

        for file in files:
            file_path = root_path / file
            rel_path = file_path.relative_to(target_root)

            # 1. Symlink check
            if file_path.is_symlink():
                violations.append(("SYMLINK", file_path, "File is a symbolic link."))

            # 2. Name and extension checks
            if file in FORBIDDEN_FILE_NAMES or file.startswith(".env"):
                violations.append(("FORBIDDEN_FILE", file_path, f"Prohibited filename '{file}'."))

            if file_path.suffix.lower() in FORBIDDEN_EXTENSIONS:
                violations.append(("FORBIDDEN_EXTENSION", file_path, f"Prohibited extension '{file_path.suffix}'."))

            # 3. Size check
            size = file_path.stat().st_size
            if size > MAX_FILE_BYTES:
                violations.append(("OVERSIZED_FILE", file_path, f"File size {size} bytes exceeds limit of {MAX_FILE_BYTES} bytes."))

            # 4. Content checks for text files
            if file_path.suffix.lower() in (".py", ".json", ".md", ".toml", ".yml", ".yaml", ".txt", ".sh", ".ps1", ".ini"):
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception as exc:
                    violations.append(("READ_ERROR", file_path, f"Could not read text file: {exc}"))
                    continue

                for pattern, desc in SECRET_PATTERNS:
                    if pattern.search(content):
                        violations.append(("SECRET_LEAK", file_path, f"Potential credential leak detected: {desc}."))

                # Ignore scanner itself for forbidden path patterns
                if file_path.name != "security_and_path_scanner.py":
                    for pattern, desc in FORBIDDEN_PATH_PATTERNS:
                        match = pattern.search(content)
                        if match:
                            violations.append(("INTERNAL_PATH_LEAK", file_path, f"Found internal path reference '{match.group(0)}' ({desc})."))

    return violations


def main():
    parser = argparse.ArgumentParser(description="Scan target directory for secrets, cleanliness, and internal path leaks.")
    parser.add_argument("--target", required=True, type=Path, help="Directory to scan")
    parser.add_argument("--strict", action="store_true", help="Fail with non-zero exit code if violations found")

    args = parser.parse_args()
    target = args.target.resolve()

    if not target.exists():
        print(f"Error: Target path '{target}' does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning target: {target}")
    violations = scan_target(target)

    if not violations:
        print("[PASS] Security and cleanliness scan completed: 0 violations found.")
        sys.exit(0)
    else:
        print(f"[FAIL] Found {len(violations)} security / hygiene violations:")
        for category, path, message in violations:
            print(f"  - [{category}] {path}: {message}")
        if args.strict:
            sys.exit(1)
        sys.exit(0)


if __name__ == "__main__":
    main()
