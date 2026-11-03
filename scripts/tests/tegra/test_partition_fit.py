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
