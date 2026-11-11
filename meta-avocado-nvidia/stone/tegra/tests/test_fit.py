"""Partition fit check against the staged layout."""

from pathlib import Path

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.fit import require_fit
from avocado_tegraflash.manifest import Manifest


def layout(app="8192", esp="4096", extra="", app_b=None, esp_file="esp.img", app_file=None, app_b_file=None):
    parts = ""
    if app is not None:
        fname = f"<filename>{app_file}</filename>" if app_file else ""
        parts += f'<partition name="APP" type="data"><size>{app}</size>{fname}</partition>\n'
    if app_b is not None:
        fname = f"<filename>{app_b_file}</filename>" if app_b_file else ""
        parts += f'<partition name="APP_b" type="data"><size>{app_b}</size>{fname}</partition>\n'
    if esp is not None:
        fname = f"<filename>{esp_file}</filename>" if esp_file else ""
        parts += f'<partition name="esp" type="data"><size>{esp}</size>{fname}</partition>\n'
    return f'<?xml version="1.0"?>\n<partition_layout>\n<device>\n{parts}{extra}</device>\n</partition_layout>\n'


def stage(tmp_path, xml=None, rootfs=4096, esp=2048, name="rootfs.img", env=None):
    if env is None:
        env = f'ROOTFS_IMAGE="{name}"\n'
    if env is not False:
        (tmp_path / ".env.initrd-flash").write_text(env)
    if xml is not None:
        data = xml if isinstance(xml, bytes) else xml.encode()
        (tmp_path / "external-flash.xml.in").write_bytes(data)
    if rootfs is not None:
        (tmp_path / name).write_bytes(b"\0" * rootfs)
    if esp is not None:
        (tmp_path / "esp.img").write_bytes(b"\0" * esp)
    return Manifest(rootfs=f"images/{name}", tegraflash_esp="esp.bin")


def run(tmp_path, manifest):
    logs = []
    require_fit(tmp_path, manifest, logs.append)
    return logs


def refusal(tmp_path, manifest):
    with pytest.raises(EngineError) as exc:
        run(tmp_path, manifest)
    return str(exc.value)


def test_pass_logs_one_line_per_pair(tmp_path):
    m = stage(tmp_path, layout())
    assert run(tmp_path, m) == ["fit: rootfs 4096 <= APP 8192", "fit: tegraflash_esp 2048 <= esp 4096"]


def test_exact_fit_passes(tmp_path):
    m = stage(tmp_path, layout(app="4096", esp="2048"))
    assert len(run(tmp_path, m)) == 2


def test_one_byte_over_refused_with_names_and_sizes(tmp_path):
    m = stage(tmp_path, layout(app="4095"))
    msg = refusal(tmp_path, m)
    assert "rootfs image rootfs.img (4096 bytes) does not fit partition APP (4095 bytes)" in msg


def test_emmc_shaped_layout_same_file_name(tmp_path):
    m = stage(tmp_path, layout(extra='<partition name="other"><size>1</size></partition>\n'), name="rootfs.ext4")
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 8192"


def test_hex_size_parsed(tmp_path):
    m = stage(tmp_path, layout(app="0x2000"))
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 8192"


def test_unparseable_layout_refused(tmp_path):
    m = stage(tmp_path, "<partition_layout><oops>")
    assert "unreadable" in refusal(tmp_path, m)


def test_doctype_refused(tmp_path):
    m = stage(tmp_path, '<!DOCTYPE x [<!ELEMENT x ANY>]>\n' + layout())
    assert "DOCTYPE or entity" in refusal(tmp_path, m)


def test_entity_refused(tmp_path):
    m = stage(tmp_path, layout(extra='<!ENTITY a "b">'))
    assert "DOCTYPE or entity" in refusal(tmp_path, m)


def test_utf16_refused(tmp_path):
    m = stage(tmp_path, layout().encode("utf-16"))
    assert "UTF-16" in refusal(tmp_path, m)


def test_oversize_layout_refused(tmp_path):
    m = stage(tmp_path, layout(extra="<!-- " + "x" * (4 * 1024 * 1024) + " -->"))
    assert "larger than" in refusal(tmp_path, m)


def test_duplicate_app_refused(tmp_path):
    m = stage(tmp_path, layout(extra='<partition name="APP"><size>1</size></partition>\n'))
    assert "partition APP is listed more than once" in refusal(tmp_path, m)


def test_absent_esp_refused(tmp_path):
    m = stage(tmp_path, layout(esp=None))
    assert "partition esp is absent" in refusal(tmp_path, m)


def test_non_numeric_size_refused(tmp_path):
    m = stage(tmp_path, layout(app="big"))
    assert "'big', not a number" in refusal(tmp_path, m)


def test_absent_layout_file_refused_naming_it(tmp_path):
    m = stage(tmp_path, None)
    assert "external-flash.xml.in is absent" in refusal(tmp_path, m)


def test_an_unnamed_required_image_is_refused_not_skipped(tmp_path):
    stage(tmp_path, layout(esp=None))
    m = Manifest(rootfs="images/rootfs.img")
    assert "no file for tegraflash_esp" in refusal(tmp_path, m)


def test_several_problems_in_one_error(tmp_path):
    m = stage(tmp_path, layout(app="10", esp="20"))
    msg = refusal(tmp_path, m)
    assert "partition APP (10 bytes)" in msg and "partition esp (20 bytes)" in msg


def test_nothing_logged_when_refused(tmp_path):
    m = stage(tmp_path, layout(app="10"))
    logs = []
    with pytest.raises(EngineError):
        require_fit(tmp_path, m, logs.append)
    assert logs == []


@pytest.mark.parametrize("rootfs", ["images/", "images/.", "images/.."])
def test_a_rootfs_name_with_no_file_component_is_refused_not_skipped(tmp_path, rootfs):
    stage(tmp_path, layout(app="10"))
    m = Manifest(rootfs=rootfs, tegraflash_esp="esp.bin")
    assert "rootfs" in refusal(tmp_path, m)


def test_a_directory_as_the_measured_rootfs_is_refused(tmp_path):
    stage(tmp_path, layout(app="10"), rootfs=None, env='ROOTFS_IMAGE="rootfs.img"\n')
    (tmp_path / "rootfs.img").mkdir()
    (tmp_path / "rootfs.img" / "big").write_bytes(b"\0" * 9999)
    assert "not a regular file" in refusal(tmp_path, Manifest(rootfs="images/rootfs.img", tegraflash_esp="esp.bin"))


def test_a_directory_as_the_measured_esp_is_refused(tmp_path):
    stage(tmp_path, layout(), esp=None)
    (tmp_path / "esp.img").mkdir()
    assert "not a regular file" in refusal(tmp_path, Manifest(rootfs="rootfs.img", tegraflash_esp="esp.bin"))


def test_the_last_rootfs_image_in_the_env_file_is_the_one_checked(tmp_path):
    m = stage(tmp_path, layout(app="10"), env='ROOTFS_IMAGE="first.img"\nROOTFS_IMAGE="rootfs.img"\n')
    assert "does not fit partition APP (10 bytes)" in refusal(tmp_path, m)


def test_a_carrier_rewritten_rootfs_image_is_refused_not_measured_as_the_manifest_name(tmp_path):
    m = stage(tmp_path, layout(app="10"), env='ROOTFS_IMAGE="big.img"\n')
    (tmp_path / "big.img").write_bytes(b"\0" * 5000)
    msg = refusal(tmp_path, m)
    assert "ROOTFS_IMAGE" in msg and "big.img" in msg and "rootfs.img" in msg


def test_a_missing_env_file_is_refused(tmp_path):
    m = stage(tmp_path, layout(), env=False)
    assert ".env.initrd-flash" in refusal(tmp_path, m)


def test_an_env_file_without_rootfs_image_falls_back_to_the_staged_name(tmp_path):
    m = stage(tmp_path, layout(), env="BOOTDEV=x\n")
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 8192"


def test_the_smaller_of_app_and_app_b_decides(tmp_path):
    m = stage(tmp_path, layout(app="8192", app_b="4000"))
    assert "does not fit partition APP_b (4000 bytes)" in refusal(tmp_path, m)


def test_app_b_larger_than_app_is_not_the_limit(tmp_path):
    m = stage(tmp_path, layout(app="5000", app_b="9000"))
    assert run(tmp_path, m)[0] == "fit: rootfs 4096 <= APP 5000"


def test_a_non_numeric_app_b_is_refused(tmp_path):
    m = stage(tmp_path, layout(app_b="big"))
    assert "APP_b" in refusal(tmp_path, m)


def test_an_esp_filename_other_than_the_staged_one_is_refused(tmp_path):
    m = stage(tmp_path, layout(esp_file="other.img"))
    msg = refusal(tmp_path, m)
    assert "other.img" in msg and "esp.img" in msg


def test_an_esp_filename_matching_the_staged_one_passes(tmp_path):
    m = stage(tmp_path, layout(esp_file="esp.img"))
    assert len(run(tmp_path, m)) == 2


def test_a_missing_esp_filename_is_refused(tmp_path):
    m = stage(tmp_path, layout(esp_file=""))
    msg = refusal(tmp_path, m)
    assert "esp" in msg and "no <filename>" in msg


@pytest.mark.parametrize("line", ['export ROOTFS_IMAGE="big.img"', '  ROOTFS_IMAGE="big.img"', 'X=1; ROOTFS_IMAGE="big.img"'])
def test_a_non_plain_rootfs_image_assignment_is_refused_not_measured(tmp_path, line):
    m = stage(tmp_path, layout(app="10"), env=f'ROOTFS_IMAGE="rootfs.img"\n{line}\n')
    (tmp_path / "big.img").write_bytes(b"\0" * 5000)
    msg = refusal(tmp_path, m)
    assert "sources this file with bash" in msg and ".env.initrd-flash:2" in msg


def test_the_first_of_two_rootfs_images_plays_no_part(tmp_path):
    m = stage(tmp_path, layout(), env='ROOTFS_IMAGE="first.img"\nROOTFS_IMAGE="last.img"\n')
    msg = refusal(tmp_path, m)
    assert "last.img" in msg and "first.img" not in msg


@pytest.mark.parametrize("which", ["app_file", "app_b_file"])
def test_a_literal_app_filename_that_is_not_the_staged_rootfs_is_refused(tmp_path, which):
    m = stage(tmp_path, layout(app_b="8192", **{which: "big.ext4"}))
    msg = refusal(tmp_path, m)
    assert "big.ext4" in msg and ("APP_b" if which == "app_b_file" else "partition APP ") in msg


@pytest.mark.parametrize("app,app_b", [("APPFILE", "APPFILE_b"), ("rootfs.img", "rootfs.img"), (None, None)])
def test_app_filenames_that_name_the_placeholder_or_the_staged_rootfs_pass(tmp_path, app, app_b):
    m = stage(tmp_path, layout(app_b="8192", app_file=app, app_b_file=app_b))
    assert len(run(tmp_path, m)) == 2


def test_the_placeholders_are_not_interchangeable_between_slots(tmp_path):
    m = stage(tmp_path, layout(app_b="8192", app_file="APPFILE_b", app_b_file="APPFILE"))
    msg = refusal(tmp_path, m)
    assert "APPFILE_b" in msg and "APPFILE'" in msg


# initrd-flash.sh rewrites a copy of the layout with `sed s,${ROOTFS_IMAGE%.*}.img,$ROOTFS_IMAGE,` (unanchored,
# `.` matches any character) and `s,APPFILE,$ROOTFS_IMAGE,` on every line, whatever partition holds the name.


def _extra_partition(name, filename):
    return f'<partition name="{name}" type="data"><size>10</size><filename>{filename}</filename></partition>\n'


def test_a_layout_filename_the_flash_would_rewrite_to_the_rootfs_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "root.img")), name="root.ext4")
    msg = refusal(tmp_path, m)
    assert "root.img" in msg and "UDA" in msg and "root.ext4" in msg


def test_the_dot_of_the_rewritten_name_matches_any_character(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "rootXimg")), name="root.ext4")
    assert "rootXimg" in refusal(tmp_path, m)


def test_the_rewrite_pattern_is_unanchored(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "pre-root.img-post")), name="root.ext4")
    assert "pre-root.img-post" in refusal(tmp_path, m)


def test_a_staged_rootfs_that_contains_its_own_rewrite_pattern_is_not_a_collision(tmp_path):
    # rootfs "r.img2" has the sparse name "r.img" as a substring, but the layout carries only the placeholder.
    m = stage(tmp_path, layout(app_file="APPFILE"), name="r.img2")
    assert len(run(tmp_path, m)) == 2


def test_a_staged_image_named_like_the_rewrite_pattern_is_refused(tmp_path):
    m = stage(tmp_path, layout(), name="root.ext4")
    m = Manifest(rootfs=m.rootfs, tegraflash_esp=m.tegraflash_esp, var="images/root.img")
    msg = refusal(tmp_path, m)
    assert "root.img" in msg and "var" in msg


def test_the_staged_rootfs_named_like_its_own_rewrite_pattern_is_not_a_collision(tmp_path):
    m = stage(tmp_path, layout(app_file="rootfs.img", extra=_extra_partition("UDA", "rootfs.img")))
    assert len(run(tmp_path, m)) == 2


@pytest.mark.parametrize("filename", ["APPFILE", "xAPPFILEx", "APPFILE_b"])
def test_appfile_in_a_partition_other_than_app_and_app_b_is_refused(tmp_path, filename):
    m = stage(tmp_path, layout(app_b="8192", app_file="APPFILE", app_b_file="APPFILE_b", extra=_extra_partition("UDA", filename)))
    msg = refusal(tmp_path, m)
    assert "UDA" in msg and "APPFILE" in msg


def test_the_placeholders_in_app_and_app_b_alone_are_not_refused(tmp_path):
    m = stage(tmp_path, layout(app_b="8192", app_file="APPFILE", app_b_file="APPFILE_b"))
    assert len(run(tmp_path, m)) == 2


def test_a_partition_with_no_filename_is_not_refused(tmp_path):
    m = stage(tmp_path, layout(extra='<partition name="UDA" type="data"><size>10</size></partition>\n'), name="root.ext4")
    assert len(run(tmp_path, m)) == 2


# the layouts the recipe ships, with the rootfs name the BSP recipe generates


SHIPPED = Path(__file__).resolve().parents[3] / "recipes-bsp" / "tegra-binaries" / "tegra-storage-layout"
SHIPPED_ROOTFS = "avocado-image-rootfs-avocado-jetson-orin-nano.erofs-lz4"


@pytest.mark.parametrize("layout_name", ["external-flash.xml", "internal-flash-emmc.xml"])
def test_the_shipped_layouts_pass_with_the_shipped_rootfs_name(tmp_path, layout_name):
    # The flash helper fills APPSIZE and ESP_FILE before the layout is staged; the other placeholders stay text.
    xml = (SHIPPED / layout_name).read_text().replace("APPSIZE", "8192").replace("ESP_FILE", "esp.img")
    m = stage(tmp_path, xml, name=SHIPPED_ROOTFS, rootfs=1024, esp=1024)
    assert len(run(tmp_path, m)) == 2


# an absent APP_b is the intent, not an oversight: the limit is APP alone


def test_an_absent_app_b_leaves_app_as_the_limit(tmp_path):
    with_b, without_b = tmp_path / "with", tmp_path / "without"
    with_b.mkdir()
    without_b.mkdir()
    logs_with = run(with_b, stage(with_b, layout(app="8192", app_b="8192")))
    logs_without = run(without_b, stage(without_b, layout(app="8192")))
    assert logs_without == logs_with == ["fit: rootfs 4096 <= APP 8192", "fit: tegraflash_esp 2048 <= esp 4096"]


def test_an_absent_app_b_still_refuses_a_rootfs_larger_than_app(tmp_path):
    m = stage(tmp_path, layout(app="1000"))
    assert "does not fit partition APP (1000 bytes)" in refusal(tmp_path, m)
