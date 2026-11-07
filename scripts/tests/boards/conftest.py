"""Shared setup for the board registry tests."""

import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

