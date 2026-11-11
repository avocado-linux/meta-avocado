"""Populate the tegraflash work directory (oracle: stone-provision-tegraflash.sh)."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from . import EngineError
from .files import copy_replacing_link, join_name, merge_tree
from .manifest import (
    REQUIRED_IMAGES,
    Manifest,
    missing_image_keys_problem,
    require_distinct_staged_names,
    staged_names,
)
from .plainenv import read_plain_env

DEFAULT_TOS_NAME = "tos-optee_t234.img"
_SDK_TOOLS = "sysroots/x86_64-avocadosdk-linux/usr/bin/tegraflash"

Log = Callable[[str], None]


def reset_work_dir(work_dir: str | Path) -> None:
    path = Path(work_dir)
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _source_dir(data_dir: str | Path, name: str, what: str) -> Path:
    src = join_name(data_dir, name)
    if not src.is_dir():
        listing = "\n".join(sorted(os.listdir(data_dir))) if Path(data_dir).is_dir() else "(absent)"
        raise EngineError(
            f"{what} directory not found: {src}\nContents of stone data directory:\n{listing}"
        )
    return src


def copy_bsp(data_dir: str | Path, bsp_name: str, work_dir: str | Path) -> None:
    if not bsp_name:
        raise EngineError("tegraflash_bsp not specified in manifest")
    merge_tree(_source_dir(data_dir, bsp_name, "BSP"), work_dir)


def copy_tools(
    data_dir: str | Path,
    tools_name: str,
    sdk_prefix: str,
    work_dir: str | Path,
    log: Log = print,
) -> None:
    if tools_name:
        merge_tree(_source_dir(data_dir, tools_name, "Tools"), work_dir)
        return
    sdk_tools = Path(sdk_prefix) / _SDK_TOOLS if sdk_prefix else None
    if sdk_tools is not None and sdk_tools.is_dir():
        log(f"Copying tegraflash tools from SDK: {sdk_tools}")
        merge_tree(sdk_tools, work_dir)
    else:
        log("WARNING: Tegraflash tools not found in manifest or SDK")
        log("Provisioning may fail without flash tools")


def _copy_image(
    data_dir: Path, src_name: str, dest_name: str, work_dir: Path, log: Log, required: bool = False
) -> None:
    if not src_name:
        return
    src = join_name(data_dir, src_name)
    if src.is_file():
        log(f"Copying {src_name} -> {dest_name}")
        copy_replacing_link(src, join_name(work_dir, dest_name))
    elif required:
        # The source was validated before staging; one that vanished since would
        # otherwise flash without it and only log a warning.
        raise EngineError(f"required image {src} disappeared before it was staged")
    else:
        log(f"WARNING: File not found: {src}")


def _tos_destination(work_dir: Path) -> str:
    """TOSIMGFILENAME as the flash sees it, read from the BSP's env files.

    Oracle line 299 aborts when the file exists but has no such line (grep
    fails under set -e and pipefail); an absent file falls back to the tegra234
    name. Deviation tos-name-bare-filename: the oracle uses the value as a path,
    so the reader refuses anything but a bare file name.
    """
    env_file = work_dir / ".env.initrd-flash"
    if not env_file.is_file():
        return DEFAULT_TOS_NAME
    name = read_plain_env(env_file).get("TOSIMGFILENAME")
    if name is None:
        raise EngineError(f"no TOSIMGFILENAME= line in {env_file}")
    return name


def require_images(data: Path, manifest: Manifest, *, require_keys: bool = False) -> None:
    """Refuse before staging when a required image is absent, not a file or empty.

    Deviation required-image-refused: the oracle warns and carries on, so a
    flash proceeds with a missing or zero-length rootfs. dtb and bpmp_dtb stay
    optional and keep the warning in _copy_image. With require_keys, a manifest
    key that names no file is listed in the same refusal as the unusable files.
    """
    problems = []
    if require_keys:
        key_problem = missing_image_keys_problem(manifest)
        if key_problem:
            problems.append(key_problem)
    for name in (getattr(manifest, key) for key in REQUIRED_IMAGES):
        if not name:
            continue
        src = join_name(data, name)
        if not src.is_file():
            problems.append(f"{src}: absent or not a regular file")
        elif src.stat().st_size == 0:
            problems.append(f"{src}: empty")
    if problems:
        raise EngineError("required image(s) unusable:\n" + "\n".join(problems))
    if require_keys:
        require_distinct_staged_names(manifest)


def copy_images(
    data_dir: str | Path, manifest: Manifest, work_dir: str | Path, log: Log = print
) -> None:
    data = Path(data_dir)
    work = Path(work_dir)
    require_images(data, manifest)
    # Before the first copy: a destination that equals another image's would
    # replace it, and the fit check would then measure the wrong file.
    tos_destination = _tos_destination(work) if manifest.tegraflash_tos else ""
    require_distinct_staged_names(manifest, tos_destination)
    for key, destinations in staged_names(manifest, tos_destination).items():
        for destination in destinations:
            _copy_image(data, getattr(manifest, key), destination, work, log, key in REQUIRED_IMAGES)


def verify_overlays(manifest: Manifest, work_dir: str | Path, log: Log = print) -> None:
    work = Path(work_dir)
    groups = (
        (manifest.overlays, "Verifying overlay DTBOs from manifest...", "Overlay DTBO"),
        (manifest.dce_overlays, "Verifying DCE overlay DTBOs from manifest...", "DCE overlay DTBO"),
    )
    for overlays, heading, label in groups:
        if not overlays:
            continue
        log(heading)
        for overlay in overlays:
            if join_name(work, overlay).is_file():
                log(f"  Found: {overlay}")
            else:
                log(f"  WARNING: {label} not found: {overlay}")
