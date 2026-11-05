"""File operations that match the oracle's `cp -a`, `cp` and `sed -i` on links."""

import os
import shutil
from pathlib import Path

from . import EngineError


def join_name(base: str | Path, name: str) -> Path:
    """Join as the oracle's "${base}/${name}" does: an absolute name stays under base.

    pathlib's `/` drops the base for an absolute right side; this keeps it.
    A name with `..` components still leaves base: callers whose names come from
    untrusted content must refuse those themselves.
    """
    return Path(f"{base}/{name}")


def write_text_replacing_link(
    path: str | Path,
    text: str,
    *,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
) -> None:
    """Write `text` to `path`; a symlink there is replaced, not followed.

    The oracle's `sed -i` does the same, so the file a staged link pointed at
    (the image tree's own copy) is never modified.
    """
    path = Path(path)
    if path.is_symlink():
        path.unlink()
    with open(path, "w", encoding=encoding, errors=errors, newline=newline) as fh:
        fh.write(text)


def read_text_preserving(path: str | Path) -> str:
    """Read a BSP text file so that `write_text_replacing_link` can put it back unchanged.

    Bytes outside UTF-8 survive as surrogates and CRLF line ends are not
    normalised; the writers of those files pass the same codec arguments.
    """
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _refuse_directory(dst: Path) -> None:
    if dst.is_dir() and not dst.is_symlink():
        raise EngineError(f"cannot overwrite directory {dst} with a non-directory")


def _install_via_temp(dst: Path, make) -> None:
    """Build the new entry beside `dst`, then rename it over `dst`.

    Unlinking first would leave a window in which a process owned by the
    directory's owner plants a link that is then written through. The rename
    replaces a link at `dst` without following it and is atomic; the temporary
    name is removed on any failure.
    """
    tmp = dst.with_name(f".{dst.name}.{os.urandom(6).hex()}.tmp")
    try:
        make(tmp)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.lexists(tmp):
            tmp.unlink()
        raise


def _copy_file(src: Path, tmp: Path, copy_meta) -> None:
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
        shutil.copyfileobj(inp, out)
    copy_meta(src, tmp)


def merge_tree(src: str | Path, dst: str | Path) -> None:
    """`cp -a src/. dst/`: merge directories, keep links, replace what is in the way.

    A file or link replaces any non-directory at the destination (never written
    through). A directory over a non-directory, including a symlinked
    directory, is refused as cp refuses it.
    """
    src, dst = Path(src), Path(dst)
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for entry in os.scandir(src):
            source = Path(entry.path)
            target = dst / entry.name
            if entry.is_dir(follow_symlinks=False):
                if os.path.lexists(target) and (target.is_symlink() or not target.is_dir()):
                    raise EngineError(f"cannot overwrite non-directory {target} with directory {source}")
                merge_tree(source, target)
                shutil.copystat(source, target)
            elif entry.is_symlink():
                _refuse_directory(target)
                link = os.readlink(source)
                _install_via_temp(target, lambda tmp, link=link: os.symlink(link, tmp))
            else:
                _refuse_directory(target)
                _install_via_temp(target, lambda tmp, source=source: _copy_file(source, tmp, shutil.copystat))
    except OSError as exc:
        raise EngineError(f"cannot copy {src} into {dst}: {exc}") from exc


def materialize_link(path: str | Path) -> None:
    """Replace a symlink with a regular copy of its target, for a program that rewrites `path` in place."""
    path = Path(path)
    if not path.is_symlink():
        return
    try:
        data = path.read_bytes()
        path.unlink()
        path.write_bytes(data)
    except OSError as exc:
        raise EngineError(f"cannot replace link {path} with a copy of its target: {exc}") from exc


def copy_replacing_link(src: str | Path, dst: str | Path) -> None:
    """Copy a file to `dst`; a link or file already there is replaced, not written through."""
    src, dst = Path(src), Path(dst)
    try:
        if dst.is_dir() and not dst.is_symlink():
            dst = dst / src.name
        _install_via_temp(dst, lambda tmp: _copy_file(src, tmp, shutil.copymode))
    except OSError as exc:
        raise EngineError(f"cannot copy {src} to {dst}: {exc}") from exc
