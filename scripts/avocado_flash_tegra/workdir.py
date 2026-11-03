"""Work directory, free-space check and cleanup for the flash run.

Standard library only. This module never starts a process itself; the
privileged removal goes through the runner it is handed.
"""

import datetime
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import FlashError

_TEGRAFLASH = "tegraflash"


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
    if explicit is not None:
        return Path(explicit)
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return Path(base) / f"avocado-flash-{machine}-{stamp}"


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


def create_workdir(path) -> Workdir:
    path = Path(path)
    if path.is_dir():
        return Workdir(path, False)
    os.makedirs(path, mode=0o700)
    # makedirs honours the umask; a leaf must be 0700 whatever it is.
    os.chmod(path, 0o700)
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
                if tegraflash != workdir.path / _TEGRAFLASH:
                    raise FlashError(f"refusing to remove {tegraflash}")
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
