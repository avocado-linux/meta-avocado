"""Populate the tegraflash work directory (oracle: stone-provision-tegraflash.sh)."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from . import EngineError
from .files import copy_replacing_link, join_name, merge_tree
from .manifest import REQUIRED_IMAGES, Manifest

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
    """The last TOSIMGFILENAME in the BSP's env file, double quotes removed.

    Oracle line 299 aborts when the file exists but has no such line (grep
    fails under set -e and pipefail); an empty value or an absent file falls
    back to the tegra234 name.
    """
    name = DEFAULT_TOS_NAME
    env_file = work_dir / ".env.initrd-flash"
    if env_file.is_file():
        values = [
            line.split("=", 1)[1].replace('"', "")
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("TOSIMGFILENAME=")
        ]
        if not values:
            raise EngineError(f"no TOSIMGFILENAME= line in {env_file}")
        name = values[-1] or name
        # Deviation tos-name-bare-filename: the oracle uses the value as a path.
        if "/" in name or name in (".", ".."):
            raise EngineError(
                f"TOSIMGFILENAME in {env_file} must be a bare file name, found {name!r}"
            )
    return name


def require_images(data: Path, manifest: Manifest) -> None:
    """Refuse before staging when a required image is absent, not a file or empty.

    Deviation required-image-refused: the oracle warns and carries on, so a
    flash proceeds with a missing or zero-length rootfs. dtb and bpmp_dtb stay
    optional and keep the warning in _copy_image.
    """
    problems = []
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


def copy_images(
    data_dir: str | Path, manifest: Manifest, work_dir: str | Path, log: Log = print
) -> None:
    data = Path(data_dir)
    work = Path(work_dir)
    require_images(data, manifest)

    def copy(src_name: str, dest_name: str, required: bool = False) -> None:
        _copy_image(data, src_name, dest_name, work, log, required)

    for name in (manifest.rootfs, manifest.var, manifest.initramfs):
        copy(name, os.path.basename(name), True)
    copy(manifest.tegraflash_initramfs, "initrd-flash.img", True)
    copy(manifest.tegraflash_esp, os.path.basename(manifest.tegraflash_esp), True)
    copy(manifest.tegraflash_esp, "esp.img", True)
    # Guarded: the destination lookup refuses a BSP env file without a TOS name,
    # which must not fire when the manifest names no TOS image.
    if manifest.tegraflash_tos:
        copy(manifest.tegraflash_tos, os.path.basename(manifest.tegraflash_tos), True)
        copy(manifest.tegraflash_tos, _tos_destination(work), True)
    base = os.path.basename(manifest.dtb)
    copy(manifest.dtb, base)
    copy(manifest.dtb, f"kernel_{base}")
    copy(manifest.bpmp_dtb, os.path.basename(manifest.bpmp_dtb))


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
