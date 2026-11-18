"""nvme and ums through the launcher (AVOCADO_FLASH_LAUNCHER=1).

Hermetic: stone, sudo, lsusb and the Jetson host tools are shell stubs in a tmp
PATH dir that append to one process log. Nothing here touches a board, a serial
console, USB, or real sudo. ums runs in process with a fake console driver.
"""

import os
import subprocess
import sys
import time

import pytest

from avocado_flash_launch import cli
from avocado_flash_launch.envmap import LauncherError
from test_launcher_cli import MACHINE, SCRIPT, Tree

NEEDS_USER = pytest.mark.skipif(os.geteuid() == 0, reason="the sudo path is only taken by a non-root user")

SUDO_STUB = (
    "#!/bin/sh\n"
    'echo "sudo $* | parent=x" >> {log}\n'
    '[ -e {rec}/sudo.argv ] || printf "%s\\n" "$@" > {rec}/sudo.argv\n'
    'exec "$@"\n'
)


class JTree(Tree):
    def __init__(self, tmp, profiles=None):
        super().__init__(
            tmp,
            profiles=profiles
            if profiles is not None
            else {
                "tegraflash-nvme": {"config": {"dry_run": True}},
                "tegraflash-sd": {"config": {"dry_run": True}},
                "ums": {"config": {"dry_run": True}},
            },
        )
        (self.images / "Image").write_bytes(b"k")
        old = time.time() - 3600  # the stone input must not look older than the build output
        os.utime(self.images / "Image", (old, old))
        for name in ("fdtget", "fdtput", "cpp"):
            self._quiet(name)
        # python3 only has to answer the version probe; it must not log as a started process.
        (self.bin / "python3").write_text("#!/bin/sh\necho 3 12\n")
        (self.bin / "python3").chmod(0o755)
        self._stub("lsusb")
        self.set_sudo()

    def _quiet(self, name):
        (self.bin / name).write_text("#!/bin/sh\nexit 0\n")
        (self.bin / name).chmod(0o755)

    def set_sudo(self):
        (self.bin / "sudo").write_text(SUDO_STUB.format(log=self.log, rec=self.rec))
        (self.bin / "sudo").chmod(0o755)

    def set_stone(self, body):
        path = self.bin / "stone"
        path.write_text(
            "#!/bin/sh\n"
            f'echo "stone $*" >> {self.log}\n'
            f"env > {self.rec}/stone.env\n"
            f'printf "%s\\n" "$@" > {self.rec}/stone.argv\n' + body
        )
        path.chmod(0o755)

    def nvme(self, *args, launcher="1", path=None):
        env = {"PATH": path or f"{self.bin}:/usr/bin:/bin", "HOME": str(self.tmp)}
        if launcher is not None:
            env["AVOCADO_FLASH_LAUNCHER"] = launcher
        argv = [sys.executable, str(SCRIPT), "nvme", "--deploy", str(self.deploy), "--machine", MACHINE, *args]
        return self._spawn(argv, env)

    def _spawn(self, argv, env):
        out = self.tmp / "out.txt"
        with open(out, "w") as fh:
            proc = subprocess.Popen(
                argv, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            rc = proc.wait(timeout=60)
        return rc, out.read_text()

    def nosudo_path(self):
        bare = self.tmp / "bin-nosudo"
        bare.mkdir()
        for entry in self.bin.iterdir():
            if entry.name != "sudo":
                (bare / entry.name).symlink_to(entry)
        return str(bare)


@pytest.fixture
def jt(tmp_path):
    return JTree(tmp_path)


def test_nvme_not_first_is_refused_before_any_usb_action(jt):
    env = {"PATH": f"{jt.bin}:/usr/bin:/bin", "HOME": str(jt.tmp), "AVOCADO_FLASH_LAUNCHER": "1"}
    rc, out = jt._spawn([sys.executable, str(SCRIPT), "-m", MACHINE, "nvme"], env)
    assert rc != 0
    assert "nvme must be the first argument" in out
    assert jt.started() == []


@NEEDS_USER
def test_real_nvme_without_root_or_sudo_refuses_before_listing_usb(jt):
    rc, out = jt.nvme("--workdir", str(jt.workdir), path=jt.nosudo_path())
    assert rc != 0
    assert "needs root" in out
    assert "lsusb" not in jt.started()
    assert jt.started() == []
    assert not jt.workdir.exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--task", "upgrade"],
        ["--backend", "uuu"],
        ["--stale-ok"],
        ["--port", "/dev/ttyACM0"],
        ["/dev/sdb"],
        ["--boot-media", "usb"],
    ],
)
def test_nvme_refuses_foreign_options_and_a_device_before_any_process(jt, extra):
    rc, out = jt.nvme(*extra, "--workdir", str(jt.workdir))
    assert rc != 0
    assert "nvme" in out
    assert jt.started() == []
    assert not jt.workdir.exists()


@NEEDS_USER
def test_real_nvme_runs_stone_whole_under_sudo_and_prints_the_next_steps(jt):
    rc, out = jt.nvme(
        "--workdir", str(jt.workdir), "--rcm-id", "0955:7523", "--kernel-cmdline-extra", "systemd.mask=x.service",
    )
    assert rc == 0, out
    assert jt.started()[:2] == ["sudo", "stone"]
    assert "lsusb" not in jt.started()
    sudo_argv = jt.argv("sudo")
    assert sudo_argv[0] == "env"
    assert str(jt.bin / "stone") in sudo_argv
    env = jt.env("stone")
    assert env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-nvme"
    assert env["AVOCADO_PROVISION_RCM_ID"] == "0955:7523"
    assert env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == "systemd.mask=x.service"
    assert "AVOCADO_PROVISION_DRY_RUN" not in env
    assert "recovery jumper" in out and "power-cycle" in out
    assert "work directory" in out
    assert list(jt.workdir.iterdir()) == []  # the scratch is gone, the named parent is never deleted


def test_nvme_dry_run_runs_stone_as_the_user_with_dry_run_set(jt):
    rc, out = jt.nvme("--dry-run", "--workdir", str(jt.workdir))
    assert rc == 0, out
    assert jt.started() == ["stone"]
    env = jt.env("stone")
    assert env["AVOCADO_PROVISION_DRY_RUN"] == "1"
    assert env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-nvme"
    assert "recovery jumper" not in out


@NEEDS_USER
def test_failed_nvme_run_keeps_the_work_directory_and_warns_mid_write(jt):
    jt.set_stone("exit 3\n")
    rc, out = jt.nvme("--workdir", str(jt.workdir))
    assert rc == 3, out
    (kept,) = list(jt.workdir.iterdir())
    assert "mid-write" in out
    assert str(kept) in out
    assert "recovery jumper" not in out


@NEEDS_USER
def test_interrupted_nvme_run_exits_130_and_keeps_the_work_directory(jt):
    # stone signals the launcher that started it, then keeps running: the launcher must wait.
    jt.set_stone("kill -INT $PPID\nsleep 1\nexit 0\n")
    rc, out = jt.nvme("--workdir", str(jt.workdir))
    assert rc == 130, out
    (kept,) = list(jt.workdir.iterdir())
    assert "mid-write" in out
    assert str(kept) in out


def test_nvme_options_reach_the_launcher_before_the_shared_parser(jt):
    # The shared parser has no --rcm-id and no tegraflash-sd boot medium.
    rc, out = jt.nvme("--dry-run", "--rcm-id", "0955:7523", "--boot-media", "sd", "--workdir", str(jt.workdir))
    assert rc == 0, out
    env = jt.env("stone")
    assert env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-sd"
    assert env["AVOCADO_PROVISION_RCM_ID"] == "0955:7523"


def test_opt_in_unset_keeps_the_old_nvme_path(jt):
    # The old parser offers only nvme and sd; the launcher also offers emmc.
    rc, out = jt.nvme("--boot-media", "emmc", launcher=None)
    assert rc == 2
    assert "invalid choice" in out
    rc, out = jt.nvme("--boot-media", "emmc", launcher="1")
    assert rc == 1
    assert "tegraflash-emmc" in out
    assert jt.started() == []


# --- ums: in process, fake console driver --------------------------------------------------


class FakeHost:
    def __init__(self):
        self.calls = []
        self.exported = False

    def UBoot(self, port):
        self.calls.append(("UBoot", port))
        return "ub"

    def interrupt_to_uboot(self, ub):
        self.calls.append(("interrupt",))

    def block_devices(self):
        return {"sda", "sdb"} if self.exported else {"sda"}

    def ums_expose(self, ub, controller, dev, timeout=25.0):
        self.calls.append(("expose", controller, dev))
        self.exported = True

    def ums_release(self, ub, quiet=False):
        self.calls.append(("release",))
        self.exported = False


@pytest.fixture
def ums_tree(tmp_path, monkeypatch):
    t = JTree(tmp_path)
    monkeypatch.setenv("PATH", f"{t.bin}:/usr/bin:/bin")
    t.resolved = cli.Resolved(deploy=t.deploy, machine=MACHINE, images_dir=t.images)
    return t


def ums_run(t, *args, host=None):
    host = host or FakeHost()
    rc = cli.main(["--workdir", str(t.workdir), *args, "ums"], t.resolved, host=host)
    return rc, host


def test_ums_sets_the_new_disk_as_device_and_releases(ums_tree):
    rc, host = ums_run(ums_tree, "--ums-dev", "mmc 0", "--usb-controller", "1", "--port", "/dev/ttyUSB9")
    assert rc == 0
    assert ums_tree.started() == ["stone"]
    env = ums_tree.env("stone")
    assert env["AVOCADO_PROVISION_DEVICE"] == "/dev/sdb"
    assert env["AVOCADO_PROVISION_PROFILE"] == "ums"
    assert host.calls == [("UBoot", "/dev/ttyUSB9"), ("interrupt",), ("expose", 1, "mmc 0"), ("release",)]


def test_ums_dry_run_still_exports_and_releases(ums_tree):
    rc, host = ums_run(ums_tree, "--dry-run")
    assert rc == 0
    assert ums_tree.env("stone")["AVOCADO_PROVISION_DRY_RUN"] == "1"
    assert ("expose", 0, "mmc 1") in host.calls
    assert host.calls[-1] == ("release",)


def test_ums_releases_when_the_profile_is_refused(tmp_path, monkeypatch):
    t = JTree(tmp_path, profiles={"sd": {}})
    monkeypatch.setenv("PATH", f"{t.bin}:/usr/bin:/bin")
    resolved = cli.Resolved(deploy=t.deploy, machine=MACHINE, images_dir=t.images)
    host = FakeHost()
    rc = cli.main(["ums"], resolved, host=host)
    assert rc == 1
    assert t.started() == []
    assert host.calls[-1] == ("release",)
    assert not host.exported


def test_ums_releases_when_stone_is_interrupted(ums_tree):
    ums_tree.set_stone("kill -INT $PPID\nsleep 1\nexit 0\n")
    rc, host = ums_run(ums_tree)
    assert rc == 130
    assert host.calls[-1] == ("release",)
    assert not host.exported


def test_ums_refuses_a_device_argument_before_touching_the_board(ums_tree):
    host = FakeHost()
    rc = cli.main(["ums", "/dev/sdb"], ums_tree.resolved, host=host)
    assert rc == 1
    assert host.calls == []
    assert ums_tree.started() == []


def test_ums_without_a_console_driver_refuses_loudly(ums_tree):
    with pytest.raises(LauncherError):
        cli.route_ums(ums_tree.resolved, type("A", (), {"device": None})(), host=None)
