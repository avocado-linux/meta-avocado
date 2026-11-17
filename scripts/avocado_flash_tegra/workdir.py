"""Work directory, free-space check and cleanup for the flash run.

Standard library only. This module never starts a process itself; the
privileged removal goes through the runner it is handed.
"""

import datetime
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from . import FlashError

_TEGRAFLASH = "tegraflash"
# Bound at import so a test that patches os.geteuid to fake "not root" for the
# sudo path does not change who counts as the owner of a directory.
_geteuid = os.geteuid


@dataclass(frozen=True)
class Workdir:
    path: Path
    created_by_tool: bool

    @property
    def log(self) -> Path:
        return self.path / "flash.log"


def required_bytes(infos) -> int:
    """Total input size plus one tenth, rounded up."""
    total = sum(i.size for i in infos)
    return total + -(-total // 10)


def planned_workdir(explicit, machine, base=Path("/var/tmp"), now=None) -> Path:
    """The path the run will use; creates nothing."""
    # The script runs with cwd=images_dir, so a relative path would resolve
    # against the deploy directory there.
    if explicit is not None:
        return Path(os.path.abspath(explicit))
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return Path(os.path.abspath(base)) / f"avocado-flash-{machine}-{stamp}"


def require_space(path, needed, disk_usage=shutil.disk_usage) -> None:
    """Refuse when the filesystem holding ``path`` has less than ``needed`` free."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    available = disk_usage(probe).free
    if available < needed:
        raise FlashError(
            f"not enough free space for the work directory {path}: "
            f"{needed} bytes required, {available} bytes available on {probe}"
        )


def require_private_dir(path, stat_fn=os.lstat) -> None:
    """Refuse unless ``path`` is a real directory we own that only we can write.

    The helper staged inside runs as root, so a directory another user could
    pre-create or write to would let them choose what root executes.
    """
    path = Path(path)
    try:
        st = stat_fn(path)
    except OSError as exc:
        raise FlashError(f"cannot inspect {path}: {exc}") from exc
    if not stat.S_ISDIR(st.st_mode):
        raise FlashError(f"{path} is not a directory (a symlink or other file is refused)")
    if st.st_uid != _geteuid():
        raise FlashError(f"{path} is not owned by the current user")
    if st.st_mode & 0o022:
        raise FlashError(f"{path} is writable by group or others")


def require_safe_ancestors(path, stat_fn=os.lstat) -> None:
    """Refuse when a directory above ``path`` could be swapped by someone else.

    The helper under ``path`` runs as root, so whoever can write a directory
    on the way down could replace the work directory with one of their own.
    Symlinks are resolved first and the real ancestors are checked. Each must
    be owned by root or the current user and not writable by group or others,
    unless its sticky bit is set (``/tmp`` and ``/var/tmp``, where others
    cannot rename or remove what they do not own). Ancestors that do not exist
    yet are skipped; the caller checks again after creating them.
    """
    real = Path(os.path.realpath(Path(path).parent))
    for ancestor in (real, *real.parents):
        try:
            st = stat_fn(ancestor)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise FlashError(f"cannot inspect {ancestor}: {exc}") from exc
        if st.st_uid not in (0, _geteuid()):
            raise FlashError(
                f"{ancestor}, above the work directory {path}, is not owned by root or the current user"
            )
        if st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX:
            raise FlashError(
                f"{ancestor}, above the work directory {path}, is writable by group or others"
            )


def create_workdir(path, *, default=False, stat_fn=os.lstat) -> Workdir:
    """Create the work directory, or accept an existing explicit one.

    A default (tool-chosen) path is predictable, so it must not exist yet.
    """
    path = Path(path)
    require_safe_ancestors(path, stat_fn)
    if os.path.lexists(path):
        if default:
            raise FlashError(f"the work directory {path} already exists; refusing to reuse it")
        require_private_dir(path, stat_fn)
        return Workdir(path, False)
    missing = [path]
    for parent in path.parents:
        if os.path.lexists(parent):
            break
        missing.append(parent)
    created: list[Path] = []

    def undo():
        for made in reversed(created):
            try:
                os.rmdir(made)
            except OSError:
                pass  # best effort: it holds something we did not put there

    try:
        # Each missing component is made 0700 by hand: makedirs would give
        # the parents the umask's mode, and a 0775 parent is then refused by
        # the re-check below, stranding it for every retry.
        for component in reversed(missing):
            os.mkdir(component, 0o700)
            created.append(component)
            # mkdir honours the umask; each one must be 0700 whatever it is.
            os.chmod(component, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - private on purpose; 0o700 is stricter than the 0o644 the rule suggests
    except OSError as exc:
        undo()
        raise FlashError(f"cannot create the work directory {path}: {exc}") from exc
    try:
        # Ancestors that pre-existed are held to the rule; ours are 0700.
        require_safe_ancestors(path, stat_fn)
    except FlashError:
        undo()
        raise
    return Workdir(path, True)


def _warn(path, why):
    print(f"avocado-flash: warning: could not remove {path}: {why}", file=sys.stderr)


def cleanup(workdir, success, runner, is_root):
    """Remove what the run left behind after a success.

    Returns None on a clean removal, otherwise the path left on disk so the
    caller can print it. Failure or interrupt removes nothing. A directory
    the tool did not create is never deleted, only its ``tegraflash`` child.
    """
    if not success:
        return workdir.path
    tegraflash = workdir.path / _TEGRAFLASH
    left = None
    try:
        if os.path.lexists(tegraflash):
            if is_root:
                if tegraflash.is_symlink():
                    tegraflash.unlink()
                else:
                    shutil.rmtree(tegraflash)
            else:
                rc, out = runner.capture(
                    ["sudo", "rm", "-rf", "--one-file-system", "--", str(tegraflash)]
                )
                if rc != 0:
                    _warn(tegraflash, out.strip() or f"sudo rm exited {rc}")
                    return workdir.path
        if workdir.created_by_tool:
            shutil.rmtree(workdir.path)
    except (OSError, FlashError) as exc:
        _warn(workdir.path, str(exc))
        left = workdir.path
    return left
