"""Private scratch input directory for the launcher (standard library only).

    plan_scratch(workdir, deploy, uid, token_hex) -> Path     pure, creates nothing
    create_scratch(path, uid) -> Scratch                      0700, caller-owned, marked
    remove_scratch(scratch, sudo=None, capture=None) -> Path | None

The directory holds the stone inputs and, for a real Jetson run, is written by
root, so a path another user could swap or pre-create would let them choose what
root executes. Adapted from avocado_flash_tegra.workdir (copied, not imported:
that wrapper is deleted later).

Removal only ever deletes a directory carrying the launcher's marker with the
random token this process wrote; the --workdir directory itself is never
removed, only the scratch directory made inside it.
"""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .envmap import LauncherError

__all__ = ["MARKER", "Scratch", "plan_scratch", "create_scratch", "remove_scratch", "capture"]

MARKER = ".avocado-flash-launcher"
# Bound at import so a test that fakes the uid for the sudo path does not change
# who counts as the owner of a directory.
_geteuid = os.geteuid


@dataclass(frozen=True)
class Scratch:
    path: Path
    token: str


def capture(argv):
    """Run argv to completion; return (returncode, output). 127 when it cannot start."""
    try:
        proc = subprocess.run(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False
        )
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout


def plan_scratch(workdir, deploy, uid, token_hex=secrets.token_hex) -> Path:
    """The scratch path the run will use; creates nothing.

    Absolute, outside the deploy tree, and free of '.' and '=' in every
    component after symlinks are resolved.
    """
    if workdir is not None:
        base = Path(os.path.abspath(workdir))
    else:
        base = Path(f"/var/tmp/avocado-flash-launch-{uid}")
    # The random name is hex so it is dot-free by construction.
    path = Path(os.path.realpath(base)) / ("s" + token_hex(8))
    # devtool-debt: dot-free scratch path. Ceiling: deploy trees whose scripts predate the payload-path fix. Upgrade trigger: the oldest supported deploy tree carries the fixed derivation.
    for part in path.parts[1:]:
        if "." in part or "=" in part:
            raise LauncherError(
                f"the scratch location {path} has a component {part!r} containing '.' or '='; "
                "the provisioning scripts of older deploy trees mis-derive their payload path "
                "from it. Choose a --workdir whose path has neither"
            )
    real_deploy = Path(os.path.realpath(deploy))
    if path.is_relative_to(real_deploy):
        raise LauncherError(f"the scratch location {path} is inside the deploy tree {real_deploy}")
    return path


def _require_safe_ancestors(path, uid, stat_fn):
    """Refuse when a directory above ``path`` could be swapped by someone else.

    Symlinks are resolved first. Each existing ancestor must be owned by root or
    the caller and not writable by group or others, unless sticky.
    """
    real = Path(os.path.realpath(Path(path).parent))
    for ancestor in (real, *real.parents):
        try:
            st = stat_fn(ancestor)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LauncherError(f"cannot inspect {ancestor}: {exc}") from exc
        if st.st_uid not in (0, uid):
            raise LauncherError(
                f"{ancestor}, above the scratch directory {path}, is not owned by root or the current user"
            )
        if st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX:
            raise LauncherError(
                f"{ancestor}, above the scratch directory {path}, is writable by group or others"
            )


def create_scratch(path, uid, stat_fn=os.lstat) -> Scratch:
    """Create the 0700 scratch directory and mark it as the launcher's."""
    path = Path(path)
    _require_safe_ancestors(path, uid, stat_fn)
    if os.path.lexists(path):
        raise LauncherError(f"the scratch directory {path} already exists; refusing to reuse it")
    missing = [path]
    for parent in path.parents:
        if os.path.lexists(parent):
            break
        missing.append(parent)
    created: list[Path] = []

    def undo():
        for made in reversed(created):
            try:
                if made == path:
                    (made / MARKER).unlink(missing_ok=True)
                os.rmdir(made)
            except OSError:
                pass  # best effort: it holds something we did not put there

    token = secrets.token_hex(16)
    try:
        for component in reversed(missing):
            os.mkdir(component, 0o700)
            created.append(component)
            os.chmod(component, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - private on purpose
        fd = os.open(path / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(token + "\n")
        # Ancestors that pre-existed are held to the rule; ours are 0700.
        _require_safe_ancestors(path, uid, stat_fn)
    except OSError as exc:
        undo()
        raise LauncherError(f"cannot create the scratch directory {path}: {exc}") from exc
    except LauncherError:
        undo()
        raise
    return Scratch(path, token)


def _warn(path, why):
    print(f"avocado-flash: warning: could not remove {path}: {why}", file=sys.stderr)


def _is_ours(scratch: Scratch) -> bool:
    try:
        st = os.lstat(scratch.path)
        if not stat.S_ISDIR(st.st_mode):
            return False
        return (scratch.path / MARKER).read_text().strip() == scratch.token
    except OSError:
        return False


def remove_scratch(scratch: Scratch, sudo=None, capture_fn=capture):
    """Remove the scratch directory; return None on success, else the path left.

    ``sudo`` is the sudo executable when root wrote into the directory, so the
    removal runs with that same privilege. A directory without the launcher's
    marker and token is never touched.
    """
    if not _is_ours(scratch):
        _warn(scratch.path, "it does not carry this run's launcher marker; leaving it")
        return scratch.path
    try:
        if sudo:
            rc, out = capture_fn([sudo, "rm", "-rf", "--one-file-system", "--", str(scratch.path)])
            if rc != 0:
                _warn(scratch.path, out.strip() or f"sudo rm exited {rc}")
                return scratch.path
        else:
            shutil.rmtree(scratch.path)
    except OSError as exc:
        _warn(scratch.path, str(exc))
        return scratch.path
    return None
