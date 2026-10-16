"""Host-side look inside a boot image's ramdisk, for the boot-arg guard's initramfs requirement.

A guard argument such as ``avocado.root=PARTUUID=<guid>`` is only a request to the image's init. With the other
disk visible, an image whose init predates the argument ignores it, and nothing else keeps the test boot off that
disk. The boot-arg guard reads the boot header only, so ``stage`` calls ``check_initramfs_requires`` before any
copy: it extracts the ramdisk of every guard partition's boot image and refuses unless the named file in it
carries the named text.

Host-only: not in the runner bundle, so it may shell out to ``zstd`` where ``compression.zstd`` is missing.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import re
import shutil
import stat
import subprocess
import zlib
from pathlib import Path

_ANDROID_MAGIC = b"ANDROID!"
_NEWC_MAGIC = b"070701"
_NEWC_HEADER = 110
_HEX8 = re.compile(rb"[0-9A-Fa-f]{8}")
_ZSTD_TIMEOUT = 300


class RamdiskError(Exception):
    """The ramdisk could not be read, or it does not meet the profile's requirement."""


def read_ramdisk(path) -> bytes:
    """Return the decompressed ramdisk (a cpio archive) of the Android boot image at path."""
    path = Path(path)
    try:
        with open(path, "rb") as fh:
            hdr = fh.read(64)
            if len(hdr) < 64 or hdr[:8] != _ANDROID_MAGIC:
                raise RamdiskError(f"{path.name} does not start with an Android boot image header (magic ANDROID!)")
            kernel_size = int.from_bytes(hdr[8:12], "little")
            ramdisk_size = int.from_bytes(hdr[16:20], "little")
            page_size = int.from_bytes(hdr[36:40], "little")
            if page_size not in (2048, 4096, 8192, 16384):
                raise RamdiskError(f"{path.name}: boot image page size {page_size} is not understood")
            if ramdisk_size == 0:
                raise RamdiskError(f"{path.name}: the boot image has no ramdisk")
            # Header page, then the kernel padded to whole pages, then the ramdisk.
            fh.seek(page_size + -(-kernel_size // page_size) * page_size)
            packed = fh.read(ramdisk_size)
    except OSError as exc:
        raise RamdiskError(f"cannot read {path}: {exc}") from None
    if len(packed) != ramdisk_size:
        raise RamdiskError(f"{path.name}: short ramdisk ({len(packed)} of {ramdisk_size} bytes)")
    return _decompress(packed, path.name)


def _decompress(data: bytes, where: str) -> bytes:
    try:
        if data[:6] == _NEWC_MAGIC:
            return data
        if data[:2] == b"\x1f\x8b":
            return gzip.decompress(data)
        if data[:6] == b"\xfd7zXZ\x00":
            return lzma.decompress(data)
        if data[:3] == b"BZh":
            return bz2.decompress(data)
        if data[:4] == b"\x28\xb5\x2f\xfd":
            return _unzstd(data, where)
    except (OSError, EOFError, lzma.LZMAError, ValueError, zlib.error) as exc:
        raise RamdiskError(f"{where}: the ramdisk does not decompress: {exc}") from None
    raise RamdiskError(f"{where}: the ramdisk compression is not one of raw cpio, gzip, xz, bzip2 or zstd")


def _unzstd(data: bytes, where: str) -> bytes:
    try:
        from compression import zstd  # Python 3.14 and later
    except ImportError:
        zstd = None
    if zstd is not None:
        try:
            return zstd.decompress(data)
        except zstd.ZstdError as exc:
            raise RamdiskError(f"{where}: the zstd ramdisk does not decompress: {exc}") from None
    exe = shutil.which("zstd")
    if exe is None:
        raise RamdiskError(f"{where}: the ramdisk is zstd and this host has neither compression.zstd nor zstd")
    try:
        res = subprocess.run([exe, "-d", "-c", "-q"], input=data, capture_output=True, timeout=_ZSTD_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RamdiskError(f"{where}: zstd did not finish in {_ZSTD_TIMEOUT} s") from None
    if res.returncode != 0:
        raise RamdiskError(f"{where}: zstd failed: {res.stderr.decode(errors='replace').strip()[:200]}")
    return res.stdout


def cpio_find(data: bytes, path: str) -> bytes | None:
    """Return the body of the file the kernel would leave at path, or None if no entry names it.

    The kernel unpacks an initramfs entry by entry, a later entry for a path replaces an earlier one,
    and it keeps unpacking after a trailer when another newc archive follows (layered initramfs, a
    marker file appended as a second archive). So every archive in the stream is walked and the last
    match wins. A symlink at path is refused rather than followed: the requirement names the file that
    has to carry the text. Anything that is not a well-formed newc archive, including bytes after a
    trailer that are neither zero padding nor another archive, is refused.
    """
    wanted = path.lstrip("/")
    off = 0
    last = None  # (mode, body offset, end offset) of the last entry that names path
    while True:
        if off + _NEWC_HEADER > len(data):
            raise RamdiskError(f"truncated cpio archive: no header at offset {off}")
        if data[off : off + 6] != _NEWC_MAGIC:
            raise RamdiskError(f"not a newc cpio archive: no 070701 header at offset {off}")
        raw_fields = [data[off + 6 + 8 * i : off + 14 + 8 * i] for i in range(13)]
        if not all(_HEX8.fullmatch(f) for f in raw_fields):
            raise RamdiskError(f"corrupt cpio header at offset {off}: a field is not eight hex digits")
        fields = [int(f, 16) for f in raw_fields]
        mode, filesize, namesize = fields[1], fields[6], fields[11]
        name_end = off + _NEWC_HEADER + namesize
        body = name_end + (-name_end % 4)
        end = body + filesize
        if namesize == 0 or end > len(data):
            raise RamdiskError(f"truncated cpio archive at the entry starting at offset {off}")
        name = data[off + _NEWC_HEADER : name_end - 1].decode(errors="replace")
        off = end + (-end % 4)
        if name == "TRAILER!!!":
            off = len(data) - len(data[off:].lstrip(b"\0"))
            if off >= len(data):
                break
            if data[off : off + 6] != _NEWC_MAGIC:
                raise RamdiskError(f"unparseable data after the cpio trailer at offset {off}")
            if off % 4:
                raise RamdiskError(f"broken padding after the cpio trailer: the next archive starts at offset {off}")
            continue
        if name.removeprefix("./") == wanted:
            last = (mode, body, end)
    if last is None:
        return None
    mode, body, end = last
    if stat.S_ISLNK(mode):
        target = data[body:end].decode(errors="replace")
        raise RamdiskError(f"{wanted} in the ramdisk is a symlink to {target}; name the file it points to")
    return data[body:end]


def check_initramfs_requires(profile, image_dir) -> list:
    """Refuse unless every guard partition's boot image carries the profile's initramfs requirement.

    Returns the boot image files that were checked; an empty list when the guard states no requirement.
    """
    params = profile.guard.params
    if profile.guard.strategy != "boot-arg" or "initramfs_file" not in params:
        return []
    path, text = params["initramfs_file"], params["initramfs_contains"]
    number_of = {p["name"]: p["number"] for p in profile.layout.params["table"]}
    checked = []
    for name in params["partitions"]:
        img = next((i for i in profile.images.values() if i.partition == number_of.get(name)), None)
        if img is None:
            raise RamdiskError(f"no image is mapped to guard partition {name}; fix the profile")
        if img.file in checked:
            continue
        body = cpio_find(read_ramdisk(Path(image_dir) / img.file), path)
        if body is None:
            raise RamdiskError(f"{img.file}: the ramdisk has no {path}")
        if text.encode() not in body:
            raise RamdiskError(
                f"{img.file}: {path} in the ramdisk does not contain {text!r}, so its init does not understand "
                f"the guard argument {params['argument']}; refusing to stage this image"
            )
        checked.append(img.file)
    return checked
