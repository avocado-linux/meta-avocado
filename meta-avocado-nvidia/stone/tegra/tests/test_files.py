import os

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.files import (
    copy_replacing_link,
    join_name,
    merge_tree,
    write_text_replacing_link,
)


def test_plain_file_is_overwritten_in_place(tmp_path):
    path = tmp_path / "f"
    path.write_text("old")
    write_text_replacing_link(path, "new")
    assert (path.read_text(), path.is_symlink()) == ("new", False)


def test_missing_file_is_created(tmp_path):
    write_text_replacing_link(tmp_path / "f", "x")
    assert (tmp_path / "f").read_text() == "x"


def test_dangling_symlink_is_replaced_by_a_regular_file(tmp_path):
    path = tmp_path / "f"
    path.symlink_to(tmp_path / "gone")
    write_text_replacing_link(path, "x")
    assert (path.read_text(), path.is_symlink(), (tmp_path / "gone").exists()) == ("x", False, False)


def test_newline_and_encoding_arguments_are_honoured(tmp_path):
    path = tmp_path / "f"
    write_text_replacing_link(path, "a\r\nb\udcff", encoding="utf-8", errors="surrogateescape", newline="")
    assert path.read_bytes() == b"a\r\nb\xff"


def test_join_name_keeps_an_absolute_name_inside_the_base(tmp_path):
    assert join_name(tmp_path, "/etc/passwd") == tmp_path / "etc" / "passwd"


def test_join_name_keeps_dotdot_components_like_the_oracle(tmp_path):
    assert str(join_name(tmp_path, "../x")) == f"{tmp_path}/../x"


def test_merge_tree_merges_directories_and_hidden_files(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "d").mkdir(parents=True)
    (src / "d" / ".h").write_text("new")
    (dst / "d").mkdir(parents=True)
    (dst / "d" / "keep").write_text("k")
    merge_tree(src, dst)
    assert (dst / "d" / ".h").read_text() == "new" and (dst / "d" / "keep").read_text() == "k"


def test_merge_tree_symlink_replaces_an_existing_file(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "f").symlink_to("target")
    (dst / "f").write_text("old")
    merge_tree(src, dst)
    assert os.readlink(dst / "f") == "target"


def test_merge_tree_file_replaces_a_symlink_without_writing_through(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    (src / "f").write_text("new")
    (dst / "f").symlink_to(outside)
    merge_tree(src, dst)
    assert (dst / "f").is_symlink() is False and (dst / "f").read_text() == "new"
    assert outside.read_text() == "untouched"


def test_merge_tree_dangling_destination_link_is_replaced_not_created_through(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    victim = tmp_path / "victim"
    (src / "f").write_text("new")
    (dst / "f").symlink_to(victim)
    merge_tree(src, dst)
    assert not victim.exists() and (dst / "f").read_text() == "new"


def test_merge_tree_refuses_a_symlinked_destination_directory(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "d").mkdir(parents=True)
    (src / "d" / "f").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    dst.mkdir()
    (dst / "d").symlink_to(outside)
    with pytest.raises(EngineError, match="d"):
        merge_tree(src, dst)
    assert list(outside.iterdir()) == []


def test_merge_tree_refuses_a_directory_over_a_file(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "d").mkdir(parents=True)
    dst.mkdir()
    (dst / "d").write_text("file")
    with pytest.raises(EngineError):
        merge_tree(src, dst)


def test_merge_tree_refuses_a_file_over_a_directory(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "d").write_text("x")
    (dst / "d").mkdir(parents=True)
    with pytest.raises(EngineError):
        merge_tree(src, dst)


def test_merge_tree_keeps_symlinks_as_links(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "dangling").symlink_to("nowhere")
    merge_tree(src, dst)
    assert os.readlink(dst / "dangling") == "nowhere"


def test_copy_replacing_link_replaces_a_symlink_and_leaves_its_target(tmp_path):
    src = tmp_path / "src"
    src.write_text("new")
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    dst = tmp_path / "dst"
    dst.symlink_to(outside)
    copy_replacing_link(src, dst)
    assert not dst.is_symlink() and dst.read_text() == "new" and outside.read_text() == "untouched"


def test_copy_replacing_link_dangling_link_does_not_create_its_target(tmp_path):
    src = tmp_path / "src"
    src.write_text("new")
    victim = tmp_path / "victim"
    dst = tmp_path / "dst"
    dst.symlink_to(victim)
    copy_replacing_link(src, dst)
    assert not victim.exists() and dst.read_text() == "new"


def test_copy_replacing_link_failure_is_an_engine_error_naming_the_path(tmp_path):
    src = tmp_path / "src"
    src.write_text("x")
    with pytest.raises(EngineError, match="nodir"):
        copy_replacing_link(src, tmp_path / "nodir" / "dst")


def _spy_replace(monkeypatch, seen):
    real = os.replace

    def spy(src, dst, *a, **k):
        seen.append((str(src), str(dst), os.path.islink(dst), os.path.lexists(dst)))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", spy)


def test_copy_replacing_link_installs_through_a_sibling_temp_and_rename(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.write_text("new")
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    dst = tmp_path / "dst"
    dst.symlink_to(outside)
    seen = []
    _spy_replace(monkeypatch, seen)
    copy_replacing_link(src, dst)
    [(tmp, target, was_link, existed)] = seen
    assert os.path.dirname(tmp) == str(tmp_path) and tmp != str(dst) and target == str(dst)
    # the destination still held the old link when the rename ran: no unlink-then-copy window
    assert was_link and existed
    assert dst.read_text() == "new" and not dst.is_symlink() and outside.read_text() == "untouched"


def test_copy_replacing_link_leaves_no_temp_file_after_success(tmp_path):
    src = tmp_path / "src"
    src.write_text("new")
    dst = tmp_path / "dst"
    dst.write_text("old")
    copy_replacing_link(src, dst)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dst", "src"]


def test_copy_replacing_link_leaves_no_temp_file_and_keeps_the_old_destination_on_failure(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.write_text("new")
    dst = tmp_path / "dst"
    dst.write_text("old")

    def boom(*_a, **_k):
        raise OSError("rename refused")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(EngineError, match="rename refused"):
        copy_replacing_link(src, dst)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dst", "src"] and dst.read_text() == "old"


def test_copy_replacing_link_keeps_the_source_mode(tmp_path):
    src = tmp_path / "src"
    src.write_text("x")
    src.chmod(0o751)
    dst = tmp_path / "dst"
    copy_replacing_link(src, dst)
    assert (dst.stat().st_mode & 0o777) == 0o751


def test_copy_replacing_link_into_a_directory_destination_copies_inside_it(tmp_path):
    src = tmp_path / "src"
    src.write_text("x")
    dst = tmp_path / "d"
    dst.mkdir()
    copy_replacing_link(src, dst)
    assert (dst / "src").read_text() == "x"


def test_merge_tree_installs_files_and_links_over_existing_ones_by_rename(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "f").write_text("new")
    (src / "l").symlink_to("target")
    old = tmp_path / "old"
    old.write_text("old")
    (dst / "f").symlink_to(old)
    (dst / "l").write_text("was a file")
    os.utime(src / "f", (1_000_000, 1_000_000))
    seen = []
    _spy_replace(monkeypatch, seen)
    merge_tree(src, dst)
    assert sorted(os.path.basename(t) for _s, t, _l, _e in seen) == ["f", "l"]
    assert all(existed for _s, _t, _l, existed in seen)
    assert (dst / "f").read_text() == "new" and not (dst / "f").is_symlink() and old.read_text() == "old"
    assert os.readlink(dst / "l") == "target"
    assert int((dst / "f").stat().st_mtime) == 1_000_000
    assert sorted(p.name for p in dst.iterdir()) == ["f", "l"]


def test_install_without_rename_is_caught_by_the_rename_expectation(tmp_path, monkeypatch):
    """Mutation: restoring unlink-then-copy leaves the rename spy unused."""
    import importlib
    import shutil
    import sys

    import avocado_tegraflash

    pkg = tmp_path / "mut" / "avocado_tegraflash"
    shutil.copytree(os.path.dirname(avocado_tegraflash.__file__), pkg, ignore=shutil.ignore_patterns("__pycache__"))
    source = (pkg / "files.py").read_text()
    old = "os.replace(tmp, dst)"
    assert source.count(old) == 1
    (pkg / "files.py").write_text(source.replace(old, "dst.unlink(missing_ok=True); shutil.copyfile(tmp, dst)"))
    saved = {k: v for k, v in sys.modules.items() if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")}
    for k in saved:
        del sys.modules[k]
    monkeypatch.syspath_prepend(str(tmp_path / "mut"))
    try:
        mutated = importlib.import_module("avocado_tegraflash.files")
        assert mutated.__file__.startswith(str(tmp_path / "mut"))
        seen = []
        _spy_replace(monkeypatch, seen)
        src = tmp_path / "src"
        src.write_text("new")
        dst = tmp_path / "dst"
        dst.write_text("old")
        mutated.copy_replacing_link(src, dst)
        assert seen == []  # the guarded test above expects exactly one rename and fails on this copy
    finally:
        for k in [k for k in sys.modules if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")]:
            del sys.modules[k]
        sys.modules.update(saved)
