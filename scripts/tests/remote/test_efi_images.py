"""Tests for the EFI variable reader and the streaming image scanner."""

from __future__ import annotations

import ast
import hashlib
import io
import pathlib

import pytest

from avocado_flash_remote import efi, images


class NoSeekFile(io.RawIOBase):
    """Behaves like an efivarfs file: sequential reads only."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def readable(self):
        return True

    def seekable(self):
        return False

    def seek(self, *a, **k):
        raise OSError(29, "Illegal seek")

    def tell(self):
        raise OSError(29, "Illegal seek")

    def readinto(self, b):
        data = self._buf.read(len(b))
        b[: len(data)] = data
        return len(data)

    def read(self, n=-1):
        return self._buf.read(n)


def _opener(data: bytes):
    def opener(path, mode="rb", buffering=-1):
        return NoSeekFile(data)

    return opener


ATTR = b"\x07\x00\x00\x00"


def test_secure_boot_disabled(monkeypatch):
    var = efi.read_variable("x", opener=_opener(ATTR + b"\x00"))
    assert var.ok and var.attributes == ATTR and var.data == b"\x00"


def test_secure_boot_state_values(tmp_path):
    p = tmp_path / "SecureBoot-x"
    p.write_bytes(ATTR + b"\x00")
    assert efi.secure_boot_state(p) == "disabled"
    p.write_bytes(ATTR + b"\x01")
    assert efi.secure_boot_state(p) == "enabled"


def test_four_byte_file_unreadable(tmp_path):
    var = efi.read_variable("x", opener=_opener(ATTR))
    assert not var.ok and var.reason
    p = tmp_path / "v"
    p.write_bytes(ATTR)
    assert efi.secure_boot_state(p) == "unreadable"


def test_zero_length_unreadable(tmp_path):
    var = efi.read_variable("x", opener=_opener(b""))
    assert not var.ok
    p = tmp_path / "v"
    p.write_bytes(b"")
    assert efi.secure_boot_state(p) == "unreadable"


def test_missing_file_unreadable(tmp_path):
    assert efi.secure_boot_state(tmp_path / "nope") == "unreadable"


@pytest.mark.parametrize("data", [b"\x01\x00", b"\x00\x00", b"\x00\x01", b"\x02", b"\xff", b"\x00\x00\x00\x00"])
def test_secure_boot_needs_exactly_one_data_byte_of_zero_or_one(tmp_path, data):
    p = tmp_path / "v"
    p.write_bytes(ATTR + data)
    assert efi.secure_boot_state(p) == "unreadable"


def test_efi_source_has_no_seek_tell_pread_mmap():
    src = pathlib.Path(efi.__file__).read_text()
    tree = ast.parse(src)
    forbidden = {"seek", "tell", "pread", "mmap"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, node.attr
        if isinstance(node, ast.Name):
            assert node.id not in forbidden, node.id
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            assert "mmap" not in names


# ---------------------------------------------------------------- images


def test_scan_hash_and_not_zero(tmp_path):
    p = tmp_path / "a.img"
    data = b"hello world" * 1000
    p.write_bytes(data)
    r = images.scan(p, chunk=64)
    assert r.size == len(data)
    assert r.sha256 == hashlib.sha256(data).hexdigest()
    assert r.all_zero is False
    st = p.stat()
    assert r.identity == (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def test_scan_all_zero(tmp_path):
    p = tmp_path / "z.img"
    p.write_bytes(bytes(1000))
    assert images.scan(p, chunk=64).all_zero is True


def test_scan_zero_length(tmp_path):
    p = tmp_path / "e.img"
    p.write_bytes(b"")
    r = images.scan(p)
    assert r.size == 0 and r.sha256 == hashlib.sha256(b"").hexdigest()
    assert r.all_zero is True


def test_scan_last_byte_nonzero(tmp_path):
    p = tmp_path / "l.img"
    p.write_bytes(bytes(999) + b"\x01")
    assert images.scan(p, chunk=64).all_zero is False


def test_scan_large_sparse_bounded_chunks(tmp_path, monkeypatch):
    p = tmp_path / "s.img"
    size = 300 * 1024 * 1024
    with open(p, "wb") as f:
        f.truncate(size)
    with open(p, "r+b") as f:
        f.seek(size - 1)
        f.write(b"\x01")
    sizes = []
    real_open = open

    class Spy:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def read(self, n=-1):
            sizes.append(n)
            return self.f.read(n)

        def readinto(self, b):
            sizes.append(len(b))
            return self.f.readinto(b)

    monkeypatch.setattr(
        images, "_open", lambda path: Spy(real_open(path, "rb", buffering=0))
    )
    r = images.scan(p, chunk=1 << 20)
    assert r.size == size and r.all_zero is False
    assert sizes and all(0 < n <= 1 << 20 for n in sizes)


def test_reverify_ok(tmp_path):
    p = tmp_path / "a.img"
    p.write_bytes(b"abc" * 100)
    r = images.scan(p)
    images.reverify(p, r)


def test_reverify_content_changed_same_size_and_mtime(tmp_path):
    import os

    p = tmp_path / "a.img"
    p.write_bytes(b"abc" * 100)
    r = images.scan(p)
    st = p.stat()
    p.write_bytes(b"abd" * 100)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    with pytest.raises(images.ImageChanged):
        images.reverify(p, r)


def test_reverify_replaced_file(tmp_path):
    p = tmp_path / "a.img"
    p.write_bytes(b"abc" * 100)
    r = images.scan(p)
    p.unlink()
    p.write_bytes(b"abc" * 100)
    with pytest.raises(images.ImageChanged):
        images.reverify(p, r)


def test_reverify_missing(tmp_path):
    p = tmp_path / "a.img"
    p.write_bytes(b"x")
    r = images.scan(p)
    p.unlink()
    with pytest.raises(images.ImageChanged):
        images.reverify(p, r)


@pytest.mark.parametrize("bad", [0, -4, 1.5, "4096", None, True])
def test_scan_and_reverify_refuse_a_chunk_that_is_not_a_positive_integer(tmp_path, bad):
    f = tmp_path / "i.img"
    f.write_bytes(b"abc")
    good = images.scan(f)
    with pytest.raises(ValueError, match="chunk"):
        images.scan(f, chunk=bad)
    with pytest.raises(ValueError, match="chunk"):
        images.reverify(f, good, chunk=bad)
