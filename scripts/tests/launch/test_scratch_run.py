"""Scratch directory and stone run: privilege split, refusal order, cleanup.

Hermetic: stone and sudo are shell stubs in a tmp dir. The stub sudo records its
argv and runs the command as the same user; nothing here uses real sudo or USB.
"""

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from avocado_flash_launch.envmap import LauncherError, LaunchOpts
from avocado_flash_launch.run import RunContext, run_stone, safe_path
from avocado_flash_launch.scratch import MARKER, Scratch, create_scratch, plan_scratch, remove_scratch

MACHINE = "avocado-test"
UID = os.geteuid()


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.rec = tmp / "rec"
        self.rec.mkdir()
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.deploy = tmp / "deploy"
        (self.deploy / "stone").mkdir(parents=True)
        (self.deploy / "stone" / "stone-test.json").write_text("{}")
        (self.deploy / "var.img").write_bytes(b"v" * 4096)
        (self.deploy / "Image").write_bytes(b"k")
        self.workdir = tmp / "work"
        self.manifest = {
            "provision": {
                "profiles": {
                    "sd": {},
                    "uuu-emmc": {},
                    "ums": {},
                    "tegraflash-nvme": {"config": {"dry_run": True}},
                }
            },
            "storage_devices": {"rootdisk": {"images": {"var": "var.img"}}},
        }
        self.stone_rc = 0
        self.install_stubs()

    def install_stubs(self, stone_rc=0):
        rec = self.rec
        _script(
            self.bin / "stone",
            f'printf "%s\\n" "$@" > {rec}/stone.argv\n'
            f"env > {rec}/stone.env\n"
            f"stat -c %a \"$3\" > {rec}/scratch.mode\n"
            f"stat -c %u \"$3\" > {rec}/scratch.uid\n"
            f"ls -a \"$3\" > {rec}/scratch.ls\n"
            f"exit {stone_rc}\n",
        )
        _script(self.bin / "sudo", f'printf "%s\\n" "$@" >> {rec}/sudo.argv\nexec "$@"\n')

    def which_map(self, **overrides):
        known = {
            "stone": str(self.bin / "stone"),
            "sudo": str(self.bin / "sudo"),
            "python3": "/bin/true",
            "fdtget": "/bin/true",
            "fdtput": "/bin/true",
            "cpp": "/bin/true",
            "lsusb": "/bin/true",
        }
        known.update(overrides)
        return lambda name, path=None: known.get(name)

    def ctx(self, workdir=True):
        return RunContext(
            deploy=self.deploy,
            machine=MACHINE,
            images_dir=self.deploy,
            manifest=self.manifest,
            stale_ok=True,
            workdir=self.workdir if workdir else None,
        )

    def environ(self):
        return {
            "PATH": f"{self.bin}:/usr/bin:/bin:relative/dir::",
            "AVOCADO_AGENT_SOCK": "/run/agent.sock",
            "HOME": str(self.tmp),
            "LANG": "C.UTF-8",
            **self.extra_environ,
        }

    def run(self, opts, uid=UID, which=None, **kw):
        kw.setdefault("python_version", (3, 12))
        return run_stone(
            opts,
            self.ctx(),
            uid=uid,
            which=which or self.which_map(),
            environ=self.environ(),
            out=self.messages.append,
            **kw,
        )

    messages: list
    extra_environ: dict = {}

    def scratches(self):
        return sorted(self.workdir.iterdir()) if self.workdir.exists() else []


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.messages = []
    return e


def read(env, name):
    return (env.rec / name).read_text()


def digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        h.update(f"{p.relative_to(root)}|{stat.S_IMODE(st.st_mode):o}|".encode())
        if p.is_symlink():
            h.update(os.readlink(p).encode())
        elif p.is_file():
            h.update(p.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


# --- privilege split ---------------------------------------------------


def test_sd_runs_as_user_without_sudo_and_removes_scratch(env):
    assert env.run(LaunchOpts(medium="sd")) == 0
    assert not (env.rec / "sudo.argv").exists()
    argv = read(env, "stone.argv").split()
    assert argv[0] == "provision" and argv[1] == "-i"
    assert argv[3:] == ["--partition-size", "var=4096"]
    assert argv[2].startswith(str(env.workdir.resolve()) + "/s")
    assert env.scratches() == []
    # the --workdir directory itself survives
    assert env.workdir.is_dir()


def test_sd_run_keeps_the_callers_agent_socket(env):
    env.run(LaunchOpts(medium="sd"))
    assert "AVOCADO_AGENT_SOCK=/run/agent.sock" in read(env, "stone.env")


def test_tegraflash_dry_run_uses_no_sudo(env):
    assert env.run(LaunchOpts(medium="nvme", dry_run=True)) == 0
    assert not (env.rec / "sudo.argv").exists()
    assert "AVOCADO_PROVISION_DRY_RUN=1" in read(env, "stone.env")
    assert env.scratches() == []


def test_real_tegraflash_non_root_runs_whole_stone_under_sudo(env):
    assert env.run(LaunchOpts(medium="nvme", assume_yes=True)) == 0
    sudo_argv = read(env, "sudo.argv").splitlines()
    assert sudo_argv[:3] == ["env", "-u", "AVOCADO_AGENT_SOCK"]
    assert sudo_argv[sudo_argv.index("provision") - 1] == str(env.bin / "stone")
    assert "AVOCADO_PROVISION_PROFILE=tegraflash-nvme" in sudo_argv
    assert "AVOCADO_PROVISION_FORCE=1" in sudo_argv
    stone_env = read(env, "stone.env")
    assert "AVOCADO_AGENT_SOCK" not in stone_env
    assert "HOME=" not in stone_env  # fixed environment: nothing else of the caller's
    assert "AVOCADO_PROVISION_KERNEL_IMAGE=" in stone_env


def test_real_tegraflash_path_keeps_only_absolute_components(env):
    env.run(LaunchOpts(medium="nvme"))
    path_line = next(l for l in read(env, "stone.env").splitlines() if l.startswith("PATH="))
    parts = path_line.removeprefix("PATH=").split(":")
    assert parts and all(p.startswith("/") for p in parts)
    assert "relative/dir" not in path_line


def test_real_tegraflash_removes_scratch_through_sudo(env):
    env.run(LaunchOpts(medium="nvme"))
    calls = read(env, "sudo.argv").splitlines()
    assert "rm" in calls and "--one-file-system" in calls
    assert env.scratches() == []


def test_safe_path_falls_back_when_nothing_is_absolute():
    assert safe_path("a:b::").startswith("/usr/local/sbin")
    assert safe_path("/x:rel:/y") == "/x:/y"


def test_real_tegraflash_without_root_or_sudo_refuses_before_anything(env):
    which = env.which_map(sudo=None)
    with pytest.raises(LauncherError, match="needs root"):
        env.run(LaunchOpts(medium="nvme"), uid=1000, which=which)
    assert not (env.rec / "stone.argv").exists()
    assert not (env.rec / "sudo.argv").exists()
    assert not env.workdir.exists()


def test_dry_run_without_sudo_still_runs(env):
    which = env.which_map(sudo=None)
    assert env.run(LaunchOpts(medium="nvme", dry_run=True), which=which) == 0


def test_sudo_env_refuses_stone_path_with_equals_before_scratch(env, tmp_path):
    odd = tmp_path / "b=in"
    odd.mkdir()
    _script(odd / "stone", "exit 0\n")
    which = env.which_map(stone=str(odd / "stone"))
    with pytest.raises(LauncherError, match="'='"):
        env.run(LaunchOpts(medium="nvme"), which=which)
    assert not env.workdir.exists()


# --- refusals leave no scratch -----------------------------------------


def test_bmaptool_refused_first(env):
    with pytest.raises(LauncherError, match="bmaptool"):
        env.run(LaunchOpts(medium="sd", backend="bmaptool"))
    assert not env.workdir.exists()


def test_missing_profile_leaves_no_scratch(env):
    env.manifest["provision"]["profiles"].pop("sd")
    with pytest.raises(LauncherError, match="no sd profile"):
        env.run(LaunchOpts(medium="sd"))
    assert not env.workdir.exists()


def test_missing_tegra_tool_leaves_no_scratch(env):
    with pytest.raises(LauncherError, match="fdtget"):
        env.run(LaunchOpts(medium="nvme"), which=env.which_map(fdtget=None))
    assert not env.workdir.exists()


def test_missing_stone_leaves_no_scratch(env):
    with pytest.raises(LauncherError, match="stone not found"):
        env.run(LaunchOpts(medium="sd"), which=env.which_map(stone=None))
    assert not env.workdir.exists()


# --- scratch path rules ------------------------------------------------


def test_scratch_is_private_caller_owned_and_marked(env):
    env.run(LaunchOpts(medium="sd"))
    assert read(env, "scratch.mode").strip() == "700"
    assert int(read(env, "scratch.uid")) == UID
    assert MARKER in read(env, "scratch.ls")
    assert "manifest.json" in read(env, "scratch.ls")


@pytest.mark.parametrize("name", ["a.b", "a=b"])
def test_dotted_or_equals_component_refused(env, name):
    env.workdir = env.tmp / name
    with pytest.raises(LauncherError, match="'.' or '='"):
        env.run(LaunchOpts(medium="sd"))
    assert not env.workdir.exists()


def test_dotted_component_found_after_symlink_resolution(tmp_path):
    real = tmp_path / "real.dir"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(LauncherError, match="real.dir"):
        plan_scratch(link, tmp_path / "deploy", UID)


def test_scratch_inside_deploy_tree_refused(env):
    env.workdir = env.deploy / "scratchbase"
    with pytest.raises(LauncherError, match="inside the deploy tree"):
        env.run(LaunchOpts(medium="sd"))
    assert not env.workdir.exists()


def test_group_writable_ancestor_refused(env):
    open_dir = env.tmp / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    env.workdir = open_dir / "w"
    with pytest.raises(LauncherError, match="writable by group or others"):
        env.run(LaunchOpts(medium="sd"))
    assert not env.workdir.exists()


def test_sticky_world_writable_ancestor_accepted(env):
    sticky = env.tmp / "sticky"
    sticky.mkdir()
    sticky.chmod(0o1777)
    env.workdir = sticky / "w"
    assert env.run(LaunchOpts(medium="sd")) == 0


def test_ancestor_owned_by_someone_else_refused(env):
    # uid differs from the owner of tmp_path and is not root
    path = plan_scratch(env.workdir, env.deploy, UID + 12345)
    with pytest.raises(LauncherError, match="not owned by root or the current user"):
        create_scratch(path, UID + 12345)
    assert not env.workdir.exists()


def test_default_location_is_dot_free_under_var_tmp(env):
    path = plan_scratch(None, env.deploy, 1234)
    assert str(path).startswith("/var/tmp/avocado-flash-launch-1234/s")
    assert "." not in str(path) and "=" not in str(path)


# --- failure, interrupt, cleanup ---------------------------------------


def test_failed_run_keeps_scratch_and_prints_its_path(env):
    env.install_stubs(stone_rc=7)
    assert env.run(LaunchOpts(medium="sd")) == 7
    kept = env.scratches()
    assert len(kept) == 1
    assert any(str(kept[0]) in m for m in env.messages)


def test_failed_real_run_keeps_scratch(env):
    env.install_stubs(stone_rc=3)
    assert env.run(LaunchOpts(medium="nvme")) == 3
    assert len(env.scratches()) == 1
    assert "rm" not in read(env, "sudo.argv").splitlines()


class _Interrupted:
    def __init__(self, *a, **kw):
        self.calls = 0

    def wait(self):
        self.calls += 1
        if self.calls == 1:
            raise KeyboardInterrupt
        return 0


def test_sigint_waits_for_stone_returns_130_and_keeps_scratch(env):
    procs = []

    def popen(argv, env=None, cwd=None):
        p = _Interrupted()
        procs.append(p)
        return p

    assert env.run(LaunchOpts(medium="sd"), popen=popen) == 130
    assert procs[0].calls == 2  # waited again after the interrupt
    assert len(env.scratches()) == 1
    assert any("interrupted" in m for m in env.messages)


def test_remove_scratch_refuses_unmarked_directory(tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious").write_text("x")
    assert remove_scratch(Scratch(victim, "tok")) == victim
    assert (victim / "precious").exists()


def test_remove_scratch_refuses_foreign_token(tmp_path):
    scratch = create_scratch(tmp_path / "s1", UID)
    other = Scratch(scratch.path, "not-the-token")
    assert remove_scratch(other) == scratch.path
    assert scratch.path.exists()
    assert remove_scratch(scratch) is None
    assert not scratch.path.exists()


def test_remove_scratch_refuses_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / MARKER).write_text("tok\n")
    link = tmp_path / "link"
    link.symlink_to(target)
    assert remove_scratch(Scratch(link, "tok")) == link
    assert target.exists()


# --- the deploy tree is never modified ---------------------------------


def test_deploy_tree_unchanged_by_dry_run_and_stubbed_real_run(env):
    before = digest(env.deploy)
    assert env.run(LaunchOpts(medium="nvme", dry_run=True)) == 0
    assert digest(env.deploy) == before
    assert env.run(LaunchOpts(medium="nvme", assume_yes=True)) == 0
    assert digest(env.deploy) == before
    assert env.run(LaunchOpts(medium="sd")) == 0
    assert digest(env.deploy) == before


def test_digest_detects_a_change(env):
    before = digest(env.deploy)
    (env.deploy / "Image").write_bytes(b"changed")
    assert digest(env.deploy) != before


# --- test-seam variables never reach stone -------------------------------

SEAMS = {
    "AVOCADO_PROVISION_SYSBLOCK": "/fake/sys",
    "AVOCADO_SAFE_DISK_MOUNTS": "/fake/mounts",
    "AVOCADO_SAFE_DISK_SWAPS": "/fake/swaps",
    "AVOCADO_SAFE_DISK_DEVDIR": "/fake/dev",
    "AVOCADO_SAFE_DISK_EUID": "0",
    "AVOCADO_SAFE_DISK_CONTAINER_MARKERS": "/fake/marker",
}

RUNS = {
    "sd": LaunchOpts(medium="sd"),
    "emmc": LaunchOpts(medium="emmc"),
    "ums": LaunchOpts(medium="ums"),
    "tegraflash-dry-run": LaunchOpts(medium="nvme", dry_run=True),
    "tegraflash-real": LaunchOpts(medium="nvme", assume_yes=True),
}


@pytest.mark.parametrize("name", sorted(RUNS))
def test_test_seam_variables_do_not_reach_stone_and_are_warned(env, name):
    env.extra_environ = dict(SEAMS)
    env.run(RUNS[name])
    stone_env = read(env, "stone.env")
    for var, value in SEAMS.items():
        assert f"{var}=" not in stone_env, var
        assert any(var in m and repr(value) in m for m in env.messages), var


@pytest.mark.parametrize("name", ["sd", "emmc", "ums", "tegraflash-dry-run"])
def test_ordinary_variables_still_reach_user_runs(env, name):
    env.extra_environ = dict(SEAMS)
    env.run(RUNS[name])
    stone_env = read(env, "stone.env")
    assert f"HOME={env.tmp}" in stone_env
    assert "LANG=C.UTF-8" in stone_env
    assert "PATH=" in stone_env


def test_no_seam_warning_when_none_inherited(env):
    env.run(LaunchOpts(medium="sd"))
    assert not any("AVOCADO_SAFE_DISK" in m or "SYSBLOCK" in m for m in env.messages)


# --- LD_LIBRARY_PATH reaches the root run only from the launcher ---------


def _sysroot(tmp: Path, stone_src: Path) -> Path:
    root = tmp / "sysroot"
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/lib").mkdir(parents=True)
    _script(root / "usr/bin/stone", stone_src.read_text().split("\n", 1)[1])
    return root


def _ld_line(env):
    return next((l for l in read(env, "stone.env").splitlines() if l.startswith("LD_LIBRARY_PATH=")), None)


def test_root_run_never_forwards_the_callers_ld_library_path(env):
    env.extra_environ = {"LD_LIBRARY_PATH": "/opt/x:"}
    env.run(LaunchOpts(medium="nvme"))
    assert _ld_line(env) is None


def test_root_run_passes_only_absolute_sysroot_library_dirs(env, tmp_path):
    env.extra_environ = {"LD_LIBRARY_PATH": "/opt/x:"}
    root = _sysroot(tmp_path, env.bin / "stone")
    which = env.which_map(stone=None)
    env.run(LaunchOpts(medium="nvme"), which=which, sysroot_lookup=lambda tool: root)
    assert _ld_line(env) == f"LD_LIBRARY_PATH={root}/usr/lib"


def test_user_run_keeps_the_callers_ld_library_path_without_empty_or_relative(env):
    env.extra_environ = {"LD_LIBRARY_PATH": "rel:/opt/x:"}
    env.run(LaunchOpts(medium="sd"))
    assert _ld_line(env) == "LD_LIBRARY_PATH=/opt/x"


def test_user_run_with_only_empty_components_sets_no_ld_library_path(env):
    env.extra_environ = {"LD_LIBRARY_PATH": ":rel"}
    env.run(LaunchOpts(medium="sd"))
    assert _ld_line(env) is None


# --- sudo is resolved once, to an absolute path ----------------------------


def test_relative_sudo_from_which_is_refused_before_anything(env):
    which = env.which_map(sudo="./sudo")
    with pytest.raises(LauncherError, match="needs root"):
        env.run(LaunchOpts(medium="nvme"), which=which, uid=1000)
    assert not env.workdir.exists()


def test_sudo_is_searched_only_in_absolute_path_components(env, tmp_path, monkeypatch):
    trap = tmp_path / "cwd"
    trap.mkdir()
    _script(trap / "sudo", f'echo used > {env.rec}/trap.used\nexec "$@"\n')
    monkeypatch.chdir(trap)
    known = env.which_map()
    seen = {}

    def which(name, path=None):
        if name == "sudo":
            seen["path"] = path
            return shutil.which("sudo", path=path)
        return known(name)

    env.extra_environ = {"PATH": f".::{env.bin}:/usr/bin"}
    assert env.run(LaunchOpts(medium="nvme"), which=which) == 0
    assert seen["path"] == f"{env.bin}:/usr/bin"
    assert not (env.rec / "trap.used").exists()


def test_same_absolute_sudo_serves_the_flash_and_the_cleanup(env):
    calls = []

    def popen(argv, **kw):
        calls.append(("flash", argv[0]))
        return subprocess.Popen(argv, **kw)

    def capture_fn(argv):
        calls.append(("rm", argv[0]))
        return 0, ""

    assert env.run(LaunchOpts(medium="nvme"), popen=popen, capture_fn=capture_fn) == 0
    assert calls == [("flash", str(env.bin / "sudo")), ("rm", str(env.bin / "sudo"))]


# --- free-space pre-check before escalation -----------------------------------


class _Usage:
    def __init__(self, free):
        self.free = free
        self.probed = []

    def __call__(self, path):
        self.probed.append(Path(path))
        return self


def test_real_tegraflash_refuses_when_scratch_filesystem_is_too_small(env):
    du = _Usage(free=1)
    with pytest.raises(LauncherError, match=r"not enough free space.*needs \d+ bytes.*has 1 "):
        env.run(LaunchOpts(medium="nvme"), disk_usage=du)
    assert not env.workdir.exists()
    assert not (env.rec / "sudo.argv").exists()
    assert du.probed and du.probed[0].exists()


def test_free_space_need_is_inputs_plus_one_tenth(env):
    # the stone dir holds stone-test.json (2 bytes): need 2 + ceil(2 / 10) = 3
    assert env.run(LaunchOpts(medium="nvme"), disk_usage=_Usage(free=3)) == 0
    with pytest.raises(LauncherError, match="not enough free space"):
        env.run(LaunchOpts(medium="nvme"), disk_usage=_Usage(free=2))


def test_dry_run_and_user_runs_skip_the_space_check(env):
    assert env.run(LaunchOpts(medium="nvme", dry_run=True), disk_usage=_Usage(free=0)) == 0
    assert env.run(LaunchOpts(medium="sd"), disk_usage=_Usage(free=0)) == 0
