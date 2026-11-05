"""Tests for the recording stubs the parity harness puts on PATH."""

from __future__ import annotations

import ast
import json
import os
import sys

import pytest

from parity import runner, stubs

TOOLS = [
    "lsusb",
    "boardctl",
    "adb",
    "fdtget",
    "fdtput",
    "cpp",
    "x86_64-avocadosdk-linux-cpp",
    "mkbootimg",
    "avocado-tegra-bootimg",
    "initrd-flash",
]

STOCK = "usb,nvme,emmc,sd,ufs"
NODE = "/fragment@0/__overlay__/firmware/uefi/variables/gNVIDIATokenSpaceGuid/DefaultBootPriority"


def _lsusb_line(pid: str, desc: str = "NVIDIA Corp. APX") -> str:
    return f"Bus 001 Device 004: ID 0955:{pid} {desc}"


@pytest.fixture
def env(tmp_path):
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "calls.jsonl"
    scenario = tmp_path / "scenario.json"
    scenario.write_text("{}")
    stubs.write_stubs(stub_dir, log, scenario)

    class Env:
        pass

    e = Env()
    e.tmp = tmp_path
    e.stub_dir = stub_dir
    e.log = log
    e.scenario = scenario

    def set_scenario(**kw):
        scenario.write_text(json.dumps(kw))

    def run(tool, *argv, cwd=None, env_extra=None):
        out = tmp_path / "out.txt"
        environ = {"PATH": f"{stub_dir}:{os.environ['PATH']}"}
        environ.update(env_extra or {})
        with out.open("w") as fh:
            rc = runner.run_in_own_session(
                [str(stub_dir / tool), *argv], stdout=fh, cwd=cwd or tmp_path, env=environ, timeout=30
            )
        return rc, out.read_text()

    def lines():
        if not log.exists():
            return []
        return [json.loads(x) for x in log.read_text().splitlines()]

    e.set_scenario = set_scenario
    e.run = run
    e.lines = lines
    return e


def test_all_tools_written_executable_with_shebang(env):
    for tool in TOOLS:
        p = env.stub_dir / tool
        assert p.is_file(), tool
        assert p.stat().st_mode & 0o777 == 0o755, tool
        assert p.read_text().startswith("#!/usr/bin/env python3\n"), tool


def test_stubs_import_only_stdlib(env):
    for tool in TOOLS:
        tree = ast.parse((env.stub_dir / tool).read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] in sys.stdlib_module_names, (tool, n)


@pytest.mark.parametrize("tool", TOOLS)
def test_each_call_records_exactly_one_line(env, tool):
    env.run(tool, "a", "b c")
    recs = env.lines()
    assert len(env.log.read_text().splitlines()) == 1
    assert len(recs) == 1
    assert recs[0]["tool"] == tool
    assert recs[0]["argv"] == ["a", "b c"]


def test_multiple_calls_one_line_each(env):
    for i in range(3):
        env.run("adb", "start-server")
    env.run("mkbootimg")
    assert [r["tool"] for r in env.lines()] == ["adb", "adb", "adb", "mkbootimg"]
    assert len(env.log.read_text().splitlines()) == 4


def test_record_carries_cwd_path_and_env(env, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    env.run(
        "cpp",
        "-x",
        cwd=work,
        env_extra={
            "PYTHONWARNINGS": "ignore::SyntaxWarning",
            "AVOCADO_KERNEL_CMDLINE_EXTRA": "a=1 b=2",
        },
    )
    (rec,) = env.lines()
    assert set(rec) == {
        "tool",
        "argv",
        "cwd",
        "PATH",
        "PYTHONWARNINGS",
        "AVOCADO_KERNEL_CMDLINE_EXTRA",
    }
    assert rec["cwd"] == str(work)
    assert rec["PATH"].startswith(str(env.stub_dir))
    assert rec["PYTHONWARNINGS"] == "ignore::SyntaxWarning"
    assert rec["AVOCADO_KERNEL_CMDLINE_EXTRA"] == "a=1 b=2"


def test_unset_env_recorded_as_null(env):
    env.run("cpp")
    (rec,) = env.lines()
    assert rec["PYTHONWARNINGS"] is None
    assert rec["AVOCADO_KERNEL_CMDLINE_EXTRA"] is None


def test_both_cpp_names_record_their_own_name(env):
    env.run("cpp")
    env.run("x86_64-avocadosdk-linux-cpp")
    assert [r["tool"] for r in env.lines()] == ["cpp", "x86_64-avocadosdk-linux-cpp"]


def test_lsusb_outputs_advance_per_bare_call_and_repeat_last(env):
    env.set_scenario(lsusb=[[], [_lsusb_line("7523")]])
    rc1, out1 = env.run("lsusb", "-d", "0955:")
    rc2, out2 = env.run("lsusb", "-d", "0955:")
    rc3, out3 = env.run("lsusb", "-d", "0955:")
    assert (rc1, out1) == (1, "")
    assert (rc2, out2) == (0, _lsusb_line("7523") + "\n")
    assert (rc3, out3) == (0, _lsusb_line("7523") + "\n")


def test_lsusb_pid_probe_present_exits_zero(env):
    env.set_scenario(lsusb=[[_lsusb_line("7523")]])
    env.run("lsusb", "-d", "0955:")
    rc, out = env.run("lsusb", "-d", "0955:7523")
    assert rc == 0
    assert out == _lsusb_line("7523") + "\n"


def test_lsusb_pid_probe_absent_exits_nonzero(env):
    env.set_scenario(lsusb=[[_lsusb_line("7523")]])
    env.run("lsusb", "-d", "0955:")
    rc, out = env.run("lsusb", "-d", "0955:7018")
    assert rc == 1
    assert out == ""


def test_lsusb_pid_probe_does_not_advance(env):
    env.set_scenario(lsusb=[[], [_lsusb_line("7523")]])
    env.run("lsusb", "-d", "0955:")  # prints output 0 (empty)
    for _ in range(3):
        rc, _out = env.run("lsusb", "-d", "0955:7523")
        assert rc == 1  # still looking at output 0
    rc, out = env.run("lsusb", "-d", "0955:")  # now output 1
    assert rc == 0 and out == _lsusb_line("7523") + "\n"


def test_lsusb_probe_before_any_bare_call_uses_first_output(env):
    env.set_scenario(lsusb=[[_lsusb_line("7019")]])
    rc, _ = env.run("lsusb", "-d", "0955:7019")
    assert rc == 0


def test_lsusb_default_scenario_prints_nothing(env):
    rc, out = env.run("lsusb", "-d", "0955:")
    assert (rc, out) == (1, "")


def test_boardctl_adb_flash_exit_codes(env):
    env.set_scenario(boardctl_rc=3, adb_rc=4, flash_rc=5)
    assert env.run("boardctl", "-t", "x", "recovery")[0] == 3
    assert env.run("adb", "start-server")[0] == 4
    assert env.run("initrd-flash", "--erase-nvme")[0] == 5


def test_default_exit_codes_are_zero(env):
    for tool in ("boardctl", "adb", "mkbootimg", "avocado-tegra-bootimg", "cpp", "initrd-flash"):
        assert env.run(tool)[0] == 0, tool


def test_fdtget_returns_scenario_priority(env, tmp_path):
    env.set_scenario(dtbo_priority="sd,usb")
    rc, out = env.run("fdtget", "-t", "s", str(tmp_path / "L4T.dtbo"), NODE, "data")
    assert (rc, out) == (0, "sd,usb\n")


def test_fdtget_default_priority_is_stock(env, tmp_path):
    rc, out = env.run("fdtget", "-t", "s", str(tmp_path / "L4T.dtbo"), NODE, "data")
    assert (rc, out) == (0, STOCK + "\n")


def test_fdtget_fails_when_dtbo_priority_null(env, tmp_path):
    env.set_scenario(dtbo_priority=None)
    rc, _ = env.run("fdtget", "-t", "s", str(tmp_path / "L4T.dtbo"), NODE, "data")
    assert rc != 0


def test_fdtget_reads_new_value_after_fdtput(env, tmp_path):
    dtbo = str(tmp_path / "L4T.dtbo")
    env.set_scenario(dtbo_priority=STOCK, fdtput_takes=True)
    assert env.run("fdtget", "-t", "s", dtbo, NODE, "data")[1] == STOCK + "\n"
    assert env.run("fdtput", "-t", "s", dtbo, NODE, "data", "sd,usb,nvme,emmc,ufs")[0] == 0
    rc, out = env.run("fdtget", "-t", "s", dtbo, NODE, "data")
    assert (rc, out) == (0, "sd,usb,nvme,emmc,ufs\n")


def test_fdtput_store_is_per_dtbo(env, tmp_path):
    a, b = str(tmp_path / "a.dtbo"), str(tmp_path / "b.dtbo")
    env.run("fdtput", "-t", "s", a, NODE, "data", "changed")
    assert env.run("fdtget", "-t", "s", a, NODE, "data")[1] == "changed\n"
    assert env.run("fdtget", "-t", "s", b, NODE, "data")[1] == STOCK + "\n"


def test_fdtput_not_taking_leaves_old_value(env, tmp_path):
    dtbo = str(tmp_path / "L4T.dtbo")
    env.set_scenario(dtbo_priority=STOCK, fdtput_takes=False)
    assert env.run("fdtput", "-t", "s", dtbo, NODE, "data", "sd")[0] == 0
    assert env.run("fdtget", "-t", "s", dtbo, NODE, "data")[1] == STOCK + "\n"


def test_stub_calls_in_scenario_keep_one_line_each(env, tmp_path):
    dtbo = str(tmp_path / "L4T.dtbo")
    env.run("fdtget", "-t", "s", dtbo, NODE, "data")
    env.run("fdtput", "-t", "s", dtbo, NODE, "data", "x")
    env.run("fdtget", "-t", "s", dtbo, NODE, "data")
    env.run("lsusb", "-d", "0955:")
    env.run("lsusb", "-d", "0955:7523")
    assert len(env.log.read_text().splitlines()) == 5
