"""The launcher holds no write logic: stone is the only tool it starts.

Hermetic: stone, fwup, uuu, dd, bmaptool, lsusb and sudo are recording stubs in
a tmp PATH dir. Each stub appends `name pid ppid` to one log, so the assertions
run over STARTED PROCESSES and their parents, never over source text. The stone
stub itself starts fwup, uuu, dd and bmaptool, which proves the checker tells
"started by stone" (allowed) from "started by the launcher" (a violation). A
stand-in launcher that runs dd directly is fed through the same checker as a
negative control. Nothing here touches a board, USB, a console or real sudo.
"""

import os
import subprocess
import sys

import pytest

from avocado_flash_launch import cli
from test_launcher_cli import MACHINE
from test_launcher_jetson_ums import FakeHost, JTree

FORBIDDEN = ("fwup", "uuu", "dd", "bmaptool", "lsusb")
WRITERS = ("fwup", "uuu", "dd", "bmaptool")

PROFILES = {
    name: {"config": {"dry_run": True}}
    for name in ("sd", "uuu-emmc", "tegraflash-nvme", "tegraflash-sd", "tegraflash-emmc", "ums")
}


def install_recording_stubs(t, stone_rc=0):
    """Replace every tool stub with one logging `name pid ppid`; stone spawns the writers.

    sudo also records its argv, one argument per line, in rec/sudo.<pid>.argv; stone
    records its own in rec/stone.argv.
    """
    def put(name, body):
        path = t.bin / name
        path.write_text(f'#!/bin/sh\necho "{name} $$ $PPID" >> {t.log}\n{body}')
        path.chmod(0o755)

    # rm is a harmless recording stub: a stand-in running `sudo rm -rf /` must never delete anything.
    for name in ("fwup", "uuu", "dd", "bmaptool", "lsusb", "rm"):
        put(name, "exit 0\n")
    put(
        "stone",
        "".join(f"{w} x\n" for w in WRITERS)
        + f'printf "%s\\n" "$@" > {t.rec}/stone.argv\nexit {stone_rc}\n',
    )
    # sudo runs its command as a child (no exec) so stone's parent is sudo, not the launcher.
    put("sudo", f'printf "%s\\n" "$@" > {t.rec}/sudo.$$.argv\n"$@"\nexit $?\n')


def sudo_argv(t, pid):
    return (t.rec / f"sudo.{pid}.argv").read_text().splitlines()


def scratch_of(t):
    argv = (t.rec / "stone.argv").read_text().splitlines()
    return argv[argv.index("-i") + 1]


def entries(log):
    rows = []
    if log.exists():
        for line in log.read_text().splitlines():
            name, pid, ppid = line.split()
            rows.append((name, int(pid), int(ppid)))
    return rows


def violations(rows, launcher_pid, expected, t=None):
    """What the launcher itself started, judged against `expected`.

    expected is one of:
      "stone"          the launcher's only child is stone;
      "sudo>stone"     its only child is sudo, whose only child is stone (a failed
                       tegraflash run: the scratch is kept, so no cleanup);
      "sudo>stone+rm"  as above, then exactly one more sudo whose only child is rm and
                       whose argv is `rm -rf --one-file-system -- <stone's -i path>`.
    Children of stone are unrestricted: stone is the tool allowed to write. `t` is the
    tree holding the recorded argv files; it is needed for the "+rm" form.
    """
    bad = []
    known = {launcher_pid} | {pid for _, pid, _ in rows}
    for name, pid, ppid in rows:
        if ppid not in known:
            bad.append(f"{name} has unknown parent {ppid}")
    direct = [(n, p) for n, p, pp in rows if pp == launcher_pid]
    names = [n for n, _ in direct]
    for name in names:
        if name in FORBIDDEN:
            bad.append(f"launcher started {name}")
    if expected == "stone":
        if names != ["stone"]:
            bad.append(f"launcher children {names} != ['stone']")
        return bad
    want = ["sudo", "sudo"] if expected == "sudo>stone+rm" else ["sudo"]
    if names != want:
        bad.append(f"launcher children {names} != {want}")
        return bad
    first = direct[0][1]
    under = [n for n, _, pp in rows if pp == first]
    if under != ["stone"]:
        bad.append(f"sudo children {under} != ['stone']")
    if expected == "sudo>stone+rm":
        second = direct[1][1]
        under = [n for n, _, pp in rows if pp == second]
        if under != ["rm"]:
            bad.append(f"cleanup sudo children {under} != ['rm']")
        got = sudo_argv(t, second)
        exact = ["rm", "-rf", "--one-file-system", "--", scratch_of(t)]
        if got != exact:
            bad.append(f"cleanup sudo argv {got} != {exact}")
    return bad


def launcher_run(t, argv_tail, nvme=False):
    """Run the real avocado-flash entry; return the pid of the launcher process."""
    env = {"PATH": f"{t.bin}:/usr/bin:/bin", "HOME": str(t.tmp), "AVOCADO_FLASH_LAUNCHER": "1"}
    from test_launcher_cli import SCRIPT

    head = [sys.executable, str(SCRIPT)]
    if nvme:
        argv = head + ["nvme", "--deploy", str(t.deploy), "--machine", MACHINE, *argv_tail]
    else:
        argv = head + ["--deploy", str(t.deploy), "--machine", MACHINE, *argv_tail]
    out = t.tmp / "out.txt"
    with open(out, "w") as fh:
        proc = subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        rc = proc.wait(timeout=60)
    return proc.pid, rc, out.read_text()


@pytest.fixture
def t(tmp_path):
    jt = JTree(tmp_path, profiles=PROFILES)
    install_recording_stubs(jt)
    return jt


def w(t):
    return ["--workdir", str(t.workdir)]


CASES = {
    "sd-real": (lambda t: w(t) + ["sd", "/dev/fakedisk"], False, "stone", False),
    "sd-dry": (lambda t: w(t) + ["--dry-run", "sd", "/dev/fakedisk"], False, "stone", False),
    "emmc-real": (lambda t: w(t) + ["emmc"], False, "stone", False),
    "emmc-dry": (lambda t: w(t) + ["--dry-run", "emmc"], False, "stone", False),
    "nvme-real": (lambda t: w(t), True, "sudo>stone+rm", True),
    "nvme-dry": (lambda t: w(t) + ["--dry-run"], True, "stone", False),
    "nvme-sd-real": (lambda t: w(t) + ["--boot-media", "sd"], True, "sudo>stone+rm", True),
    "nvme-sd-dry": (lambda t: w(t) + ["--boot-media", "sd", "--dry-run"], True, "stone", False),
    "nvme-emmc-real": (lambda t: w(t) + ["--boot-media", "emmc"], True, "sudo>stone+rm", True),
    "nvme-emmc-dry": (lambda t: w(t) + ["--boot-media", "emmc", "--dry-run"], True, "stone", False),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_launcher_children_are_only_stone(t, case):
    tail, nvme, expected, needs_user = CASES[case]
    if needs_user and os.geteuid() == 0:
        pytest.skip("the sudo path is only taken by a non-root user")
    pid, rc, out = launcher_run(t, tail(t), nvme=nvme)
    assert rc == 0, out
    rows = entries(t.log)
    assert violations(rows, pid, expected, t) == [], rows
    # The distinction is live: stone did start the writers, as its own children.
    stone_pid = next(p for n, p, _ in rows if n == "stone")
    started_by_stone = sorted(n for n, _, pp in rows if pp == stone_pid)
    assert started_by_stone == sorted(WRITERS), rows

@pytest.mark.skipif(os.geteuid() == 0, reason="the sudo path is only taken by a non-root user")
def test_failed_tegraflash_run_has_no_cleanup_sudo(tmp_path):
    t = JTree(tmp_path, profiles=PROFILES)
    install_recording_stubs(t, stone_rc=3)
    pid, rc, out = launcher_run(t, w(t), nvme=True)
    assert rc == 3, out
    rows = entries(t.log)
    assert violations(rows, pid, "sudo>stone", t) == [], rows
    assert "rm" not in [n for n, _, _ in rows], rows



@pytest.mark.skipif(os.geteuid() == 0, reason="the sudo path is only taken by a non-root user")
@pytest.mark.parametrize("media", ["nvme", "sd", "emmc"])
def test_real_tegraflash_never_starts_a_writer_under_launcher_or_its_sudo(t, media):
    pid, rc, out = launcher_run(t, w(t) + ["--boot-media", media], nvme=True)
    assert rc == 0, out
    rows = entries(t.log)
    sudo_pids = {p for n, p, pp in rows if n == "sudo" and pp == pid}
    assert sudo_pids, rows
    for name, _, ppid in rows:
        if ppid == pid or ppid in sudo_pids:
            assert name in ("sudo", "stone", "rm"), rows



@pytest.mark.parametrize("dry", [False, True])
def test_ums_children_are_only_stone(t, monkeypatch, dry):
    monkeypatch.setenv("PATH", f"{t.bin}:/usr/bin:/bin")
    resolved = cli.Resolved(deploy=t.deploy, machine=MACHINE, images_dir=t.images)
    args = w(t) + (["--dry-run"] if dry else []) + ["ums"]
    rc = cli.main(args, resolved, host=FakeHost())
    assert rc == 0
    rows = entries(t.log)
    assert violations(rows, os.getpid(), "stone") == [], rows
    stone_pid = next(p for n, p, _ in rows if n == "stone")
    assert sorted(n for n, _, pp in rows if pp == stone_pid) == sorted(WRITERS), rows


# --- negative controls: the checker must be able to fail ------------------------------------


def standin(t, body):
    path = t.tmp / "standin-launcher"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    proc = subprocess.Popen(
        [str(path)], env={"PATH": f"{t.bin}:/usr/bin:/bin"}, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    assert proc.wait(timeout=60) == 0
    return proc.pid


@pytest.mark.parametrize("writer", WRITERS)
def test_checker_flags_a_launcher_that_runs_a_writer_directly(t, writer):
    pid = standin(t, f"{writer} x\nstone provision\n")
    bad = violations(entries(t.log), pid, "stone")
    assert f"launcher started {writer}" in bad


def test_checker_flags_a_launcher_that_runs_dd_instead_of_stone(t):
    pid = standin(t, "dd if=/dev/zero of=/dev/null\n")
    bad = violations(entries(t.log), pid, "stone")
    assert "launcher started dd" in bad
    assert any("!= ['stone']" in b for b in bad)


def test_checker_flags_sudo_wrapping_something_other_than_stone(t):
    pid = standin(t, "sudo dd x\n")
    bad = violations(entries(t.log), pid, "sudo>stone")
    assert any("sudo children" in b for b in bad)


RUN_STONE = "sudo stone provision -i /scratch/x\n"


def cleanup_violations(t, rm_line):
    pid = standin(t, RUN_STONE + rm_line)
    return violations(entries(t.log), pid, "sudo>stone+rm", t)


def test_checker_accepts_the_exact_cleanup_sudo(t):
    assert cleanup_violations(t, "sudo rm -rf --one-file-system -- /scratch/x\n") == []


@pytest.mark.parametrize(
    "rm_line",
    [
        "sudo dd x\n",
        "sudo rm -rf /\n",
        "sudo rm -rf --one-file-system -- /scratch/other\n",
        "sudo rm /scratch/x\n",
        "sudo rm -rf -- /scratch/x\n",
        "sudo rm -rf --one-file-system -- /scratch/x /etc\n",
    ],
)
def test_checker_flags_a_second_sudo_that_is_not_the_exact_cleanup(t, rm_line):
    assert cleanup_violations(t, rm_line) != []


def test_checker_flags_a_third_sudo_after_the_cleanup(t):
    line = "sudo rm -rf --one-file-system -- /scratch/x\nsudo dd x\n"
    assert cleanup_violations(t, line) != []


def test_checker_flags_a_cleanup_sudo_when_none_is_expected(t):
    pid = standin(t, RUN_STONE + "sudo rm -rf --one-file-system -- /scratch/x\n")
    assert violations(entries(t.log), pid, "sudo>stone", t) != []


def test_checker_accepts_a_launcher_that_runs_only_stone(t):
    pid = standin(t, "stone provision\n")
    assert violations(entries(t.log), pid, "stone") == []
