"""Fixture trees for the parity harness.

build_tree stages, from a real Jetson stone manifest, the data directory the
legacy provision script reads (AVOCADO_STONE_DATA_DIR) and an empty build
directory (AVOCADO_STONE_BUILD_DIR). Every name is created verbatim through
pathlib, never a shell, so a manifest entry such as `a;touch PWNED` is just a
file name.
"""

from __future__ import annotations

import json
import shutil
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

DIR_KEYS = ("tegraflash_bsp", "tegraflash_tools", "tegraflash_carrier_bsp")
SHADOW_NAME = "shadow-link"
SENTINEL_TEXT = "sentinel: must stay as staged\n"

# The legacy script grep/sed-rewrites these, so each key must exist exactly as
# the sed expressions anchor it (`^KEY=`).
_ENV_INITRD_FLASH = (
    'BOOTDEV="nvme0n1p1"\n'
    'ROOTFS_DEVICE="nvme0n1"\n'
    "EXTERNAL_ROOTFS_DRIVE=0\n"
    'TOSIMGFILENAME="tos-optee_t234.img"\n'
)
_FLASHVARS = 'ODMDATA="0x9190000"\nOVERLAY_DTB_FILE="fixture.dtbo"\nDCE_OVERLAY=""\n'
# APPUUID_b contains APPUUID, so each placeholder sits on its own line.
APP_SIZE = 8192
ESP_SIZE = 4096
ROOTFS_IMAGE_SIZE = 4096
ESP_IMAGE_SIZE = 2048
_LAYOUT = (
    "<partition_layout>\n"
    '  <partition name="APP">\n'
    f"    <size>{APP_SIZE}</size>\n"
    "    <unique_guid>APPUUID</unique_guid>\n"
    "  </partition>\n"
    '  <partition name="APP_b">\n'
    f"    <size>{APP_SIZE}</size>\n"
    "    <unique_guid>APPUUID_b</unique_guid>\n"
    "  </partition>\n"
    '  <partition name="esp">\n'
    f"    <size>{ESP_SIZE}</size>\n"
    "  </partition>\n"
    "</partition_layout>\n"
)
_EXTERNAL_LAYOUT = _LAYOUT
# A smaller APP than the external layout, so a test can tell which of the two the
# fit check read: a rootfs between the two sizes fits one and not the other.
EMMC_APP_SIZE = 6144
_INTERNAL_EMMC_LAYOUT = _LAYOUT.replace(f"<size>{APP_SIZE}</size>", f"<size>{EMMC_APP_SIZE}</size>")
_SIZED_IMAGES = {"rootfs": ROOTFS_IMAGE_SIZE, "tegraflash_esp": ESP_IMAGE_SIZE}


def _sized_image(key: str, size: int) -> bytes:
    head = f"fixture {key}\n".encode()
    return head + b"\0" * (size - len(head))

_DTBO_BYTES = b"\xd0\x0d\xfe\xed fixture dtbo"


class Tree(NamedTuple):
    data_dir: Path
    build_dir: Path
    manifest: Path
    stub_dir: Path
    kernel_image: Path | None
    outside_dir: Path


def _touch(path: Path, content: str | bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode()
    path.write_bytes(content)


def _carrier_env(carrier: str | Mapping[str, str]) -> str:
    if isinstance(carrier, str):
        return carrier
    return "".join(f"{k}={v}\n" for k, v in carrier.items())


def _stage_bsp(
    bsp: Path, tegraflash: Mapping, stub_dir: Path, omit, used: set, tos_name: str | None, shadow_target: Path | None
) -> None:
    bsp.mkdir(parents=True, exist_ok=True)
    layout = _EXTERNAL_LAYOUT
    if "appuuid" in omit:
        layout = layout.replace("    <unique_guid>APPUUID</unique_guid>\n", "")
        used.add("appuuid")
    if "appuuid_b" in omit:
        layout = layout.replace("    <unique_guid>APPUUID_b</unique_guid>\n", "")
        used.add("appuuid_b")
    files: dict[str, str | bytes] = {
        ".env.initrd-flash": _ENV_INITRD_FLASH,
        "flashvars": _FLASHVARS,
        "external-flash.xml.in": layout,
        "internal-flash-emmc.xml": _INTERNAL_EMMC_LAYOUT,
        "L4TConfiguration.dtbo": _DTBO_BYTES,
        "mkbootimg": "#!/bin/sh\nexit 0\n",
    }
    for name in list(tegraflash.get("overlays", [])) + list(tegraflash.get("dce_overlays", [])):
        files.setdefault(name, _DTBO_BYTES)
    if tos_name is not None:
        old = 'TOSIMGFILENAME="tos-optee_t234.img"'
        assert _ENV_INITRD_FLASH.count(old) == 1
        files[".env.initrd-flash"] = _ENV_INITRD_FLASH.replace(old, f'TOSIMGFILENAME="{tos_name}"')
    for name, content in files.items():
        if name in omit:
            used.add(name)
        else:
            _touch(bsp / name, content)
    if shadow_target is not None:
        (bsp / SHADOW_NAME).symlink_to(shadow_target)
    flash_stub = stub_dir / "initrd-flash"
    if "initrd-flash" in omit:
        used.add("initrd-flash")
    elif flash_stub.is_file():
        shutil.copy2(flash_stub, bsp / "initrd-flash")
    mk = bsp / "mkbootimg"
    if mk.is_file():
        mk.chmod(mk.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_tree(
    manifest_path,
    root,
    stub_dir,
    *,
    carrier: str | Mapping[str, str] | None = None,
    kernel: bool = False,
    drop: Iterable[str] = (),
    shadow_link: bool = False,
    absolute_images: Iterable[str] = (),
    tos_name: str | None = None,
) -> Tree:
    """Stage a data dir and an empty build dir for one manifest.

    drop names what to leave out: a manifest image key (`tegraflash_bsp`), an
    image's file name, a file inside the BSP (`external-flash.xml.in`,
    `L4TConfiguration.dtbo`, `initrd-flash`, ...), or `appuuid` / `appuuid_b`
    to remove one placeholder from the external layout. A name that matched
    nothing actually skipped raises ValueError, so a typo cannot turn a failure
    case into a base case.

    outside_dir holds a sentinel file beside both trees. shadow_link makes the
    BSP carry a link named SHADOW_NAME to that sentinel and the carrier overlay
    carry a regular file of the same name (needs a carrier and a carrier image).
    absolute_images names manifest image keys whose manifest name gets a leading
    `/` (the file stays at data_dir + name). tos_name replaces the
    TOSIMGFILENAME value in the BSP's env file.
    """
    manifest_path, root, stub_dir = Path(manifest_path), Path(root), Path(stub_dir)
    omit = set(drop)
    used: set[str] = set()
    shadowed = False
    data_dir = root / "data"
    build_dir = root / "build"
    outside_dir = root / "outside"
    data_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    sentinel = outside_dir / "sentinel.txt"
    _touch(sentinel, SENTINEL_TEXT)

    manifest_copy = data_dir / "manifest.json"
    doc = json.loads(manifest_path.read_text())
    rootdisk = doc["storage_devices"]["rootdisk"]
    for key in absolute_images:
        if not isinstance(rootdisk["images"].get(key), str):
            raise ValueError(f"absolute_images names no string image: {key!r}")
        rootdisk["images"][key] = "/" + rootdisk["images"][key]
    manifest_copy.write_text(json.dumps(doc))
    tegraflash = rootdisk.get("tegraflash") or {}

    for key, name in rootdisk["images"].items():
        if not isinstance(name, str):
            continue
        if key in omit or name in omit:
            used.update({key, name} & omit)
            continue
        target = data_dir / name.lstrip("/")
        if key == "tegraflash_bsp":
            _stage_bsp(target, tegraflash, stub_dir, omit, used, tos_name, sentinel if shadow_link else None)
        elif key == "tegraflash_carrier_bsp":
            target.mkdir(parents=True, exist_ok=True)
            _touch(target / ".placeholder")
            if carrier is not None:
                _touch(target / "carrier.env", _carrier_env(carrier))
                _touch(target / "carrier-marker", "carrier overlay marker\n")
                if shadow_link:
                    _touch(target / SHADOW_NAME, "carrier overlay file\n")
                    shadowed = True
        elif key in DIR_KEYS:
            target.mkdir(parents=True, exist_ok=True)
            _touch(target / ".placeholder")
        elif key in _SIZED_IMAGES:
            _touch(target, _sized_image(key, _SIZED_IMAGES[key]))
        else:
            _touch(target, f"fixture {key}\n")

    kernel_image = None
    if kernel:
        kernel_image = root / "kernel" / "Image"
        _touch(kernel_image, "fixture kernel Image\n")

    unmatched = sorted(omit - used)
    if unmatched:
        raise ValueError(f"drop names matched nothing: {', '.join(map(repr, unmatched))}")
    if shadow_link and not shadowed:
        raise ValueError("shadow_link needs a carrier and a carrier image in the manifest")

    return Tree(data_dir, build_dir, manifest_copy, stub_dir, kernel_image, outside_dir)
