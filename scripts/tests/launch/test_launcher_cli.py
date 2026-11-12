"""End to end through scripts/avocado-flash with AVOCADO_FLASH_LAUNCHER=1.

Hermetic: stone, fwup, uuu, dd, bmaptool and sudo are shell stubs in a tmp PATH
dir. Each appends its argv and its parent's name to one log, so the tests assert
the LIST of processes the launcher started. Nothing here touches a device or
runs real sudo.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "avocado-flash"
MACHINE = "avocado-test"
STUBS = ("stone", "fwup", "uuu", "dd", "bmaptool", "sudo")
VAR_BYTES = 8192


class Tree:
    def __init__(self, tmp: Path, profiles=None):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "procs.log"
        self.rec = tmp / "rec"
        self.rec.mkdir()
        self.deploy = tmp / "deploy"
        self.images = self.deploy / "images" / MACHINE
        self.images.mkdir(parents=True)
        (self.images / "var.img").write_bytes(b"v" * VAR_BYTES)
        stone = self.deploy / "stone"
        stone.mkdir()
        (stone / "rootfs.img").write_bytes(b"r")
        profiles = profiles if profiles is not None else {
            "sd": {},
            "uuu-emmc": {"config": {"dry_run": True}},
        }
        manifest = {
            "provision": {"profiles": profiles},
            "storage_devices": {"rootdisk": {"images": {"var": "var.img"}}},
        }
        (stone / "stone-test.json").write_text(json.dumps(manifest))
        self.workdir = tmp / "work"
        for name in STUBS:
            self._stub(name)

    def _stub(self, name):
        path = self.bin / name
        path.write_text(
            "#!/bin/sh\n"
            f'echo "{name} $* | parent=$(cat /proc/$PPID/comm)" >> {self.log}\n'
            f"env > {self.rec}/{name}.env\n"
            f'printf "%s\\n" "$@" > {self.rec}/{name}.argv\n'
            "exit 0\n"
        )
        path.chmod(0o755)

    def started(self):
        if not self.log.exists():
            return []
        return [line.split(" ", 1)[0] for line in self.log.read_text().splitlines()]

    def run(self, *args, launcher="1", extra_env=None):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp)}
        if launcher is not None:
            env["AVOCADO_FLASH_LAUNCHER"] = launcher
        env.update(extra_env or {})
        argv = [
            sys.executable, str(SCRIPT),
            "--deploy", str(self.deploy), "--machine", MACHINE, *args,
        ]
        out = self.tmp / "out.txt"
        with open(out, "w") as fh:
            proc = subprocess.Popen(
                argv, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                rc = proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                if os.getpgid(proc.pid) == proc.pid:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
        return rc, out.read_text()

    def argv(self, name):
        return (self.rec / f"{name}.argv").read_text().splitlines()

    def env(self, name):
        pairs = (l.split("=", 1) for l in (self.rec / f"{name}.env").read_text().splitlines() if "=" in l)
        return dict(pairs)


@pytest.fixture
def tree(tmp_path):
    return Tree(tmp_path)


def test_sd_starts_only_stone_with_absolute_input_and_var_size(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "sd", "/dev/fakedisk")
    assert rc == 0, out
    assert tree.started() == ["stone"]
    argv = tree.argv("stone")
    assert argv[0] == "provision"
    assert argv[1] == "-i"
    assert os.path.isabs(argv[2])
    assert argv[3:] == ["--partition-size", f"var={VAR_BYTES}"]
    env = tree.env("stone")
    assert env["AVOCADO_PROVISION_PROFILE"] == "sd"
    assert env["AVOCADO_PROVISION_DEVICE"] == "/dev/fakedisk"
    assert env["AVOCADO_PROVISION_FORCE"] == "0"
    assert "AVOCADO_PROVISION_DRY_RUN" not in env
    assert "sudo" not in tree.started()


def test_sd_stone_is_started_by_the_python_launcher_not_a_shell_chain(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "sd", "/dev/fakedisk")
    assert rc == 0, out
    (line,) = tree.log.read_text().splitlines()
    assert line.endswith("parent=python3") or "parent=python" in line


def test_sd_passes_task_only_when_given(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "--task", "upgrade", "sd", "/dev/fakedisk")
    assert rc == 0, out
    assert tree.env("stone")["AVOCADO_PROVISION_FWUP_TASK"] == "upgrade"


def test_emmc_maps_to_uuu_emmc_and_starts_only_stone(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "emmc")
    assert rc == 0, out
    assert tree.started() == ["stone"]
    assert tree.env("stone")["AVOCADO_PROVISION_PROFILE"] == "uuu-emmc"


def test_dry_run_on_declared_profile_sets_dry_run(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "--dry-run", "emmc")
    assert rc == 0, out
    assert tree.env("stone")["AVOCADO_PROVISION_DRY_RUN"] == "1"


def test_dry_run_on_undeclared_profile_is_refused_before_stone(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "--dry-run", "sd", "/dev/fakedisk")
    assert rc != 0
    assert "sd" in out
    assert tree.started() == []
    assert not tree.workdir.exists()


def test_missing_profile_is_refused_naming_machine_and_profile(tmp_path):
    t = Tree(tmp_path, profiles={"sd": {}})
    rc, out = t.run("--workdir", str(t.workdir), "emmc")
    assert rc != 0
    assert MACHINE in out and "uuu-emmc" in out
    assert t.started() == []
    assert not t.workdir.exists()


def test_yes_sets_force_and_inherited_force_is_replaced(tree):
    rc, out = tree.run(
        "--workdir", str(tree.workdir), "sd", "/dev/fakedisk",
        extra_env={"AVOCADO_PROVISION_FORCE": "1"},
    )
    assert rc == 0, out
    assert tree.env("stone")["AVOCADO_PROVISION_FORCE"] == "0"
    assert "AVOCADO_PROVISION_FORCE" in out


def test_bmaptool_is_refused_with_no_process_started(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "--backend", "bmaptool", "sd", "/dev/fakedisk")
    assert rc != 0
    assert "bmaptool is no longer offered" in out
    assert tree.started() == []


def test_unwired_media_fail_loudly_not_silently(tree):
    rc, out = tree.run("--workdir", str(tree.workdir), "ums")
    assert rc != 0
    assert "not yet wired" in out
    assert tree.started() == []


def test_two_deploy_trees_still_refused(tmp_path):
    # Resolution stays in avocado-flash: ensure it still refuses with the opt-in on.
    for n in ("build-a", "build-b"):
        (tmp_path / "ws" / n / "build" / "tmp" / "deploy").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "AVOCADO_FLASH_LAUNCHER": "1"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "sd", "/dev/fakedisk"], env=env, cwd=tmp_path / "ws",
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "several build trees" in proc.stderr


@pytest.mark.parametrize("value", [None, "0", "true", ""])
def test_opt_in_unset_or_other_keeps_the_old_path(tree, value):
    # The old sd path refuses a non-block device before writing anything; the
    # launcher would instead have started stone.
    rc, out = tree.run("sd", "/dev/fakedisk", launcher=value)
    assert rc != 0
    assert tree.started() == []
    assert "stone" not in out


def test_nvme_under_opt_in_fails_loudly_and_starts_nothing(tree):
    env = {"PATH": f"{tree.bin}:/usr/bin:/bin", "HOME": str(tree.tmp), "AVOCADO_FLASH_LAUNCHER": "1"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "nvme", "--dry-run"], env=env,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "not yet wired" in proc.stderr
    assert tree.started() == []
