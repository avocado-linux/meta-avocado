"""Host-side board profile resolution.

The profile is resolved once on the host: the project's board-support
extension directory first, the tool-shipped directory second. The winning
file is read exactly once as bytes; those bytes are validated, hashed and
later shipped unchanged, so host and runner always agree on the sha256.
``Resolved.recheck`` lets the host confirm, right before bundling, that the
file on disk is still the one that was planned.

An invalid profile in the extension directory is an error, never a silent
fallback to the shipped one.

Standard library only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .profile import _BOARD_RE, Profile, ProfileError, load_profile_bytes, profile_hash

SHIPPED_DIR = Path(__file__).resolve().parent / "profiles"



class InvalidBoard(ValueError):
    """The board name is not kebab-case [a-z0-9-]+ (no leading dash)."""


class UnknownBoard(LookupError):
    """No profile of that name in either directory."""

    def __init__(self, board: str, known: List[str]):
        self.board = board
        self.known = known
        listing = ", ".join(known) if known else "(none)"
        super().__init__(f"unknown board '{board}'; known boards: {listing}")


class UnsafeProfilePath(ValueError):
    """The candidate file is a dangling or escaping symlink."""


class ProfileChanged(RuntimeError):
    """The profile file changed after it was resolved."""


def _check_board(board: str) -> str:
    if not isinstance(board, str) or not _BOARD_RE.fullmatch(board):
        raise InvalidBoard(
            f"invalid board name {board!r}: must be kebab-case [a-z0-9-]+ "
            "without a leading dash"
        )
    return board


def _read(candidate: Path, directory: Path):
    """Return (real_path, data, st_dev, st_ino), reading the file once."""
    try:
        real = candidate.resolve(strict=True)
        root = directory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafeProfilePath(f"cannot resolve {candidate}: {exc}") from None
    if real.parent != root:
        raise UnsafeProfilePath(
            f"{candidate} resolves to {real}, outside {root}"
        )
    with open(real, "rb") as fh:
        st = os.fstat(fh.fileno())
        data = fh.read()
    return real, data, st.st_dev, st.st_ino


@dataclass(frozen=True)
class Resolved:
    board: str
    source: str  # 'extension' | 'shipped'
    path: Path  # the candidate path that won (may be a symlink)
    other_path: Optional[Path]  # the shadowed candidate, if it also exists
    data: bytes
    sha256: str
    profile: Profile
    real_path: Path
    st_dev: int
    st_ino: int

    def recheck(self) -> None:
        """Raise ProfileChanged if the winning file is no longer the same."""
        try:
            real, data, dev, ino = _read(self.path, self.path.parent)
        except (OSError, UnsafeProfilePath) as exc:
            raise ProfileChanged(f"{self.path} is no longer readable: {exc}") from None
        if real != self.real_path:
            raise ProfileChanged(
                f"{self.path} now resolves to {real}, was {self.real_path}"
            )
        if (dev, ino) != (self.st_dev, self.st_ino):
            raise ProfileChanged(f"{self.path} was replaced (different file)")
        if profile_hash(data) != self.sha256:
            raise ProfileChanged(f"{self.path} was modified after it was resolved")


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def resolve_profile(
    board: str,
    extension_dir: Optional[Path],
    shipped_dir: Optional[Path] = SHIPPED_DIR,
) -> Resolved:
    _check_board(board)
    name = board + ".json"
    candidates = []
    if extension_dir is not None:
        candidates.append(("extension", Path(extension_dir)))
    if shipped_dir is not None:
        candidates.append(("shipped", Path(shipped_dir)))

    found = [(src, d, d / name) for src, d in candidates if _exists(d / name)]
    if not found:
        raise UnknownBoard(board, list_known(extension_dir, shipped_dir))

    source, directory, path = found[0]
    other = found[1][2] if len(found) > 1 else None
    real, data, dev, ino = _read(path, directory)
    profile = load_profile_bytes(data)
    if profile.board != board:
        raise ProfileError(
            "board", f"'{profile.board}' does not match requested board '{board}'"
        )
    return Resolved(
        board=board,
        source=source,
        path=path,
        other_path=other,
        data=data,
        sha256=profile_hash(data),
        profile=profile,
        real_path=real,
        st_dev=dev,
        st_ino=ino,
    )


def list_known(
    extension_dir: Optional[Path],
    shipped_dir: Optional[Path] = SHIPPED_DIR,
) -> List[str]:
    names = set()
    for d in (extension_dir, shipped_dir):
        if d is None:
            continue
        try:
            entries = list(Path(d).iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix == ".json" and _BOARD_RE.fullmatch(entry.stem):
                names.add(entry.stem)
    return sorted(names)


def describe(resolved: Resolved) -> str:
    line = f"profile: {resolved.board} ({resolved.source}: {resolved.path})"
    if resolved.other_path is not None:
        line += f"; shadows shipped: {resolved.other_path}"
    return line
