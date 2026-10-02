"""Streaming scan and re-verification of staged image files."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Tuple

Identity = Tuple[int, int, int, int]


class ImageChanged(Exception):
    """The staged image differs from what was scanned."""


@dataclass(frozen=True)
class ScanResult:
    size: int
    sha256: str
    all_zero: bool
    identity: Identity


def _open(path):
    return open(path, "rb", buffering=0)


def _identity(st: os.stat_result) -> Identity:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _stream(path, chunk: int) -> tuple[int, str, bool, Identity]:
    if isinstance(chunk, bool) or not isinstance(chunk, int) or chunk <= 0:
        raise ValueError(f"chunk must be a positive integer, got {chunk!r}")
    h = hashlib.sha256()
    size = 0
    all_zero = True
    buf = bytearray(chunk)
    view = memoryview(buf)
    zeros = bytes(chunk)
    with _open(path) as fh:
        st = os.fstat(fh.fileno()) if hasattr(fh, "fileno") else os.stat(path)
        while True:
            n = fh.readinto(view)
            if not n:
                break
            part = view[:n]
            h.update(part)
            size += n
            if all_zero and part != zeros[:n]:
                all_zero = False
    return size, h.hexdigest(), all_zero, _identity(st)


def scan(path, chunk: int = 1 << 20) -> ScanResult:
    """One streaming pass: sha256 and all-zero check with chunk-bounded memory."""
    size, digest, all_zero, ident = _stream(path, chunk)
    return ScanResult(size, digest, all_zero, ident)


def reverify(path, expected: ScanResult, chunk: int = 1 << 20) -> None:
    """Recheck identity and recompute the hash; raise ImageChanged on mismatch."""
    try:
        size, digest, _, ident = _stream(path, chunk)
    except OSError as exc:
        raise ImageChanged(f"{path}: cannot re-read image: {exc}") from exc
    if ident[:3] != expected.identity[:3] or size != expected.size:
        raise ImageChanged(f"{path}: file identity changed since scan")
    if digest != expected.sha256:
        raise ImageChanged(f"{path}: content hash changed since scan")
