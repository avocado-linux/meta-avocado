"""The pre-flash check that each image fits its partition in the deployed layout."""

import json
import os
import pathlib
import shutil

import pytest

from avocado_flash_tegra import cli, inputs, prereqs

BOARD = "Bus 001 Device 004: ID 0955:7523 NVIDIA Corp. APX"


class FakeFatal(Exception):
    pass


class FakeRunner:
    def __init__(self):
        self.captured = []

    def capture(self, argv):
        self.captured.append(list(argv))
        return 0, f"{BOARD}\n"


def make_host(tree):
    deploy = tree.images_dir.parent.parent
    return cli.Host(
        resolve_deploy_dir=lambda explicit: explicit or deploy,
        resolve_machine=lambda d, explicit: explicit or tree.machine,
        confirm_destructive=lambda *a: None,
        fatal=FakeFatal,
    )

REAL_LAYOUT = pathlib.Path(
    "/var/tmp/claude-code/peridio/avocado-flash-nvme-rcm/deploy/images/"
    "avocado-jetson-orin-nano/tegraflash-bsp/external-flash.xml"
)
ROOTFS_BYTES = 2051383296
APP_BYTES = 268435456


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, path=None: f"/stub/{name}")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)


@pytest.fixture
def template(deploy_tree):
    return json.loads(deploy_tree.template.read_text())


def _entries(template):
    return inputs.image_entries(template)


def _set_layout(tree, xml):
    (tree.bsp_dir / "external-flash.xml").write_text(xml)


def _size_rootfs(tree, template, size):
    path = tree.images_dir / _entries(template)["rootfs"]
    path.unlink()
    with open(path, "wb") as fh:
        os.truncate(fh.fileno(), size)


def _check(tree, template):
    return prereqs.check_partition_fit(tree.images_dir, template, _entries(template))


def test_the_observed_failure_names_both_sizes_and_the_build_target(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, make_layout({"esp": 67108864, "APP": APP_BYTES}))
    _size_rootfs(deploy_tree, template, ROOTFS_BYTES)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    p = problems[0]
    assert str(ROOTFS_BYTES) in p.what
    assert str(APP_BYTES) in p.what
    assert "APP" in p.what
    assert "ROOTFSPART_SIZE_DEFAULT" in p.what
    assert p.target == "tegraflash-bsp"


def test_equal_size_fits_and_one_byte_over_refuses(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, make_layout({"esp": 67108864, "APP": APP_BYTES}))
    _size_rootfs(deploy_tree, template, APP_BYTES)
    assert _check(deploy_tree, template) == []
    _size_rootfs(deploy_tree, template, APP_BYTES + 1)
    assert len(_check(deploy_tree, template)) == 1


def test_esp_over_its_partition_refuses(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, make_layout({"esp": 4, "APP": APP_BYTES}))
    (deploy_tree.images_dir / _entries(template)["tegraflash_esp"]).write_bytes(b"12345")
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "esp" in problems[0].what
    assert "5 bytes" in problems[0].what and "4 bytes" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_symlinked_image_is_measured_through_the_link(deploy_tree, template, make_layout, tmp_path):
    _set_layout(deploy_tree, make_layout({"esp": 67108864, "APP": APP_BYTES}))
    real = tmp_path / "real.erofs"
    with open(real, "wb") as fh:
        os.truncate(fh.fileno(), ROOTFS_BYTES)
    link = deploy_tree.images_dir / _entries(template)["rootfs"]
    link.unlink()
    link.symlink_to(real)
    assert len(_check(deploy_tree, template)) == 1


def test_missing_layout_is_a_problem_naming_the_bsp(deploy_tree, template):
    (deploy_tree.bsp_dir / "external-flash.xml").unlink()
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "cannot be verified" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_layout_falls_back_to_the_in_file(deploy_tree, template, make_layout):
    (deploy_tree.bsp_dir / "external-flash.xml").unlink()
    (deploy_tree.bsp_dir / "external-flash.xml.in").write_text(
        make_layout({"esp": 67108864, "APP": APP_BYTES})
    )
    assert _check(deploy_tree, template) == []


def test_unparseable_layout_is_a_problem(deploy_tree, template):
    _set_layout(deploy_tree, "<partition_layout><oops")
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "cannot be verified" in problems[0].what


def test_layout_with_a_doctype_and_entity_is_refused(deploy_tree, template, make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES})
    _set_layout(deploy_tree, '<!DOCTYPE x [<!ENTITY a "aaaa">]>\n' + valid)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "DOCTYPE or entity declaration" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_billion_laughs_layout_is_refused_without_expansion(deploy_tree, template, make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES})
    bomb = '<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
    prev = "a"
    for i in range(9):
        cur = f"b{i}"
        bomb += f'<!ENTITY {cur} "' + f"&{prev};" * 10 + '">'
        prev = cur
    bomb += "]>\n"
    _set_layout(deploy_tree, bomb + valid)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "DOCTYPE or entity declaration" in problems[0].what


def test_layout_over_the_size_cap_is_refused(deploy_tree, template, make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES})
    padding = "<!--" + "x" * (prereqs.MAX_LAYOUT_BYTES + 1) + "-->"
    _set_layout(deploy_tree, valid + padding)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "larger than" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_non_numeric_size_is_a_refusal(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, make_layout({"esp": 67108864, "APP": "ROOTFSPART_SIZE"}))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "APP" in problems[0].what
    assert "cannot be verified" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_absent_partition_is_a_problem(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, make_layout({"esp": 67108864}))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "APP" in problems[0].what
    assert "absent" in problems[0].what


def test_cli_reports_the_fit_problem_in_the_single_refusal(deploy_tree, tmp_path, capsys, make_layout, monkeypatch):
    _set_layout(deploy_tree, make_layout({"esp": 67108864, "APP": APP_BYTES}))
    _size_rootfs(deploy_tree, json.loads(deploy_tree.template.read_text()), ROOTFS_BYTES)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None if name == "jq" else f"/stub/{name}")
    runner = FakeRunner()
    argv = ["--deploy", str(deploy_tree.images_dir.parent.parent), "--workdir", str(tmp_path / "w"), "--dry-run"]
    rc = cli.main(argv, make_host(deploy_tree), runner)
    err = capsys.readouterr().err
    assert rc == 1
    assert runner.captured == []
    assert "does not fit partition APP" in err
    assert "jq" in err


def test_cli_dry_run_prints_a_fit_line_per_checked_pair(deploy_tree, tmp_path, capsys):
    argv = ["--deploy", str(deploy_tree.images_dir.parent.parent), "--workdir", str(tmp_path / "w"), "--dry-run"]
    rc = cli.main(argv, make_host(deploy_tree), FakeRunner())
    out = capsys.readouterr().out
    assert rc == 0
    assert "fit: rootfs" in out and "<= APP 268435456" in out
    assert "fit: tegraflash_esp" in out and "<= esp 67108864" in out
    assert out.index("fit: rootfs") < out.index("pinned:")


@pytest.mark.skipif(not REAL_LAYOUT.is_file(), reason="no deployed layout on this host")
def test_real_layout_parses_and_has_a_numeric_app_size():
    sizes, error = prereqs.parse_partition_sizes(REAL_LAYOUT)
    assert error is None
    assert isinstance(sizes["APP"], int) and sizes["APP"] > 0
    assert isinstance(sizes["esp"], int)


# ---- the layout must be plain UTF-8/ASCII before the entity search means anything ----


def _entity_layout(make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES})
    return '<!DOCTYPE x [<!ENTITY a "aaaa">]>\n' + valid


def _write_bytes(tree, data, name="external-flash.xml"):
    (tree.bsp_dir / name).write_bytes(data)


@pytest.mark.parametrize(
    "label,encode",
    [
        ("utf-16 with BOM", lambda s: s.encode("utf-16")),
        ("utf-16-le without BOM", lambda s: s.encode("utf-16-le")),
        ("utf-16-be without BOM", lambda s: s.encode("utf-16-be")),
        ("utf-32 with BOM", lambda s: s.encode("utf-32")),
        ("utf-32-le without BOM", lambda s: s.encode("utf-32-le")),
    ],
)
def test_a_non_utf8_layout_with_an_entity_is_refused(deploy_tree, template, make_layout, label, encode):
    _write_bytes(deploy_tree, encode(_entity_layout(make_layout)))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1, label
    assert "UTF-8" in problems[0].what, label
    assert problems[0].target == "tegraflash-bsp"


def test_a_clean_utf16_layout_is_refused_too(deploy_tree, template, make_layout):
    _write_bytes(deploy_tree, make_layout({"esp": 67108864, "APP": APP_BYTES}).encode("utf-16"))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1 and "UTF-8" in problems[0].what


def test_a_layout_declaring_latin1_is_refused(deploy_tree, template, make_layout):
    xml = make_layout({"esp": 67108864, "APP": APP_BYTES}).replace(
        '<?xml version="1.0"?>', "<?xml version='1.0' encoding='ISO-8859-1'?>"
    )
    _set_layout(deploy_tree, xml)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "ISO-8859-1" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


@pytest.mark.parametrize("enc", ["UTF-8", "utf-8", "US-ASCII"])
def test_a_utf8_or_ascii_declaration_is_accepted(deploy_tree, template, make_layout, enc):
    xml = make_layout({"esp": 67108864, "APP": APP_BYTES}).replace(
        '<?xml version="1.0"?>', f'<?xml version="1.0" encoding="{enc}"?>'
    )
    _set_layout(deploy_tree, xml)
    assert _check(deploy_tree, template) == []


def test_invalid_utf8_bytes_are_refused(deploy_tree, template, make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES}).encode()
    _write_bytes(deploy_tree, valid.replace(b"<?xml", b"\xff<?xml"))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1 and "UTF-8" in problems[0].what


def test_a_mixed_case_doctype_in_utf8_is_still_refused(deploy_tree, template, make_layout):
    valid = make_layout({"esp": 67108864, "APP": APP_BYTES})
    _set_layout(deploy_tree, '<!DocType x [<!EnTiTy a "aaaa">]>\n' + valid)
    problems = _check(deploy_tree, template)
    assert len(problems) == 1 and "DOCTYPE or entity declaration" in problems[0].what


# ---- which layout file counts: the one the provisioning script reads ----


def _write_layout(tree, name, sizes, make_layout):
    (tree.bsp_dir / name).write_text(make_layout(sizes))


def test_an_oversized_image_is_judged_against_the_in_file(deploy_tree, template, make_layout):
    _write_layout(deploy_tree, "external-flash.xml", {"esp": 67108864, "APP": APP_BYTES}, make_layout)
    _write_layout(deploy_tree, "external-flash.xml.in", {"esp": 67108864, "APP": APP_BYTES // 2}, make_layout)
    _size_rootfs(deploy_tree, template, APP_BYTES)
    problems = _check(deploy_tree, template)
    assert any("does not fit partition APP" in p.what and str(APP_BYTES // 2) in p.what for p in problems)


def test_disagreeing_layouts_are_a_problem(deploy_tree, template, make_layout):
    _write_layout(deploy_tree, "external-flash.xml", {"esp": 67108864, "APP": APP_BYTES * 2}, make_layout)
    _write_layout(deploy_tree, "external-flash.xml.in", {"esp": 67108864, "APP": APP_BYTES}, make_layout)
    problems = _check(deploy_tree, template)
    assert any("disagree" in p.what and "APP" in p.what for p in problems)
    assert all(p.target == "tegraflash-bsp" for p in problems)


def test_agreeing_layouts_are_clean(deploy_tree, template, make_layout):
    for name in ("external-flash.xml", "external-flash.xml.in"):
        _write_layout(deploy_tree, name, {"esp": 67108864, "APP": APP_BYTES}, make_layout)
    assert _check(deploy_tree, template) == []


def test_the_xml_file_is_used_when_the_in_file_is_absent(deploy_tree, template, make_layout):
    _write_layout(deploy_tree, "external-flash.xml", {"esp": 4, "APP": APP_BYTES}, make_layout)
    (deploy_tree.images_dir / _entries(template)["tegraflash_esp"]).write_bytes(b"12345")
    problems = _check(deploy_tree, template)
    assert len(problems) == 1 and "esp" in problems[0].what


# ---- a checked partition name must be unambiguous ----


def _two_devices(app_first, app_second):
    return (
        '<?xml version="1.0"?>\n<partition_layout version="01.00.0000">\n'
        '<device type="external" instance="0">\n'
        f'<partition name="APP" type="data"><size> {app_first} </size></partition>\n'
        '<partition name="esp" type="data"><size> 67108864 </size></partition>\n'
        "</device>\n"
        '<device type="internal" instance="3">\n'
        f'<partition name="APP" type="data"><size> {app_second} </size></partition>\n'
        "</device>\n</partition_layout>\n"
    )


def test_a_checked_name_listed_twice_is_ambiguous_and_refused(deploy_tree, template):
    _set_layout(deploy_tree, _two_devices(APP_BYTES, 1))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1
    assert "APP" in problems[0].what and "more than once" in problems[0].what
    assert problems[0].target == "tegraflash-bsp"


def test_a_duplicate_with_equal_sizes_is_refused_too(deploy_tree, template):
    _set_layout(deploy_tree, _two_devices(APP_BYTES, APP_BYTES))
    problems = _check(deploy_tree, template)
    assert len(problems) == 1 and "more than once" in problems[0].what


def test_an_unchecked_duplicate_name_is_ignored(deploy_tree, template, make_layout):
    xml = make_layout({"esp": 67108864, "APP": APP_BYTES}).replace(
        "</device>",
        '<partition name="other" type="data"><size> 1 </size></partition>'
        '<partition name="other" type="data"><size> 2 </size></partition></device>',
    )
    _set_layout(deploy_tree, xml)
    assert _check(deploy_tree, template) == []


@pytest.mark.skipif(not REAL_LAYOUT.is_file(), reason="no deployed layout on this host")
def test_real_layout_lists_each_checked_name_exactly_once_and_both_files_agree():
    for name in ("external-flash.xml", "external-flash.xml.in"):
        path = REAL_LAYOUT.with_name(name)
        if not path.is_file():
            continue
        sizes, error = prereqs.parse_partition_sizes(path)
        assert error is None, name
        for _key, part in prereqs.FIT_PAIRS:
            assert isinstance(sizes[part], int), (name, part)


def test_a_duplicate_against_a_single_listing_prints_a_word_not_an_object(deploy_tree, template, make_layout):
    _set_layout(deploy_tree, _two_devices(APP_BYTES, APP_BYTES))
    _write_layout(deploy_tree, "external-flash.xml.in", {"esp": 67108864, "APP": APP_BYTES}, make_layout)
    problems = _check(deploy_tree, template)
    disagree = [p for p in problems if "disagree" in p.what]
    assert disagree
    for p in disagree:
        assert "object at 0x" not in p.what
        assert "listed more than once" in p.what
