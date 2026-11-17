"""Tests for the parity runner: oracle and engine on the same fixture."""

import shutil
from pathlib import Path

import pytest

from parity import cases, runner

ENGINE_PKG = runner.ENGINE_ROOT / "avocado_tegraflash"


def _case(variant="base", stem="stone-jetson-orin-nano", profile=None):
    # Variant cases hang off a manifest's first profile; the base case is picked
    # on the NVMe profile.
    profile = profile or ("tegraflash-nvme" if variant == "base" else "tegraflash")
    found = [
        c
        for c in cases.all_cases()
        if c.manifest.stem == stem and c.profile == profile and c.id.endswith("/" + variant)
    ]
    assert len(found) == 1
    return found[0]


def _flash(calls):
    return [c for c in calls if c["tool"] == "initrd-flash"]


def test_oracle_records_one_erase_nvme_flash_call(tmp_path):
    status, calls, *_ = runner.run_oracle(_case(), tmp_path / "w1")
    assert status == 0
    assert [c["argv"] for c in _flash(calls)] == [["--erase-nvme"]]


def test_engine_records_one_erase_nvme_flash_call(tmp_path):
    status, calls, *_ = runner.run_engine(_case(), tmp_path / "w2")
    assert status == 0
    assert [c["argv"] for c in _flash(calls)] == [["--erase-nvme"]]


def test_engine_snapshot_lists_the_staged_work_directory(tmp_path):
    _s, _c, snap, *_ = runner.run_engine(_case(), tmp_path / "w2")
    assert "flashvars" in snap


def test_engine_root_selects_the_package_that_runs(tmp_path):
    copy_root = tmp_path / "copy"
    shutil.copytree(ENGINE_PKG, copy_root / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    flash_py = copy_root / "avocado_tegraflash" / "flash.py"
    src = flash_py.read_text()
    old = 'found.add("--erase-nvme")'
    assert src.count(old) == 1
    flash_py.write_text(src.replace(old, 'found.add("--mutated-nvme")'))

    _s, mutated, *_ = runner.run_engine(_case(), tmp_path / "wm", engine_root=copy_root)
    _s, default, *_ = runner.run_engine(_case(), tmp_path / "wd")
    assert [c["argv"] for c in _flash(mutated)] == [["--mutated-nvme"]]
    assert [c["argv"] for c in _flash(default)] == [["--erase-nvme"]]


def test_oracle_without_jq_raises_instead_of_returning(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(runner.OracleUnavailable):
        runner.run_oracle(_case(), tmp_path / "w1")


def test_oracle_nonzero_exit_is_returned_not_raised(tmp_path):
    status, calls, *_ = runner.run_oracle(_case("flash-exit-7"), tmp_path / "w1")
    assert status == 7
    assert len(_flash(calls)) == 1


def test_engine_nonzero_exit_is_returned_not_raised(tmp_path):
    status, *_ = runner.run_engine(_case("flash-exit-7"), tmp_path / "w2")
    assert status == 7


def test_adb_warmup_home_stays_under_the_workdir(tmp_path):
    w = tmp_path / "w1"
    runner.run_oracle(_case(), w)
    env = runner.build_env(_case(), runner.setup(_case(), tmp_path / "w3"))
    assert Path(env["HOME"]).resolve().is_relative_to((tmp_path / "w3").resolve())
    assert "sleep" not in {c["tool"] for c in runner.read_calls(w / "calls.jsonl")}


def test_environment_is_explicit_and_drops_host_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDCTL_TARGET", "host-leak")
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    env = runner.build_env(_case(), runner.setup(_case(), tmp_path / "w"))
    assert "BOARDCTL_TARGET" not in env
    assert "PYTHONWARNINGS" not in env


def test_kernel_image_is_passed_when_the_tree_has_one(tmp_path):
    env = runner.build_env(_case(), runner.setup(_case(), tmp_path / "w"))
    assert env["AVOCADO_PROVISION_KERNEL_IMAGE"].endswith("kernel/Image")


def test_no_kernel_case_sets_no_kernel_image(tmp_path):
    case = _case("no-kernel")
    env = runner.build_env(case, runner.setup(case, tmp_path / "w"))
    assert "AVOCADO_PROVISION_KERNEL_IMAGE" not in env


def test_snapshot_of_a_missing_work_directory_is_empty(tmp_path):
    assert runner.snapshot_of(tmp_path / "absent", []) == {}


def test_unknown_tree_keyword_is_reported(tmp_path):
    case = cases.Case(
        id="x", manifest=_case().manifest, profile="tegraflash-nvme", tree={"bogus": 1}
    )
    with pytest.raises(ValueError, match="bogus"):
        runner.setup(case, tmp_path / "w")


def test_runner_source_starts_no_shell():
    src = Path(runner.__file__).read_text()
    assert "shell=True" not in src
    assert "os.system" not in src


def test_path_is_the_stub_directory_plus_the_allowlist_links_only(tmp_path):
    s = runner.setup(_case(), tmp_path / "w")
    stub_dir, hostbin = runner.build_env(_case(), s)["PATH"].split(":")
    assert (stub_dir, hostbin) == (str(s.tree.stub_dir), str(tmp_path / "w" / "hostbin"))
    linked = {p.name for p in Path(hostbin).iterdir()}
    assert linked <= set(runner.HOST_TOOLS)
    assert {"bash", "jq", "sed"} <= linked
    assert linked.isdisjoint({p.name for p in Path(stub_dir).iterdir() if p.name != "sleep"})


def _fake_oracle(tmp_path, monkeypatch, body):
    script = tmp_path / "fake-oracle.sh"
    script.write_text("#!/bin/bash\n" + body)
    monkeypatch.setattr(runner, "ORACLE", script)


def test_oracle_starting_an_unlisted_program_is_reported(tmp_path, monkeypatch):
    _fake_oracle(tmp_path, monkeypatch, "nosuchtool --flag\nexit 0\n")
    result = runner.run_oracle(_case(), tmp_path / "w")
    assert result.unstubbed == ("nosuchtool",)


def test_engine_starting_an_unlisted_program_is_reported(tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(ENGINE_PKG, root / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = root / "avocado_tegraflash" / "bootpriority.py"
    src = target.read_text()
    old = '["fdtget", "-t", "s", str(dtbo), NODE, "data"]'
    assert src.count(old) == 1
    target.write_text(src.replace(old, '["nosuchtool", "-t", "s", str(dtbo), NODE, "data"]'))
    result = runner.run_engine(_case(), tmp_path / "w", engine_root=root)
    assert result.unstubbed == ("nosuchtool",)


def test_engine_starting_an_absolute_path_outside_the_stub_directory_is_reported(tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(ENGINE_PKG, root / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = root / "avocado_tegraflash" / "bootpriority.py"
    src = target.read_text()
    old = '["fdtget", "-t", "s", str(dtbo), NODE, "data"]'
    assert src.count(old) == 1
    target.write_text(src.replace(old, '["/usr/bin/true", "-t", "s", str(dtbo), NODE, "data"]'))
    result = runner.run_engine(_case(), tmp_path / "w", engine_root=root)
    assert result.unstubbed == ("/usr/bin/true",)


def test_a_clean_engine_run_reports_nothing_unstubbed_and_nothing_changed(tmp_path):
    result = runner.run_engine(_case(), tmp_path / "w")
    assert (result.unstubbed, result.outside_changes) == ((), ())


def test_a_write_to_the_data_directory_and_to_the_sentinel_is_reported(tmp_path, monkeypatch):
    body = (
        'echo extra >> "$AVOCADO_STONE_DATA_DIR/manifest.json"\n'
        'echo extra >> "$AVOCADO_STONE_DATA_DIR/../outside/sentinel.txt"\n'
        'echo extra > "$AVOCADO_STONE_DATA_DIR/../outside/new.txt"\n'
        'echo extra > "$AVOCADO_STONE_BUILD_DIR/stray.txt"\n'
        "exit 0\n"
    )
    _fake_oracle(tmp_path, monkeypatch, body)
    changes = "\n".join(runner.run_oracle(_case(), tmp_path / "w").outside_changes)
    for path in ("data/manifest.json", "outside/sentinel.txt", "outside/new.txt", "build/stray.txt"):
        assert path in changes, changes


def test_a_write_inside_the_work_directory_is_not_an_outside_change(tmp_path, monkeypatch):
    body = 'mkdir -p "$AVOCADO_STONE_BUILD_DIR/tegraflash"\necho x > "$AVOCADO_STONE_BUILD_DIR/tegraflash/f"\nexit 0\n'
    _fake_oracle(tmp_path, monkeypatch, body)
    assert runner.run_oracle(_case(), tmp_path / "w").outside_changes == ()
