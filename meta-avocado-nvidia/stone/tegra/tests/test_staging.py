import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash import staging
from avocado_tegraflash.manifest import Manifest


class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, text=""):
        self.lines.append(str(text))

    def text(self):
        return "\n".join(self.lines)


def write(path, data=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


@pytest.fixture
def dirs(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    work = tmp_path / "build" / "tegraflash"
    return data, work


# reset_work_dir


def test_reset_work_dir_removes_leftover_file_from_earlier_run(dirs):
    _, work = dirs
    write(work / "stale.txt")
    staging.reset_work_dir(work)
    assert list(work.iterdir()) == []


def test_reset_work_dir_creates_missing_directory_and_parents(dirs):
    _, work = dirs
    staging.reset_work_dir(work)
    assert work.is_dir()


def test_reset_work_dir_removes_leftover_subdirectory(dirs):
    _, work = dirs
    write(work / "sub" / "deep" / "f")
    staging.reset_work_dir(work)
    assert os.listdir(work) == []


def test_reset_work_dir_replaces_a_symlink_without_touching_its_target(tmp_path):
    target = tmp_path / "target"
    write(target / "keep.txt")
    work = tmp_path / "work"
    work.symlink_to(target)
    staging.reset_work_dir(work)
    assert (target / "keep.txt").exists() and not work.is_symlink() and work.is_dir()


# copy_bsp


def test_copy_bsp_copies_hidden_env_file(dirs):
    data, work = dirs
    write(data / "bsp" / ".env.initrd-flash", "TOSIMGFILENAME=x\n")
    write(data / "bsp" / "flash.sh", "#!/bin/sh\n")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    assert (work / ".env.initrd-flash").read_text() == "TOSIMGFILENAME=x\n"


def test_copy_bsp_copies_nested_files(dirs):
    data, work = dirs
    write(data / "bsp" / "a" / "b" / "c.bin", b"\x00\x01")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    assert (work / "a" / "b" / "c.bin").read_bytes() == b"\x00\x01"


def test_copy_bsp_keeps_symlinks_as_symlinks(dirs):
    data, work = dirs
    write(data / "bsp" / "real")
    (data / "bsp" / "link").symlink_to("real")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    assert os.readlink(work / "link") == "real"


def test_copy_bsp_keeps_a_dangling_symlink(dirs):
    data, work = dirs
    (data / "bsp").mkdir()
    (data / "bsp" / "dangling").symlink_to("nowhere")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    assert os.readlink(work / "dangling") == "nowhere"


def test_copy_bsp_empty_name_raises_naming_the_manifest_key(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    with pytest.raises(EngineError, match="tegraflash_bsp"):
        staging.copy_bsp(data, "", work)


def test_copy_bsp_missing_directory_raises_naming_it_and_listing_data_dir(dirs):
    data, work = dirs
    write(data / "present-file.txt")
    staging.reset_work_dir(work)
    with pytest.raises(EngineError) as info:
        staging.copy_bsp(data, "nobsp", work)
    message = str(info.value)
    assert str(data / "nobsp") in message and "present-file.txt" in message


def test_copy_bsp_path_that_is_a_file_raises(dirs):
    data, work = dirs
    write(data / "bsp")
    staging.reset_work_dir(work)
    with pytest.raises(EngineError, match="BSP directory not found"):
        staging.copy_bsp(data, "bsp", work)


# copy_tools


def test_copy_tools_named_directory_copied_with_hidden_files(dirs):
    data, work = dirs
    write(data / "tools" / "tegraflash.py", "py")
    write(data / "tools" / ".hidden", "h")
    staging.reset_work_dir(work)
    staging.copy_tools(data, "tools", "", work)
    assert sorted(p.name for p in work.iterdir()) == [".hidden", "tegraflash.py"]


def test_copy_tools_merges_over_bsp_files(dirs):
    data, work = dirs
    write(data / "bsp" / "shared", "bsp")
    write(data / "bsp" / "only-bsp", "b")
    write(data / "tools" / "shared", "tools")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    staging.copy_tools(data, "tools", "", work)
    assert (work / "shared").read_text() == "tools" and (work / "only-bsp").exists()


def test_copy_tools_named_but_missing_directory_raises_with_listing(dirs):
    data, work = dirs
    write(data / "marker.txt")
    staging.reset_work_dir(work)
    with pytest.raises(EngineError) as info:
        staging.copy_tools(data, "notools", "", work)
    assert str(data / "notools") in str(info.value) and "marker.txt" in str(info.value)


def test_copy_tools_without_name_uses_sdk_tegraflash_directory(dirs, tmp_path):
    data, work = dirs
    sdk = tmp_path / "sdk"
    write(sdk / "sysroots/x86_64-avocadosdk-linux/usr/bin/tegraflash/tool", "sdk")
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_tools(data, "", str(sdk), work, log=log)
    assert (work / "tool").read_text() == "sdk"


def test_copy_tools_without_name_and_sdk_dir_absent_warns_and_continues(dirs, tmp_path):
    data, work = dirs
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_tools(data, "", str(tmp_path / "nosdk"), work, log=log)
    assert "WARNING: Tegraflash tools not found in manifest or SDK" in log.text()


def test_copy_tools_without_name_and_empty_sdk_prefix_warns(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_tools(data, "", "", work, log=log)
    assert "WARNING: Tegraflash tools not found in manifest or SDK" in log.text()


def test_copy_tools_named_directory_wins_over_sdk(dirs, tmp_path):
    data, work = dirs
    write(data / "tools" / "named", "n")
    sdk = tmp_path / "sdk"
    write(sdk / "sysroots/x86_64-avocadosdk-linux/usr/bin/tegraflash/sdkfile", "s")
    staging.reset_work_dir(work)
    staging.copy_tools(data, "tools", str(sdk), work)
    assert sorted(p.name for p in work.iterdir()) == ["named"]


# copy_images


def images(data, **files):
    """Write each named file into data and return a Manifest naming them."""
    fields = {}
    for key, rel in files.items():
        if rel:
            write(data / rel, f"content-of-{rel}".encode())
        fields[key] = rel
    return Manifest(**fields)


def test_copy_images_runtime_images_use_their_own_basename(dirs):
    data, work = dirs
    m = images(data, rootfs="sub/root.img", var="var.img", initramfs="sub/init.cpio")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["init.cpio", "root.img", "var.img"]


def test_copy_images_flash_initramfs_is_copied_as_initrd_flash_img_byte_equal(dirs):
    data, work = dirs
    m = images(data, tegraflash_initramfs="x/flash-init.cpio.gz")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert (work / "initrd-flash.img").read_bytes() == (data / "x/flash-init.cpio.gz").read_bytes()


def test_copy_images_flash_initramfs_is_not_also_copied_under_its_own_name(dirs):
    data, work = dirs
    m = images(data, tegraflash_initramfs="flash-init.cpio.gz")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["initrd-flash.img"]


def test_copy_images_esp_under_own_name_and_esp_img(dirs):
    data, work = dirs
    m = images(data, tegraflash_esp="d/esp-orin.img")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["esp-orin.img", "esp.img"]


def test_copy_images_tos_without_env_file_uses_t234_default(dirs):
    data, work = dirs
    m = images(data, tegraflash_tos="tos.img")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["tos-optee_t234.img", "tos.img"]


def test_copy_images_tos_takes_the_last_tosimgfilename_with_quotes_stripped(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", 'TOSIMGFILENAME=first.img\nOTHER=1\nTOSIMGFILENAME="tos-optee_t264.img"\n')
    m = images(data, tegraflash_tos="tos.img")
    staging.copy_images(data, m, work)
    assert (work / "tos-optee_t264.img").read_bytes() == b"content-of-tos.img"


def test_copy_images_tos_value_keeps_everything_after_first_equals(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", "TOSIMGFILENAME=a=b.img\n")
    staging.copy_images(data, images(data, tegraflash_tos="tos.img"), work)
    assert (work / "a=b.img").exists()


def test_copy_images_tos_empty_value_keeps_the_default(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", 'TOSIMGFILENAME=""\n')
    staging.copy_images(data, images(data, tegraflash_tos="tos.img"), work)
    assert (work / "tos-optee_t234.img").exists()


def test_copy_images_tos_ignores_indented_or_commented_assignment(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", " TOSIMGFILENAME=indented.img\n#TOSIMGFILENAME=c.img\nTOSIMGFILENAME=real.img\n")
    staging.copy_images(data, images(data, tegraflash_tos="tos.img"), work)
    assert (work / "real.img").exists() and not (work / "indented.img").exists()


def test_copy_images_tos_env_file_without_the_key_is_refused(dirs):
    # Oracle line 299: grep | tail | cut under set -e and pipefail aborts (rc 1).
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", "OTHER=1\n #TOSIMGFILENAME=c.img\n")
    with pytest.raises(EngineError) as info:
        staging.copy_images(data, images(data, tegraflash_tos="tos.img"), work)
    assert ".env.initrd-flash" in str(info.value) and "TOSIMGFILENAME" in str(info.value)


def test_copy_images_env_file_without_the_key_is_fine_when_no_tos_is_configured(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", "OTHER=1\n")
    staging.copy_images(data, images(data, rootfs="r.img"), work)
    assert (work / "r.img").exists()


def test_copy_images_absolute_name_is_looked_up_inside_the_data_dir(dirs, tmp_path):
    data, work = dirs
    outside = write(tmp_path / "outside" / "secret.img", "secret")
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_images(data, Manifest(rootfs=str(outside)), work, log=log)
    assert not (work / "secret.img").exists()
    assert f"WARNING: File not found: {data}{outside}" in log.text()


def test_copy_images_absolute_name_inside_the_data_dir_is_staged_from_there(dirs):
    data, work = dirs
    write(data / "abs" / "root.img", "inside")
    staging.reset_work_dir(work)
    staging.copy_images(data, Manifest(rootfs="/abs/root.img"), work)
    assert (work / "root.img").read_text() == "inside"


@pytest.mark.deviation("tos-name-bare-filename")
@pytest.mark.parametrize(
    "value", ["../../escaped-tos.img", "/abs/tos.img", "sub/tos.img", "..", ".", '"."']
)
def test_copy_images_tos_destination_must_be_a_bare_file_name(dirs, tmp_path, value):
    data, work = dirs
    staging.reset_work_dir(work)
    write(work / ".env.initrd-flash", f"TOSIMGFILENAME={value}\n")
    with pytest.raises(EngineError) as info:
        staging.copy_images(data, images(data, tegraflash_tos="tos.img"), work)
    assert ".env.initrd-flash" in str(info.value) and value.replace('"', "") in str(info.value)
    assert not (tmp_path / "escaped-tos.img").exists() and not (tmp_path / "build" / "escaped-tos.img").exists()


def test_copy_bsp_absolute_name_is_not_read_from_outside_the_data_dir(dirs, tmp_path):
    data, work = dirs
    write(tmp_path / "evil" / "f", "x")
    staging.reset_work_dir(work)
    with pytest.raises(EngineError) as info:
        staging.copy_bsp(data, str(tmp_path / "evil"), work)
    assert str(data) in str(info.value) and os.listdir(work) == []


def test_verify_overlays_absolute_name_is_looked_up_inside_the_work_dir(dirs, tmp_path):
    data, work = dirs
    outside = write(tmp_path / "outside.dtbo")
    staging.reset_work_dir(work)
    log = Log()
    staging.verify_overlays(Manifest(overlays=[str(outside)]), work, log=log)
    assert "WARNING: Overlay DTBO not found" in log.text()


@pytest.mark.deviation("symlink-destination-replaced")
def test_tools_symlink_over_an_existing_file_is_replaced_without_writing_through(dirs):
    data, work = dirs
    write(data / "bsp" / "shared", "bsp")
    (data / "tools").mkdir()
    (data / "tools" / "shared").symlink_to("elsewhere")
    staging.reset_work_dir(work)
    staging.copy_bsp(data, "bsp", work)
    staging.copy_tools(data, "tools", "", work)
    assert os.readlink(work / "shared") == "elsewhere"


@pytest.mark.deviation("symlink-destination-replaced")
def test_bsp_file_over_a_destination_symlink_never_modifies_the_target(dirs, tmp_path):
    data, work = dirs
    outside = write(tmp_path / "outside", "untouched")
    write(data / "bsp" / "f", "new")
    staging.reset_work_dir(work)
    (work / "f").symlink_to(outside)
    staging.copy_bsp(data, "bsp", work)
    assert outside.read_text() == "untouched" and (work / "f").read_text() == "new"


@pytest.mark.deviation("symlink-destination-replaced")
def test_image_over_a_dangling_destination_link_does_not_create_the_target(dirs, tmp_path):
    data, work = dirs
    victim = tmp_path / "victim"
    staging.reset_work_dir(work)
    (work / "root.img").symlink_to(victim)
    write(data / "root.img", "img")
    staging.copy_images(data, Manifest(rootfs="root.img"), work)
    assert not victim.exists() and (work / "root.img").read_text() == "img"


def test_copy_bsp_symlinked_destination_directory_is_refused(dirs, tmp_path):
    data, work = dirs
    write(data / "bsp" / "d" / "f", "x")
    outside = tmp_path / "outside"
    outside.mkdir()
    staging.reset_work_dir(work)
    (work / "d").symlink_to(outside)
    with pytest.raises(EngineError):
        staging.copy_bsp(data, "bsp", work)
    assert list(outside.iterdir()) == []


def test_copy_images_dtb_under_own_name_and_kernel_prefixed(dirs):
    data, work = dirs
    m = images(data, dtb="dt/board.dtb")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["board.dtb", "kernel_board.dtb"]


def test_copy_images_bpmp_dtb_under_own_name_only(dirs):
    data, work = dirs
    m = images(data, bpmp_dtb="dt/bpmp.dtb")
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert sorted(p.name for p in work.iterdir()) == ["bpmp.dtb"]


def test_copy_images_absent_file_warns_and_later_images_are_still_copied(dirs):
    data, work = dirs
    write(data / "var.img", "v")
    m = Manifest(rootfs="missing.img", var="var.img")
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_images(data, m, work, log=log)
    assert f"WARNING: File not found: {data / 'missing.img'}" in log.text() and (work / "var.img").exists()


def test_copy_images_absent_flash_initramfs_warns_and_creates_nothing(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_images(data, Manifest(tegraflash_initramfs="gone.cpio"), work, log=log)
    assert "WARNING: File not found" in log.text() and not (work / "initrd-flash.img").exists()


def test_copy_images_empty_manifest_copies_nothing_and_does_not_warn(dirs):
    data, work = dirs
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_images(data, Manifest(), work, log=log)
    assert list(work.iterdir()) == [] and "WARNING" not in log.text()


def test_copy_images_directory_named_as_image_warns_as_not_a_file(dirs):
    data, work = dirs
    (data / "isdir").mkdir()
    staging.reset_work_dir(work)
    log = Log()
    staging.copy_images(data, Manifest(rootfs="isdir"), work, log=log)
    assert "WARNING: File not found" in log.text() and not (work / "isdir").exists()


def test_copy_images_shell_metacharacters_in_name_are_copied_verbatim(dirs):
    data, work = dirs
    name = "a;touch PWNED"
    m = images(data, rootfs=name)
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert (work / name).read_bytes() == b"content-of-a;touch PWNED" and not (work / "PWNED").exists()


def test_copy_images_unicode_and_space_names_are_copied(dirs):
    data, work = dirs
    name = "röot image.img"
    m = images(data, rootfs=name)
    staging.reset_work_dir(work)
    staging.copy_images(data, m, work)
    assert (work / name).exists()


def test_copy_images_overwrites_a_file_the_bsp_already_provided(dirs):
    data, work = dirs
    write(work / "root.img", "from-bsp")
    m = images(data, rootfs="root.img")
    staging.copy_images(data, m, work)
    assert (work / "root.img").read_bytes() == b"content-of-root.img"


def test_copy_images_follows_a_symlinked_source_like_cp(dirs):
    data, work = dirs
    write(data / "real.img", "real")
    (data / "link.img").symlink_to("real.img")
    staging.reset_work_dir(work)
    staging.copy_images(data, Manifest(rootfs="link.img"), work)
    assert not (work / "link.img").is_symlink() and (work / "link.img").read_text() == "real"


# verify_overlays


def test_verify_overlays_warns_once_per_missing_overlay(dirs):
    _, work = dirs
    write(work / "have.dtbo")
    log = Log()
    staging.verify_overlays(Manifest(overlays=("have.dtbo", "gone.dtbo", "gone2.dtbo")), work, log=log)
    warnings = [line for line in log.lines if "WARNING" in line]
    assert warnings == [
        "  WARNING: Overlay DTBO not found: gone.dtbo",
        "  WARNING: Overlay DTBO not found: gone2.dtbo",
    ]


def test_verify_overlays_reports_dce_overlays_separately(dirs):
    _, work = dirs
    log = Log()
    staging.verify_overlays(Manifest(dce_overlays=("dce.dtbo",)), work, log=log)
    assert "  WARNING: DCE overlay DTBO not found: dce.dtbo" in log.lines


def test_verify_overlays_all_present_prints_found_and_no_warning(dirs):
    _, work = dirs
    write(work / "a.dtbo")
    log = Log()
    staging.verify_overlays(Manifest(overlays=("a.dtbo",)), work, log=log)
    assert "  Found: a.dtbo" in log.lines and "WARNING" not in log.text()


def test_verify_overlays_with_no_overlays_prints_nothing(dirs):
    _, work = dirs
    log = Log()
    staging.verify_overlays(Manifest(), work, log=log)
    assert log.lines == []


def test_verify_overlays_a_directory_of_that_name_is_not_a_found_overlay(dirs):
    _, work = dirs
    (work / "d.dtbo").mkdir(parents=True)
    log = Log()
    staging.verify_overlays(Manifest(overlays=("d.dtbo",)), work, log=log)
    assert "  WARNING: Overlay DTBO not found: d.dtbo" in log.lines


# mutation proofs: each falsifier fails on a deliberately broken copy

PACKAGE = Path(staging.__file__).parent


def broken_staging(tmp_path, old, new):
    copy = tmp_path / "mutant" / "avocado_tegraflash"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    source = (copy / "staging.py").read_text()
    assert source.count(old) == 1, source.count(old)
    (copy / "staging.py").write_text(source.replace(old, new))
    saved = {k: v for k, v in sys.modules.items() if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")}
    for key in saved:
        del sys.modules[key]
    sys.path.insert(0, str(copy.parent))
    try:
        return importlib.import_module("avocado_tegraflash.staging"), saved
    finally:
        sys.path.remove(str(copy.parent))


def restore(saved):
    for key in [k for k in sys.modules if k == "avocado_tegraflash" or k.startswith("avocado_tegraflash.")]:
        del sys.modules[key]
    sys.modules.update(saved)


def test_mutation_reset_that_keeps_old_files_is_caught(dirs, tmp_path):
    _, work = dirs
    write(work / "stale.txt")
    mutant, saved = broken_staging(tmp_path, "shutil.rmtree(path)", "return")
    try:
        mutant.reset_work_dir(work)
    finally:
        restore(saved)
    assert (work / "stale.txt").exists()


def test_mutation_bsp_copy_that_skips_hidden_files_is_caught(dirs, tmp_path):
    data, work = dirs
    write(data / "bsp" / ".env.initrd-flash")
    write(data / "bsp" / "visible")
    mutant, saved = broken_staging(
        tmp_path,
        'merge_tree(_source_dir(data_dir, bsp_name, "BSP"), work_dir)',
        'shutil.copytree(_source_dir(data_dir, bsp_name, "BSP"), work_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".*"))',
    )
    try:
        mutant.reset_work_dir(work)
        mutant.copy_bsp(data, "bsp", work)
    finally:
        restore(saved)
    assert not (work / ".env.initrd-flash").exists()


def test_mutation_missing_bsp_that_does_not_raise_is_caught(dirs, tmp_path):
    data, work = dirs
    mutant, saved = broken_staging(tmp_path, "if not src.is_dir():", "if False:")
    try:
        mutant.reset_work_dir(work)
        with pytest.raises(Exception) as info:
            mutant.copy_bsp(data, "nobsp", work)
    finally:
        restore(saved)
    assert not isinstance(info.value, EngineError)


def test_mutation_absent_image_that_stops_the_run_is_caught(dirs, tmp_path):
    data, work = dirs
    write(data / "var.img")
    mutant, saved = broken_staging(
        tmp_path, 'log(f"WARNING: File not found: {src}")', 'raise RuntimeError("stop")'
    )
    try:
        mutant.reset_work_dir(work)
        with pytest.raises(RuntimeError):
            mutant.copy_images(data, Manifest(rootfs="missing.img", var="var.img"), work)
    finally:
        restore(saved)
    assert not (work / "var.img").exists()
