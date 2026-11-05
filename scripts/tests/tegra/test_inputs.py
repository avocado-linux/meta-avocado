"""Tests for template loading and flash input validation."""

import json
import os
import shutil

import pytest

from avocado_flash_tegra import FlashError, InputInfo, Problem
from avocado_flash_tegra import inputs


def _entries(tree):
    template = inputs.load_template(tree.images_dir, tree.machine)
    return template, inputs.image_entries(template)


def test_template_name_strips_avocado_prefix():
    assert inputs.template_name("avocado-jetson-orin-nano") == "stone-jetson-orin-nano.json"


def test_template_name_without_prefix_is_kept():
    assert inputs.template_name("other-board") == "stone-other-board.json"


def test_load_template_reads_the_deployed_file(deploy_tree):
    template = inputs.load_template(deploy_tree.images_dir, deploy_tree.machine)
    assert template == json.loads(deploy_tree.template.read_text())


def test_absent_template_names_file_target_and_bringup_sentence(tmp_path):
    with pytest.raises(FlashError) as exc:
        inputs.load_template(tmp_path, "avocado-jetson-orin-nano")
    text = str(exc.value)
    assert "stone-jetson-orin-nano.json" in text
    assert "avocado-stone" in text
    assert "provisioning script" in text
    assert "var, ESP and TOS images" in text
    assert "host tools" in text


def test_image_entries_skips_object_valued_boot(deploy_tree):
    _, entries = _entries(deploy_tree)
    assert "boot" not in entries
    assert entries["rootfs"] == "avocado-image-rootfs-jetson-orin-nano.erofs-lz4"
    assert set(entries) == {
        "rootfs",
        "var",
        "initramfs",
        "tegraflash_initramfs",
        "tegraflash_esp",
        "tegraflash_tos",
        "tegraflash_bsp",
        "tegraflash_engine",
        "tegraflash_tools",
        "tegraflash_carrier_bsp",
    }


def test_require_profile_accepts_nvme_template(deploy_tree):
    template, _ = _entries(deploy_tree)
    inputs.require_profile(template, deploy_tree.machine)


def test_require_profile_refuses_template_without_nvme(deploy_tree):
    template, _ = _entries(deploy_tree)
    del template["provision"]["profiles"]["tegraflash-nvme"]
    with pytest.raises(FlashError) as exc:
        inputs.require_profile(template, deploy_tree.machine)
    assert deploy_tree.machine in str(exc.value)
    assert "tegraflash-nvme" in str(exc.value)


def test_all_present_gives_no_problems(deploy_tree):
    _, entries = _entries(deploy_tree)
    assert inputs.check_images(deploy_tree.images_dir, entries) == []


def test_three_missing_inputs_give_three_problems(deploy_tree):
    template, entries = _entries(deploy_tree)
    (deploy_tree.images_dir / entries["var"]).unlink()
    (deploy_tree.images_dir / entries["tegraflash_esp"]).unlink()
    (deploy_tree.tools_dir / "initrd-flash").unlink()
    (deploy_tree.tools_dir / "placeholder").unlink()
    deploy_tree.tools_dir.rmdir()
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert len(problems) == 3
    by_target = {p.target: p for p in problems}
    assert set(by_target) == {"avocado-image-var", "tegra-espimage", "tegraflash-tools-deploy"}
    assert entries["var"] in by_target["avocado-image-var"].what
    assert entries["tegraflash_esp"] in by_target["tegra-espimage"].what
    assert entries["tegraflash_tools"] in by_target["tegraflash-tools-deploy"].what


def test_zero_byte_image_counts_missing(deploy_tree):
    _, entries = _entries(deploy_tree)
    (deploy_tree.images_dir / entries["rootfs"]).write_bytes(b"")
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == ["avocado-image-rootfs"]
    assert entries["rootfs"] in problems[0].what


def test_missing_esp_problem_carries_build_target(deploy_tree):
    _, entries = _entries(deploy_tree)
    (deploy_tree.images_dir / entries["tegraflash_esp"]).unlink()
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert problems == [Problem(problems[0].what, "tegra-espimage")]


def test_unmapped_key_falls_back_to_avocado_stone():
    problems = inputs.check_images("/nonexistent-dir", {"something_new": "x.bin"})
    assert [p.target for p in problems] == ["avocado-stone"]


def test_all_mapped_build_targets():
    assert inputs.BUILD_TARGETS == {
        "rootfs": "avocado-image-rootfs",
        "var": "avocado-image-var",
        "initramfs": "avocado-image-initramfs",
        "tegraflash_initramfs": "tegra-initrd-flash-initramfs",
        "tegraflash_esp": "tegra-espimage",
        "tegraflash_tos": "tos-optee",
        "tegraflash_bsp": "tegraflash-bsp",
        "tegraflash_engine": "tegraflash-engine",
        "tegraflash_tools": "tegraflash-tools-deploy",
        "tegraflash_carrier_bsp": "tegraflash-bsp",
    }


def test_symlinked_file_and_directory_count_present(deploy_tree, tmp_path):
    _, entries = _entries(deploy_tree)
    real_file = tmp_path / "real.img"
    real_file.write_bytes(b"data")
    link = deploy_tree.images_dir / entries["var"]
    link.unlink()
    os.symlink(real_file, link)
    real_dir = tmp_path / "real-bsp"
    real_dir.mkdir()
    (real_dir / "f").write_text("x")
    dlink = deploy_tree.images_dir / entries["tegraflash_bsp"]
    (dlink / "placeholder").unlink()
    (dlink / "external-flash.xml").unlink()
    dlink.rmdir()
    os.symlink(real_dir, dlink)
    assert inputs.check_images(deploy_tree.images_dir, entries) == []


def test_dangling_symlink_counts_missing(deploy_tree, tmp_path):
    _, entries = _entries(deploy_tree)
    link = deploy_tree.images_dir / entries["var"]
    link.unlink()
    os.symlink(tmp_path / "nowhere", link)
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == ["avocado-image-var"]


def test_file_where_directory_expected_counts_missing(deploy_tree):
    _, entries = _entries(deploy_tree)
    path = deploy_tree.images_dir / entries["tegraflash_carrier_bsp"]
    (path / "placeholder").unlink()
    path.rmdir()
    path.write_bytes(b"not a dir")
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == ["tegraflash-bsp"]


def test_renamed_rootfs_is_looked_up_under_the_new_name(deploy_tree):
    template, _ = _entries(deploy_tree)
    template["storage_devices"]["rootdisk"]["images"]["rootfs"] = "renamed-rootfs.img"
    entries = inputs.image_entries(template)
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert len(problems) == 1
    assert "renamed-rootfs.img" in problems[0].what
    assert problems[0].target == "avocado-image-rootfs"
    (deploy_tree.images_dir / "renamed-rootfs.img").write_bytes(b"x")
    assert inputs.check_images(deploy_tree.images_dir, entries) == []


def test_describe_inputs_sizes_files_and_directories(deploy_tree, tmp_path):
    _, entries = _entries(deploy_tree)
    (deploy_tree.tools_dir / "sub").mkdir()
    (deploy_tree.tools_dir / "sub" / "blob").write_bytes(b"12345")
    real_dir = tmp_path / "linked"
    real_dir.mkdir()
    (real_dir / "a").write_bytes(b"abc")
    (deploy_tree.bsp_dir / "placeholder").unlink()
    (deploy_tree.bsp_dir / "external-flash.xml").unlink()
    deploy_tree.bsp_dir.rmdir()
    os.symlink(real_dir, deploy_tree.bsp_dir)
    infos = {i.key: i for i in inputs.describe_inputs(deploy_tree.images_dir, entries)}
    assert set(infos) == set(entries)
    var = deploy_tree.images_dir / entries["var"]
    assert infos["var"] == InputInfo(
        name=entries["var"], key="var", size=var.stat().st_size, mtime=var.stat().st_mtime
    )
    tools_size = len("#!/bin/sh\nexit 0\n") + len("x\n") + 5
    assert infos["tegraflash_tools"].size == tools_size
    assert infos["tegraflash_bsp"].size == 3


# --- The provisioning engine directory is a required input ---------------

ENGINE = "tegraflash-engine"


def _remove_engine(tree):
    engine = tree.images_dir / ENGINE
    shutil.rmtree(engine)
    return engine


def test_engine_key_is_a_directory_key_with_its_own_build_target():
    assert "tegraflash_engine" in inputs.DIR_KEYS
    assert inputs.BUILD_TARGETS["tegraflash_engine"] == ENGINE


def test_engine_absent_names_the_engine_and_the_stone_target(deploy_tree):
    """Scenario: Engine absent."""
    _, entries = _entries(deploy_tree)
    _remove_engine(deploy_tree)
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == [ENGINE]
    assert ENGINE in problems[0].what
    assert "avocado-stone" in problems[0].what


def test_engine_as_a_plain_file_counts_absent(deploy_tree):
    _, entries = _entries(deploy_tree)
    _remove_engine(deploy_tree).write_bytes(b"not a dir")
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == [ENGINE]


def test_engine_present_passes_and_is_described_as_a_directory_input(deploy_tree):
    """Scenario: Engine present."""
    template, entries = _entries(deploy_tree)
    inputs.require_engine(template, deploy_tree.machine)
    assert inputs.check_images(deploy_tree.images_dir, entries) == []
    infos = {i.key: i for i in inputs.describe_inputs(deploy_tree.images_dir, entries)}
    assert infos["tegraflash_engine"].name == ENGINE


def test_require_engine_refuses_a_template_that_does_not_name_it(deploy_tree):
    """Scenario: Template does not name the engine."""
    template, _ = _entries(deploy_tree)
    del template["storage_devices"]["rootdisk"]["images"]["tegraflash_engine"]
    with pytest.raises(FlashError) as exc:
        inputs.require_engine(template, deploy_tree.machine)
    text = str(exc.value)
    assert "predates the engine" in text
    assert deploy_tree.machine in text
    assert "avocado-stone" in text


def test_require_engine_refuses_a_non_string_engine_entry(deploy_tree):
    template, _ = _entries(deploy_tree)
    template["storage_devices"]["rootdisk"]["images"]["tegraflash_engine"] = {"out": "x"}
    with pytest.raises(FlashError):
        inputs.require_engine(template, deploy_tree.machine)


def test_require_engine_accepts_the_name_the_shim_looks_for(deploy_tree):
    template, _ = _entries(deploy_tree)
    assert template["storage_devices"]["rootdisk"]["images"]["tegraflash_engine"] == ENGINE
    inputs.require_engine(template, deploy_tree.machine)


def test_require_engine_refuses_a_misnamed_engine_directory(deploy_tree):
    """The shim looks for tegraflash-engine in the data directory, whatever the template says."""
    template, _ = _entries(deploy_tree)
    template["storage_devices"]["rootdisk"]["images"]["tegraflash_engine"] = "my-engine"
    with pytest.raises(FlashError) as exc:
        inputs.require_engine(template, deploy_tree.machine)
    assert ENGINE in str(exc.value)
    assert "my-engine" in str(exc.value)


@pytest.mark.parametrize("section", ["storage_devices", "rootdisk", "images"])
@pytest.mark.parametrize("bad", [None, "text", []])
def test_require_engine_refuses_a_template_with_a_malformed_section(deploy_tree, section, bad):
    template, _ = _entries(deploy_tree)
    holder = template if section == "storage_devices" else template["storage_devices"]
    if section == "images":
        holder = template["storage_devices"]["rootdisk"]
    holder[section] = bad
    with pytest.raises(FlashError):
        inputs.require_engine(template, deploy_tree.machine)


def test_engine_directory_without_the_entry_point_counts_missing(deploy_tree):
    _, entries = _entries(deploy_tree)
    (deploy_tree.images_dir / ENGINE / "avocado_tegraflash" / "__main__.py").unlink()
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == [ENGINE]
    assert "avocado_tegraflash/__main__.py" in problems[0].what
    assert "avocado-stone" in problems[0].what


def test_empty_engine_directory_counts_missing(deploy_tree):
    _, entries = _entries(deploy_tree)
    engine = _remove_engine(deploy_tree)
    engine.mkdir()
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == [ENGINE]


def test_engine_entry_point_that_is_a_directory_counts_missing(deploy_tree):
    _, entries = _entries(deploy_tree)
    main = deploy_tree.images_dir / ENGINE / "avocado_tegraflash" / "__main__.py"
    main.unlink()
    main.mkdir()
    problems = inputs.check_images(deploy_tree.images_dir, entries)
    assert [p.target for p in problems] == [ENGINE]


# CLI ordering: each refusal comes before any USB listing.


class _Fatal(Exception):
    pass


class _RecordingRunner:
    def __init__(self):
        self.captured = []
        self.streamed = []

    def capture(self, argv):
        self.captured.append(list(argv))
        return 0, "Bus 001 Device 004: ID 0955:7523 NVIDIA Corp. APX\n"

    def stream(self, invocation, log_path, echo=print):
        self.streamed.append(invocation)
        return 0


def _cli(tree, tmp_path, monkeypatch):
    import shutil

    from avocado_flash_tegra import cli

    monkeypatch.setattr(shutil, "which", lambda name, path=None: f"/stub/{name}")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    deploy = tree.images_dir.parent.parent
    host = cli.Host(
        resolve_deploy_dir=lambda explicit: explicit or deploy,
        resolve_machine=lambda d, explicit: explicit or tree.machine,
        confirm_destructive=lambda *a: None,
        fatal=_Fatal,
    )
    runner = _RecordingRunner()
    argv = ["--deploy", str(deploy), "--workdir", str(tmp_path / "work"), "--dry-run"]
    return cli.main(argv, host, runner), runner


def test_cli_engine_directory_absent_refuses_before_any_usb_action(
    deploy_tree, tmp_path, monkeypatch, capsys
):
    _remove_engine(deploy_tree)
    rc, runner = _cli(deploy_tree, tmp_path, monkeypatch)
    captured = capsys.readouterr()
    assert rc == 1
    assert runner.captured == []
    assert ENGINE in captured.err and "avocado-stone" in captured.err
    assert "inputs: all present" not in captured.out
    assert "pinned:" not in captured.out


def test_cli_template_without_the_engine_entry_refuses_before_any_usb_action(
    deploy_tree, tmp_path, monkeypatch, capsys
):
    data = json.loads(deploy_tree.template.read_text())
    del data["storage_devices"]["rootdisk"]["images"]["tegraflash_engine"]
    deploy_tree.template.write_text(json.dumps(data))
    rc, runner = _cli(deploy_tree, tmp_path, monkeypatch)
    captured = capsys.readouterr()
    assert rc == 1
    assert runner.captured == []
    assert "predates the engine" in captured.err
    assert deploy_tree.template.name in captured.err
    assert "inputs: all present" not in captured.out
    assert "pinned:" not in captured.out


def test_cli_engine_present_lists_it_among_the_inputs(deploy_tree, tmp_path, monkeypatch, capsys):
    rc, runner = _cli(deploy_tree, tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 0
    assert runner.captured == [["lsusb"]]
    assert f"  {ENGINE}  " in out
