"""
Pytest global configuration and fixtures for FortifiedReg Fleet.
Ensures PRODOCUX_REPO_DIR and PDX_REPO_DIR sibling repositories are in sys.path
and configured in environment for live in-process testing.
"""
import os
from pathlib import Path
import sys

PRODOCUX_DIR = Path("D:/ProDocuX/prodocux")
if PRODOCUX_DIR.exists():
    os.environ.setdefault("PRODOCUX_REPO_DIR", str(PRODOCUX_DIR))
    if str(PRODOCUX_DIR) not in sys.path:
        sys.path.insert(0, str(PRODOCUX_DIR))

PDX_DIR = Path("D:/ProDocuX/pdx-artifact-engine")
if PDX_DIR.exists():
    os.environ.setdefault("PDX_REPO_DIR", str(PDX_DIR))
    if str(PDX_DIR) not in sys.path:
        sys.path.insert(0, str(PDX_DIR))
