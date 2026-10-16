"""Host-side look inside a boot image's ramdisk: the guard's initramfs requirement.

The boot images here are built in the test: an Android v0 header, a kernel blob and a ramdisk that is a newc cpio
archive, raw or compressed, so every byte the reader sees has a known origin.
"""

import gzip
import lzma
import shutil
import subprocess
from types import SimpleNamespace as NS

import pytest

from avocado_flash_remote import ramdisk
from avocado_flash_remote.ramdisk import RamdiskError

PAGE = 4096
INIT = "usr/sbin/avocado-tegra-init"
MARKER = "resolve_pinned_root"


def _newc(entries):
    """entries: [(name, mode, body)] -> newc cpio bytes, with the trailer."""
    out = bytearray()
    for ino, (name, mode, body) in enumerate([*entries, ("TRAILER!!!", 0, b"")], start=1):
        raw = name.encode() + b"\0"
        fields = [ino, mode, 0, 0, 1, 0, len(body), 0, 0, 0, 0, len(raw), 0]
        out += b"070701" + b"".join(b"%08X" % f for f in fields) + raw
        out += b"\0" * (-len(out) % 4)
        out += body
        out += b"\0" * (-len(out) % 4)
    return bytes(out)


def _boot_img(ramdisk_bytes, kernel=b"K" * 5000, page=PAGE, magic=b"ANDROID!", ramdisk_size=None):
    hdr = bytearray(page)
    hdr[0:8] = magic
    hdr[8:12] = len(kernel).to_bytes(4, "little")
    size = len(ramdisk_bytes) if ramdisk_size is None else ramdisk_size
    hdr[16:20] = size.to_bytes(4, "little")
    hdr[36:40] = page.to_bytes(4, "little")
    hdr[40:44] = (0).to_bytes(4, "little")
    body = kernel + b"\0" * (-len(kernel) % page)
    return bytes(hdr) + body + ramdisk_bytes


FILE = 0o100755
LINK = 0o120777
GOOD_CPIO = _newc([("usr", 0o40755, b""), ("usr/sbin", 0o40755, b""), (INIT, FILE, b"#!/bin/sh\n" + MARKER.encode() + b"() {\n")])


def _write(tmp_path, data, name="boot.img"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _zstd(data):
    try:
        from compression import zstd  # Python 3.14

        return zstd.compress(data)
    except ImportError:
        exe = shutil.which("zstd")
        if exe is None:
            pytest.skip("no zstd: neither compression.zstd nor the zstd command")
        return subprocess.run([exe, "-c", "-q"], input=data, capture_output=True, check=True).stdout


@pytest.mark.parametrize(
    "compress",
    [lambda b: b, gzip.compress, lzma.compress, _zstd],
    ids=["raw", "gzip", "xz", "zstd"],
)
def test_the_ramdisk_is_read_back_whatever_its_compression(tmp_path, compress):
    p = _write(tmp_path, _boot_img(compress(GOOD_CPIO)))
    assert ramdisk.read_ramdisk(p) == GOOD_CPIO


def test_a_file_is_found_by_its_path_in_the_archive():
    assert MARKER.encode() in ramdisk.cpio_find(GOOD_CPIO, INIT)


def test_a_leading_dot_slash_in_the_archive_name_still_matches():
    data = _newc([("./" + INIT, FILE, b"body")])
    assert ramdisk.cpio_find(data, INIT) == b"body"


def test_a_missing_file_is_none_and_the_trailer_ends_the_search():
    after_trailer = _newc([("other", FILE, b"x")]) + _newc([(INIT, FILE, b"late")])
    assert ramdisk.cpio_find(after_trailer, INIT) is None


def test_a_symlink_is_refused_naming_its_target():
    data = _newc([(INIT, LINK, b"../../bin/busybox")])
    with pytest.raises(RamdiskError, match="symlink.*busybox"):
        ramdisk.cpio_find(data, INIT)


def test_a_truncated_archive_is_refused():
    with pytest.raises(RamdiskError, match="cpio"):
        ramdisk.cpio_find(GOOD_CPIO[:200], "nothing/here")


def test_garbage_where_a_header_should_be_is_refused():
    with pytest.raises(RamdiskError, match="cpio"):
        ramdisk.cpio_find(b"X" * 300, INIT)


def test_a_file_that_is_not_a_boot_image_is_refused(tmp_path):
    p = _write(tmp_path, _boot_img(GOOD_CPIO, magic=b"NOTABOOT"))
    with pytest.raises(RamdiskError, match="ANDROID!"):
        ramdisk.read_ramdisk(p)


def test_a_ramdisk_shorter_than_its_header_says_is_refused(tmp_path):
    p = _write(tmp_path, _boot_img(GOOD_CPIO, ramdisk_size=len(GOOD_CPIO) + 10))
    with pytest.raises(RamdiskError, match="short"):
        ramdisk.read_ramdisk(p)


def test_an_unknown_compression_is_refused(tmp_path):
    p = _write(tmp_path, _boot_img(b"\x02\x21\x4c\x18" + b"lz4 frame"))
    with pytest.raises(RamdiskError, match="compression"):
        ramdisk.read_ramdisk(p)


# ---- the profile's requirement -------------------------------------------------------------------------------


def _profile(requirement=True, partitions=("A_kernel", "B_kernel")):
    params = {"argument": "avocado.root=PARTUUID=727dfa31-d47f-4a55-8d62-d812de5ce092", "partitions": list(partitions)}
    if requirement:
        params.update(initramfs_file=INIT, initramfs_contains=MARKER)
    return NS(
        guard=NS(strategy="boot-arg", params=params),
        layout=NS(params={"table": [{"name": "A_kernel", "number": 3}, {"name": "B_kernel", "number": 6}]}),
        images={"boot": NS(partition=3, file="boot.img"), "boot_b": NS(partition=6, file="boot_b.img")},
    )


def test_an_image_whose_init_carries_the_text_passes_and_each_boot_image_is_named(tmp_path):
    _write(tmp_path, _boot_img(gzip.compress(GOOD_CPIO)))
    _write(tmp_path, _boot_img(gzip.compress(GOOD_CPIO)), "boot_b.img")
    assert ramdisk.check_initramfs_requires(_profile(), tmp_path) == ["boot.img", "boot_b.img"]


def test_an_image_whose_init_predates_the_pin_is_refused(tmp_path):
    old = _newc([(INIT, FILE, b"#!/bin/sh\nrootdev=$(blkid -l -t PARTLABEL=APP)\n")])
    _write(tmp_path, _boot_img(gzip.compress(GOOD_CPIO)))
    _write(tmp_path, _boot_img(gzip.compress(old)), "boot_b.img")
    with pytest.raises(RamdiskError, match=f"boot_b.img.*{MARKER}"):
        ramdisk.check_initramfs_requires(_profile(), tmp_path)


def test_an_image_whose_ramdisk_lacks_the_file_is_refused(tmp_path):
    _write(tmp_path, _boot_img(gzip.compress(_newc([("init", FILE, b"x")]))))
    with pytest.raises(RamdiskError, match=f"boot.img.*no {INIT}"):
        ramdisk.check_initramfs_requires(_profile(partitions=("A_kernel",)), tmp_path)


def test_without_a_requirement_nothing_is_read(tmp_path):
    # tmp_path holds no boot image at all; reading one would fail.
    assert ramdisk.check_initramfs_requires(_profile(requirement=False), tmp_path) == []


def test_a_guard_partition_with_no_image_is_refused(tmp_path):
    prof = _profile()
    prof.images = {"boot": NS(partition=3, file="boot.img")}
    _write(tmp_path, _boot_img(gzip.compress(GOOD_CPIO)))
    with pytest.raises(RamdiskError, match="B_kernel"):
        ramdisk.check_initramfs_requires(prof, tmp_path)
