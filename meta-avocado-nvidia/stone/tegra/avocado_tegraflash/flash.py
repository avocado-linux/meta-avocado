"""Erase flags and the final initrd-flash call."""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import EngineError, Media
from .runner import Runner


def erase_flags(
    media: Media, *, erase_nvme: bool, erase_emmc: bool, erase_only: bool
) -> list[str]:
    """Each flag once, alphabetical: the oracle sorts and de-duplicates the words."""
    found = set()
    if media is Media.NVME or erase_nvme:
        found.add("--erase-nvme")
    if erase_emmc:
        found.add("--erase-emmc")
    if erase_only:
        found.add("--erase-only")
    return sorted(found)


def run_flash(
    runner: Runner,
    work_dir: str | Path,
    flags: Sequence[str],
    env: Mapping[str, str] | None,
) -> int:
    """Run ./initrd-flash from the work directory and return its exit status.

    A tool killed by a signal has a negative status from Popen; the oracle's bash
    reports it as 128 plus the signal number, and sys.exit(-9) would give 247.
    """
    work = Path(work_dir)
    tool = work / "initrd-flash"
    if not (tool.is_file() and os.access(tool, os.X_OK)):
        names = sorted(p.name for p in work.iterdir()) if work.is_dir() else []
        raise EngineError(
            "initrd-flash script not found or not executable in "
            f"{work}; contents: {', '.join(names)}"
        )
    status = runner.run(["./initrd-flash", *flags], cwd=work, env=env)
    if status < 0:
        return 128 - status
    return status
