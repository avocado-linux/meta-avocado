"""Partition fit check against the staged layout."""

import time
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
    m = stage(tmp_path, layout(app_b="8192", app_file="rootfs.img", app_b_file="rootfs.img"))
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


# the rename pattern is read by GNU sed as a basic regex: only `.` is special in the names the env reader accepts


@pytest.mark.parametrize(
    "rootfs,colliding",
    [
        ("img+dev.raw", "img+dev.img"),
        ("r(1).raw", "r(1).img"),
        ("rootfs.img", "rootfs_img"),
        ("a.b.ext4", "a.b.img"),
    ],
)
def test_the_rewrite_pattern_is_the_sed_basic_regex_of_the_stem(tmp_path, rootfs, colliding):
    # no ROOTFS_IMAGE line: the env reader would refuse parentheses, and the staged name is used as is
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", colliding)), name=rootfs, env="BOOTDEV=x\n")
    msg = refusal(tmp_path, m)
    assert colliding in msg and "UDA" in msg


def test_only_the_last_extension_is_dropped_from_the_stem(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "a.img")), name="a.b.ext4")
    assert len(run(tmp_path, m)) == 2


def test_regex_metacharacters_in_the_rootfs_name_are_literal_and_cannot_backtrack(tmp_path):
    name = "a+" * 8 + "x.ext4"
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "a" * 60)), name=name, env=f'ROOTFS_IMAGE="{name}"\n')
    started = time.monotonic()
    assert len(run(tmp_path, m)) == 2
    assert time.monotonic() - started < 1.0


def test_a_plus_in_the_rootfs_name_does_not_match_repeated_characters(tmp_path):
    # in a BRE `a+x` is the three characters a, +, x, so "aax.img" is not rewritten
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "aax.img")), name="a+x.ext4", env='ROOTFS_IMAGE="a+x.ext4"\n')
    assert len(run(tmp_path, m)) == 2


def test_a_layout_filename_equal_to_the_rootfs_name_is_the_only_exemption(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "rootfs.img.bak")))
    assert "rootfs.img.bak" in refusal(tmp_path, m)


def test_the_tos_destination_is_part_of_the_collision_check(tmp_path):
    m = stage(tmp_path, layout(), name="root.ext4", env='ROOTFS_IMAGE="root.ext4"\nTOSIMGFILENAME="root.img"\n')
    m = Manifest(rootfs=m.rootfs, tegraflash_esp=m.tegraflash_esp, tegraflash_tos="tos/other.bin")
    msg = refusal(tmp_path, m)
    assert "tegraflash_tos" in msg and "root.img" in msg


# the sed runs over every line of the layout, so a partition with no name, or a name listed twice, is scanned too


def _nameless(filename):
    return f'<partition type="data"><size>10</size><filename>{filename}</filename></partition>\n'


def test_a_nameless_partition_carrying_appfile_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_nameless("APPFILE")))
    msg = refusal(tmp_path, m)
    assert "no name" in msg and "APPFILE" in msg


def test_a_nameless_partition_matching_the_rename_pattern_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_nameless("root.img")), name="root.ext4")
    assert "root.img" in refusal(tmp_path, m)


def test_a_repeated_partition_name_does_not_hide_its_second_filename(tmp_path):
    extra = _extra_partition("UDA", "ok.bin") + _extra_partition("UDA", "APPFILE")
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=extra)))
    assert "UDA" in msg and "APPFILE" in msg


def test_a_second_app_partition_with_a_foreign_filename_is_refused_for_its_filename(tmp_path):
    extra = _extra_partition("APP", "big.ext4")
    assert "big.ext4" in refusal(tmp_path, stage(tmp_path, layout(extra=extra)))


def test_a_second_esp_partition_with_a_foreign_filename_is_refused(tmp_path):
    extra = _extra_partition("esp", "other.img")
    assert "other.img" in refusal(tmp_path, stage(tmp_path, layout(extra=extra)))


# DATAFILE belongs to the data partition and DTB_FILE to the kernel dtb partitions


def test_datafile_in_the_data_partition_passes(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("DATAPART_EXPAND", "DATAFILE")))
    assert len(run(tmp_path, m)) == 2


@pytest.mark.parametrize("name", ["UDA", "esp", "A_kernel-dtb"])
def test_datafile_in_another_partition_is_refused(tmp_path, name):
    extra = _extra_partition("DATAPART_EXPAND", "DATAFILE") + _extra_partition(name + "_x", "DATAFILE")
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=extra)))
    assert "DATAFILE" in msg and name + "_x" in msg


def test_datafile_in_a_nameless_partition_is_refused(tmp_path):
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=_nameless("DATAFILE"))))
    assert "no name" in msg and "DATAFILE" in msg


@pytest.mark.parametrize("name", ["A_kernel-dtb", "B_kernel-dtb", "kernel-dtb"])
def test_dtb_file_in_a_kernel_dtb_partition_passes(tmp_path, name):
    m = stage(tmp_path, layout(extra=_extra_partition(name, "DTB_FILE")))
    assert len(run(tmp_path, m)) == 2


@pytest.mark.parametrize(
    "name", ["UDA", "A_kernel", "RECDTB-NAME", "A_kernel-dtb_x", "recovery-dtb", "foo-dtb", "A_recovery-dtb", "C_kernel-dtb"]
)
def test_dtb_file_in_another_partition_is_refused(tmp_path, name):
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=_extra_partition(name, "DTB_FILE"))))
    assert "DTB_FILE" in msg and name in msg


# The layout this check reads is rewritten by initrd-flash.sh with `s,DTB_FILE,kernel_$DTBFILE,` (no leading
# space); the leading-space sed (`s, DTB_FILE,`) belongs to the flash helper, which reads a different file. So a
# BPFDTB_FILE or a space-prefixed DTB_FILE in this layout is rewritten too, and is refused outside the kernel slots.


@pytest.mark.parametrize("filename", ["BPFDTB_FILE", " DTB_FILE", "x DTB_FILE", "pre_DTB_FILE_post"])
def test_every_spelling_the_substitution_rewrites_is_refused_outside_the_kernel_slots(tmp_path, filename):
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=_extra_partition("A_bpmp-fw-dtb", filename))))
    assert "DTB_FILE" in msg and "A_bpmp-fw-dtb" in msg


def test_dtb_file_in_a_nameless_partition_is_refused(tmp_path):
    msg = refusal(tmp_path, stage(tmp_path, layout(extra=_nameless("DTB_FILE"))))
    assert "no name" in msg and "DTB_FILE" in msg


# a signed layout is rebuilt by the flash from a copy the engine never read


def test_an_oem_signed_layout_is_refused(tmp_path):
    xml = layout().replace('<partition name="esp"', '<partition name="esp" oem_sign="true"')
    msg = refusal(tmp_path, stage(tmp_path, xml))
    assert "oem_sign" in msg


# initrd-flash.sh:805 runs grep -q 'oem_sign="true"': case-sensitive, that exact attribute text, comments included


def _with_esp_attr(attr):
    return layout().replace('<partition name="esp"', f'<partition name="esp" {attr}')


@pytest.mark.parametrize("attr", ['oem_sign="false"', 'OEM_SIGN="true"', 'oem_sign="yes"', 'oem_sign=""', 'oem_sign="TRUE"'])
def test_an_oem_sign_attribute_that_the_flash_does_not_match_is_accepted(tmp_path, attr):
    assert len(run(tmp_path, stage(tmp_path, _with_esp_attr(attr)))) == 2


def test_oem_sign_true_is_refused_even_when_another_partition_says_false(tmp_path):
    xml = _with_esp_attr('oem_sign="false"').replace('<partition name="APP"', '<partition name="APP" oem_sign="true"')
    assert 'oem_sign="true"' in refusal(tmp_path, stage(tmp_path, xml))


def test_oem_sign_true_in_a_comment_is_refused_like_the_flash_greps_it(tmp_path):
    xml = layout(extra='<!-- oem_sign="true" -->')
    assert 'oem_sign="true"' in refusal(tmp_path, stage(tmp_path, xml))


# refusals cite the file and line that set the value, which is .presigning-vars when that file won


def test_a_rootfs_image_set_by_presigning_vars_cites_that_file_and_line(tmp_path):
    m = stage(tmp_path, layout())
    (tmp_path / ".presigning-vars").write_text("A=1\nROOTFS_IMAGE=big.img\n")
    msg = refusal(tmp_path, m)
    assert f"{tmp_path / '.presigning-vars'}:2" in msg and "big.img" in msg


def test_a_rootfs_image_set_by_the_env_file_cites_the_env_file_and_line(tmp_path):
    m = stage(tmp_path, layout(), env='A=1\nROOTFS_IMAGE="big.img"\n')
    assert f"{tmp_path / '.env.initrd-flash'}:2" in refusal(tmp_path, m)


# a size is a decimal or 0x hex number; int(raw, 0) alone also takes 1_0, which nothing downstream reads as ten


@pytest.mark.parametrize("raw", ["1_0", "0x1_0", "010", "-5", "+5", "0b11", "1e3", "٣", "0x", "0X"])
def test_a_size_that_is_not_plain_decimal_or_hex_is_refused(tmp_path, raw):
    m = stage(tmp_path, layout(app=raw), rootfs=5)
    assert f"{raw!r}, not a number" in refusal(tmp_path, m)


@pytest.mark.parametrize("raw,image", [("0x10", 16), ("0X10", 16), ("0xFF", 255), ("0Xff", 255), ("16", 16), ("0", 0), ("  16  ", 16)])
def test_plain_decimal_and_hex_sizes_are_accepted(tmp_path, raw, image):
    m = stage(tmp_path, layout(app=raw), rootfs=image)
    assert run(tmp_path, m)[0] == f"fit: rootfs {image} <= APP {image}"


# the collision message names the file-name form of the pattern, not Python's escaping of it


def test_the_collision_message_prints_the_stem_and_says_what_dot_matches(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "a+b.img")), name="a+b.ext4", env="BOOTDEV=x\n")
    msg = refusal(tmp_path, m)
    assert "matches 'a+b.img'" in msg and "`.` matches any character" in msg
    assert "\\" not in msg


def test_the_staged_image_collision_message_prints_the_stem_too(tmp_path):
    m = stage(tmp_path, layout(), name="a+b.ext4", env="BOOTDEV=x\n")
    m = Manifest(rootfs=m.rootfs, tegraflash_esp=m.tegraflash_esp, var="images/a+b.img")
    msg = refusal(tmp_path, m)
    assert "matches 'a+b.img'" in msg and "\\" not in msg


# the staged names are searched like the layout ones: unanchored, so a name that merely contains the stem collides


def test_a_staged_name_that_contains_the_stem_pattern_is_refused(tmp_path):
    m = stage(tmp_path, layout(), name="rootfs.ext4")
    m = Manifest(rootfs=m.rootfs, tegraflash_esp=m.tegraflash_esp, var="images/xrootfs.imgz")
    msg = refusal(tmp_path, m)
    assert "xrootfs.imgz" in msg and "var" in msg


# a partition that is not a rootfs slot and carries the rootfs name is written the rootfs, and nothing measured it


def test_a_non_slot_partition_named_exactly_like_the_rootfs_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "rootfs.img")))
    msg = refusal(tmp_path, m)
    assert "UDA" in msg and "rootfs.img" in msg and "never checked" in msg


def test_a_non_slot_partition_named_like_a_rootfs_that_the_pattern_misses_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_extra_partition("UDA", "rootfs.ext4")), name="rootfs.ext4")
    assert "UDA" in refusal(tmp_path, m)


def test_a_nameless_partition_named_exactly_like_the_rootfs_is_refused(tmp_path):
    m = stage(tmp_path, layout(extra=_nameless("rootfs.img")))
    assert "no name" in refusal(tmp_path, m)
