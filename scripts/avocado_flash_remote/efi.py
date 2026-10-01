"""EFI variable reader for efivarfs files.

efivarfs files reject seeks (``tail -c +5`` fails with "Illegal seek"), so the
file is read once, sequentially, whole. The first 4 bytes are the attributes
and the remainder is the data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

ATTR_LEN = 4


@dataclass(frozen=True)
class EfiVar:
    attributes: bytes
    data: bytes
    ok: bool
    reason: str = ""


def read_variable(path: str | os.PathLike, opener: Callable = open) -> EfiVar:
    """Read a variable with one sequential read(); never position the file."""
    try:
        with opener(path, "rb", buffering=0) as fh:
            raw = fh.read()
    except OSError as exc:
        return EfiVar(b"", b"", False, f"cannot read variable: {exc}")
    raw = raw or b""
    if len(raw) <= ATTR_LEN:
        return EfiVar(raw[:ATTR_LEN], b"", False, "variable has no data byte")
    return EfiVar(raw[:ATTR_LEN], raw[ATTR_LEN:], True)


def secure_boot_state(path: str | os.PathLike, opener: Callable = open) -> str:
    """Return 'disabled', 'enabled' or 'unreadable' from the final data byte."""
    var = read_variable(path, opener)
    if not var.ok:
        return "unreadable"
    return "disabled" if var.data[-1] == 0 else "enabled"
