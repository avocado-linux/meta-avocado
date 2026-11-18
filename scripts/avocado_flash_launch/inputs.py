"""Launcher input assembly and checks (no hidden state; every path is a parameter).

Deploy-tree and machine resolution stay in avocado-flash (resolve_deploy_dir,
resolve_machine, find_native_sysroot); the caller passes their results in.

    check_profile(manifest, machine, profile, dry_run)   call BEFORE creating any scratch dir
    stone_dir_for(deploy, machine) -> Path | None
    assemble_inputs(machine, stone_dir, images_dir, scratch) -> names linked
    var_size_bytes(manifest, images_dir) -> int
    jetson_kernel_image(images_dir) -> absolute path string
    stale_check(stone_dir, images_dir, stale_ok)

The deploy tree is only read; the scratch directory is the only thing written.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .envmap import LauncherError

__all__ = [
    "check_profile",
    "stone_dir_for",
    "assemble_inputs",
    "var_size_bytes",
    "jetson_kernel_image",
    "stale_check",
]

REFRESH_STEP = "bitbake avocado-stone -c stone_provision"


def _short(machine: str) -> str:
    # Same derivation as the Jetson template name: stone-<machine without avocado->.json
    return machine.removeprefix("avocado-")


def _template_name(machine: str) -> str:
    return f"stone-{_short(machine)}.json"


def check_profile(manifest: dict, machine: str, profile: str, dry_run: bool) -> None:
    profiles = manifest.get("provision", {}).get("profiles", {})
    if not isinstance(profiles, dict) or profile not in profiles:
        raise LauncherError(
            f"the manifest for {machine} defines no {profile} profile; "
            f"this machine cannot be provisioned with it"
        )
    if dry_run:
        entry = profiles[profile]
        config = entry.get("config") if isinstance(entry, dict) else None
        if not (isinstance(config, dict) and config.get("dry_run") is True):
            raise LauncherError(
                f"--dry-run refused: the {profile} profile of {machine} does not declare "
                "dry_run: true in its config"
            )


def stone_dir_for(deploy: Path, machine: str) -> Path | None:
    """The deploy tree's stone directory, when its manifest names this machine."""
    stone = Path(deploy) / "stone"
    if stone.is_dir() and (
        (stone / _template_name(machine)).is_file() or (stone / f"stone-{machine}.json").is_file()
    ):
        return stone
    return None


def assemble_inputs(
    machine: str, stone_dir: Path | None, images_dir: Path, scratch_dir: Path
) -> list[str]:
    """Symlink the inputs into scratch_dir. _build is never linked."""
    source = Path(stone_dir) if stone_dir else Path(images_dir)
    made: list[str] = []
    for entry in sorted(source.iterdir()):
        if entry.name == "_build":
            continue
        (Path(scratch_dir) / entry.name).symlink_to(entry.resolve())
        made.append(entry.name)
    if "manifest.json" not in made:
        candidates = [source / _template_name(machine), source / f"stone-{machine}.json"]
        template = next((c for c in candidates if c.is_file()), None)
        if template is None:
            raise LauncherError(
                f"no manifest for {machine}: {candidates[0]} not found; "
                "build the avocado-stone target to deploy it"
            )
        (Path(scratch_dir) / "manifest.json").symlink_to(template.resolve())
        made.append("manifest.json")
    return made


def var_size_bytes(manifest: dict, images_dir: Path) -> int:
    node = manifest
    for key in ("storage_devices", "rootdisk", "images", "var"):
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, str):
        raise LauncherError("the manifest names no var image in storage_devices.rootdisk.images")
    path = Path(images_dir) / node
    if not path.is_file():
        raise LauncherError(f"the var image {path} is missing")
    return path.stat().st_size


def jetson_kernel_image(images_dir: Path) -> str:
    kernel = Path(images_dir) / "Image"
    if not kernel.is_file() or kernel.stat().st_size == 0:
        raise LauncherError(f"the kernel image {kernel} is missing or empty")
    return str(Path(images_dir).resolve() / "Image")


def _mtime(path: Path) -> float | None:
    try:
        return path.resolve().stat().st_mtime
    except OSError:
        return None


def stale_check(stone_dir: Path | None, images_dir: Path, stale_ok: bool) -> None:
    """Refuse when a file under images_dir is newer than the stone input.

    The stone input's age is its newest file outside _build. Symlinks are followed
    on both sides because a link's own mtime never changes when its target does.
    Inputs taken from the images directory itself have nothing to compare to.
    """
    if stale_ok or stone_dir is None:
        return
    stone = Path(stone_dir)
    since = 0.0
    for root, dirs, files in os.walk(stone, followlinks=True):
        dirs[:] = [d for d in dirs if d != "_build"]
        for name in files:
            m = _mtime(Path(root) / name)
            if m is not None and m > since:
                since = m
    newer: list[tuple[float, Path]] = []
    for root, _dirs, files in os.walk(images_dir, followlinks=True):
        for name in files:
            f = Path(root) / name
            m = _mtime(f)
            if m is not None and m > since:
                newer.append((m, f))
    if not newer:
        return
    newest_mtime, newest = max(newer)

    def stamp(t: float) -> str:
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")

    raise LauncherError(
        "the stone input is older than the build output it should carry\n"
        f"  stone input: {stone} ({stamp(since)})\n"
        f"  newest:      {newest} ({stamp(newest_mtime)})\n"
        f"  {len(newer)} file(s) under {images_dir} are newer.\n"
        f"  Refresh it with: {REFRESH_STEP}\n"
        "  To use it anyway, pass --stale-ok."
    )
