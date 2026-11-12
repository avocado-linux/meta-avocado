"""Tool lookup for the launcher (no scratch directory, no sudo, no I/O beyond stat).

    find_stone(sysroot_lookup, which, base_path=None, base_ld=None) -> (stone, env_additions)
    check_tegra_tools(which, python_version) -> None, raises LauncherError
    make_sysroot_lookup(deploy) -> sysroot_lookup

stone comes from the build's native sysroot when it has one, from PATH only
otherwise. With a sysroot, env_additions carries PATH (sysroot bin dirs first)
and LD_LIBRARY_PATH (sysroot lib dirs); with the host stone it is empty.
Every function here runs before the scratch directory exists, so a refusal
leaves nothing behind.
"""

from __future__ import annotations

import os
from pathlib import Path

from avocado_flash_launch.envmap import LauncherError

__all__ = ["find_stone", "check_tegra_tools", "make_sysroot_lookup", "TEGRA_TOOLS", "MIN_PYTHON"]

TEGRA_TOOLS = ("python3", "fdtget", "fdtput", "cpp", "lsusb")
MIN_PYTHON = (3, 10)

_BIN_DIRS = ("usr/bin", "usr/sbin", "bin", "sbin")
_LIB_DIRS = ("usr/lib", "lib")


def make_sysroot_lookup(deploy):
    """Return a lookup(tool) -> native sysroot Path | None for a deploy directory.

    Same search as avocado-flash's find_native_sysroot: a recipe sysroot is
    used rather than per-recipe component directories because only it resolves
    the shared libraries that live in sibling component trees.
    """
    top = Path(str(deploy).split("/deploy")[0])

    def lookup(tool: str):
        for sysroot in sorted(top.glob("work/*/avocado-stone/*/recipe-sysroot-native")):
            cand = sysroot / "usr/bin" / tool
            if cand.is_file() and os.access(cand, os.X_OK):
                return sysroot
        return None

    return lookup


def _prepend(dirs, existing):
    parts = [str(d) for d in dirs]
    if existing:
        parts.append(existing)
    return ":".join(parts)


def find_stone(sysroot_lookup, which, base_path=None, base_ld=None):
    sysroot = sysroot_lookup("stone")
    if sysroot is not None:
        sysroot = Path(sysroot)
        bins = [sysroot / d for d in _BIN_DIRS if (sysroot / d).is_dir()]
        libs = [sysroot / d for d in _LIB_DIRS if (sysroot / d).is_dir()]
        if base_path is None:
            base_path = os.environ.get("PATH", "")
        if base_ld is None:
            base_ld = os.environ.get("LD_LIBRARY_PATH", "")
        env = {"PATH": _prepend(bins, base_path)}
        if libs:
            env["LD_LIBRARY_PATH"] = _prepend(libs, base_ld)
        return sysroot / "usr/bin/stone", env
    host = which("stone")
    if host:
        return Path(host), {}
    raise LauncherError(
        "stone not found: not in the build's native sysroot "
        "(work/*/avocado-stone/*/recipe-sysroot-native) and not on PATH. "
        "A build that runs rm_work deletes that sysroot; keep it by adding "
        "avocado-stone to RM_WORK_EXCLUDE, or put stone on PATH."
    )


def check_tegra_tools(which, python_version):
    """Refuse before escalation when a Jetson host tool is missing or python3 is old.

    python_version is the (major, minor) of the python3 the run will use, or
    None when it could not be read. Every problem is reported in one error.
    """
    problems = [f"host tool {t} is not on PATH" for t in TEGRA_TOOLS if not which(t)]
    needed = ".".join(str(p) for p in MIN_PYTHON)
    if which("python3"):
        if python_version is None:
            problems.append(f"the python3 version could not be read; python3 {needed} or newer is needed")
        elif tuple(python_version) < MIN_PYTHON:
            found = ".".join(str(p) for p in python_version)
            problems.append(f"python3 {found} found; python3 {needed} or newer is needed")
    if problems:
        raise LauncherError("; ".join(problems))
