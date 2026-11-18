import os
import time
from pathlib import Path

import pytest

from avocado_flash_launch.envmap import LauncherError
from avocado_flash_launch.inputs import (
    assemble_inputs,
    check_profile,
    jetson_kernel_image,
    stale_check,
    stone_dir_for,
    var_size_bytes,
)


def manifest(profiles=None, var="var.btrfs"):
    return {
        "provision": {"profiles": profiles if profiles is not None else {"sd": {}}},
        "storage_devices": {"rootdisk": {"images": {"var": var, "rootfs": "rootfs.erofs"}}},
    }


# ---- check_profile: runs before any scratch directory exists


def test_missing_profile_names_machine_and_profile(tmp_path):
    scratch = tmp_path / "scratch"
    with pytest.raises(LauncherError) as e:
        check_profile(manifest({"sd": {}}), "imx93-frdm", "uuu-emmc", dry_run=False)
    assert "imx93-frdm" in str(e.value) and "uuu-emmc" in str(e.value)
    assert not scratch.exists()


def test_dry_run_requires_declaration_naming_profile():
    m = manifest({"sd": {"config": {}}})
    with pytest.raises(LauncherError) as e:
        check_profile(m, "imx93-frdm", "sd", dry_run=True)
    assert "sd" in str(e.value) and "dry_run" in str(e.value)


def test_dry_run_requires_true_not_truthy():
    m = manifest({"sd": {"config": {"dry_run": "yes"}}})
    with pytest.raises(LauncherError):
        check_profile(m, "m", "sd", dry_run=True)


def test_dry_run_declared_passes():
    check_profile(manifest({"sd": {"config": {"dry_run": True}}}), "m", "sd", dry_run=True)


def test_no_dry_run_needs_no_declaration():
    check_profile(manifest({"sd": {}}), "m", "sd", dry_run=False)


# ---- stone_dir_for


def test_stone_dir_used_only_when_manifest_names_machine(tmp_path):
    stone = tmp_path / "stone"
    stone.mkdir()
    assert stone_dir_for(tmp_path, "avocado-imx93-frdm") is None
    (stone / "stone-imx93-frdm.json").write_text("{}")
    assert stone_dir_for(tmp_path, "avocado-imx93-frdm") == stone


def test_stone_dir_absent(tmp_path):
    assert stone_dir_for(tmp_path, "jetson-orin-nano") is None


# ---- assemble_inputs


def test_images_dir_inputs_link_manifest_and_skip_build(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "stone-jetson.json").write_text("{}")
    (images / "Image").write_text("k")
    (images / "_build").mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    made = assemble_inputs("jetson", None, images, scratch)
    assert (scratch / "manifest.json").resolve() == (images / "stone-jetson.json").resolve()
    assert (scratch / "Image").resolve() == (images / "Image").resolve()
    assert not (scratch / "_build").exists() and not (scratch / "_build").is_symlink()
    assert all((scratch / n).is_symlink() for n in made)
    assert "manifest.json" in made


def test_stone_dir_inputs_resolve_into_stone_and_skip_build(tmp_path):
    stone = tmp_path / "stone"
    stone.mkdir()
    (stone / "stone-m.json").write_text("{}")
    (stone / "os-bundle.aos").write_text("b")
    (stone / "_build").mkdir()
    images = tmp_path / "images"
    images.mkdir()
    (images / "other").write_text("x")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    assemble_inputs("m", stone, images, scratch)
    for p in scratch.iterdir():
        assert p.is_symlink()
        assert str(p.resolve()).startswith(str(stone.resolve()))
    assert not (scratch / "_build").exists()
    assert not (scratch / "other").exists()
    assert (scratch / "manifest.json").resolve() == (stone / "stone-m.json").resolve()


def test_existing_manifest_json_is_not_overridden(tmp_path):
    stone = tmp_path / "stone"
    stone.mkdir()
    (stone / "manifest.json").write_text("{}")
    (stone / "stone-m.json").write_text("{}")
    scratch = tmp_path / "s"
    scratch.mkdir()
    assemble_inputs("m", stone, tmp_path, scratch)
    assert (scratch / "manifest.json").resolve() == (stone / "manifest.json").resolve()


def test_missing_manifest_refuses(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    scratch = tmp_path / "s"
    scratch.mkdir()
    with pytest.raises(LauncherError) as e:
        assemble_inputs("m", None, images, scratch)
    assert "stone-m.json" in str(e.value)


# ---- var_size_bytes


def test_var_size_from_manifest_var_image(tmp_path):
    (tmp_path / "var.btrfs").write_bytes(b"x" * 1234)
    assert var_size_bytes(manifest(), tmp_path) == 1234


def test_var_size_missing_image_refuses(tmp_path):
    with pytest.raises(LauncherError) as e:
        var_size_bytes(manifest(), tmp_path)
    assert "var.btrfs" in str(e.value)


def test_var_size_follows_symlink(tmp_path):
    real = tmp_path / "real"
    real.write_bytes(b"abc")
    (tmp_path / "var.btrfs").symlink_to(real)
    assert var_size_bytes(manifest(), tmp_path) == 3


# ---- jetson_kernel_image


def test_kernel_image_returned_absolute(tmp_path):
    (tmp_path / "Image").write_text("k")
    assert jetson_kernel_image(tmp_path) == str(tmp_path.resolve() / "Image")


def test_kernel_image_missing_names_it(tmp_path):
    with pytest.raises(LauncherError) as e:
        jetson_kernel_image(tmp_path)
    assert str(tmp_path / "Image") in str(e.value)


def test_kernel_image_empty_refuses(tmp_path):
    (tmp_path / "Image").write_text("")
    with pytest.raises(LauncherError):
        jetson_kernel_image(tmp_path)


# ---- stale_check


def _age(p: Path, secs_ago: float):
    t = time.time() - secs_ago
    os.utime(p, (t, t))


def _tree(tmp_path):
    stone = tmp_path / "stone"
    stone.mkdir()
    bundle = stone / "os-bundle.aos"
    bundle.write_text("b")
    _age(bundle, 1000)
    images = tmp_path / "images"
    images.mkdir()
    return stone, images


def test_stale_names_stone_newest_and_refresh_step(tmp_path):
    stone, images = _tree(tmp_path)
    k = images / "Image"
    k.write_text("k")
    _age(k, 10)
    with pytest.raises(LauncherError) as e:
        stale_check(stone, images, stale_ok=False)
    msg = str(e.value)
    assert str(stone) in msg and str(k) in msg and "stone_provision" in msg


def test_stale_ok_allows(tmp_path):
    stone, images = _tree(tmp_path)
    k = images / "Image"
    k.write_text("k")
    stale_check(stone, images, stale_ok=True)


def test_fresh_passes(tmp_path):
    stone, images = _tree(tmp_path)
    k = images / "Image"
    k.write_text("k")
    _age(k, 5000)
    stale_check(stone, images, stale_ok=False)


def test_symlink_target_mtime_is_followed(tmp_path):
    stone, images = _tree(tmp_path)
    real = tmp_path / "real"
    real.write_text("r")
    _age(real, 10)
    (images / "link").symlink_to(real)
    with pytest.raises(LauncherError):
        stale_check(stone, images, stale_ok=False)


def test_images_dir_inputs_never_stale(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "Image").write_text("k")
    stale_check(None, images, stale_ok=False)
