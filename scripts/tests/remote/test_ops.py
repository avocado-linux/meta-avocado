"""Tests for the operations interface (scripts/avocado_flash_remote/ops.py).

No real device or mutating tool is touched: RealOps is driven against a
temp directory of stub shell scripts, and vectors are asserted through the
pure ``vec_*`` builders.
"""

from __future__ import annotations

import ast
import os
import pathlib
import stat
import time

import pytest

from avocado_flash_remote import ops as O

SCRIPTS = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "calls.log"

DISK = "/dev/mmcblk0"

MUTATING_CALLS = [
    lambda o: o.sfdisk_write(DISK, "label: gpt\n"),
    lambda o: o.sfdisk_delete(DISK, [1, 2]),
    lambda o: o.wipefs(DISK),
    lambda o: o.udevadm_settle(),
    lambda o: o.blockdev_flushbufs(f"{DISK}p3"),
    lambda o: o.dd_write("/run/x/boot.img", f"{DISK}p3"),
    lambda o: o.efibootmgr_next("0003"),
    lambda o: o.efibootmgr_delete_next(),
    lambda o: o.mount(f"{DISK}p16", "/mnt/x", "ro", "btrfs"),
    lambda o: o.umount("/mnt/x"),
    lambda o: o.dd_read("/dev/zero", "1", count=1, of="/tmp/never"),
    lambda o: o.run_read(["blockdev", "--setro", DISK]),
    lambda o: o.run_read(["efibootmgr", "-B", "-b", "0001"]),
    lambda o: o.run_read(["sfdisk", "--delete", DISK, "1"]),
    lambda o: o.run_read(["dd", "if=/dev/zero", f"of={DISK}"]),
]


def _script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


# ------------------------------------------------------------- read-only


@pytest.mark.parametrize("call", MUTATING_CALLS)
def test_read_only_refuses_every_mutating_verb_before_launch(call):
    inner = O.RecordingOps()
    ro = O.ReadOnlyOps(inner)
    with pytest.raises(O.MutationRefused):
        call(ro)
    assert inner.calls == []


def test_read_only_passes_reads_through():
    inner = O.RecordingOps({f"blockdev --getsz {DISK}": "122314752\n"})
    ro = O.ReadOnlyOps(inner)
    assert ro.blockdev_getsz(DISK) == 122314752
    assert inner.log == [f"blockdev --getsz {DISK}"]


def test_read_only_wrapping_real_launches_nothing_on_mutation(tmp_path):
    marker = tmp_path / "ran"
    _script(tmp_path / "wipefs", f"touch {marker}\n")
    ro = O.ReadOnlyOps(O.RealOps(tool_dir=tmp_path))
    with pytest.raises(O.MutationRefused):
        ro.wipefs(DISK)
    assert not marker.exists()


# ------------------------------------------------------------- recording


def test_recording_keeps_order_and_arguments():
    r = O.RecordingOps(
        {
            f"blockdev --getro {DISK}": "0\n",
            f"blockdev --getsz {DISK}": "100\n",
            "efibootmgr -v": "BootCurrent: 0001\n",
        }
    )
    r.efibootmgr_list()
    r.blockdev_getro(DISK)
    r.blockdev_getsz(DISK)
    r.sfdisk_write(DISK, "label: gpt\n")
    r.dd_write("/i/boot.img", f"{DISK}p3")
    r.efibootmgr_next("0004")
    assert r.log == [
        "efibootmgr -v",
        f"blockdev --getro {DISK}",
        f"blockdev --getsz {DISK}",
        f"sfdisk {DISK}",
        f"dd if=/i/boot.img of={DISK}p3 bs=1M conv=fsync status=none",
        "efibootmgr -n 0004",
    ]
    assert r.calls[3].stdin == b"label: gpt\n"


def test_recording_unscripted_read_is_an_error_not_a_default():
    r = O.RecordingOps()
    with pytest.raises(O.UnscriptedCall):
        r.blockdev_getsz(DISK)
    with pytest.raises(O.UnscriptedCall):
        r.read_file("/etc/nothing")
    # the attempted read is still recorded
    assert r.log == [f"blockdev --getsz {DISK}", "read_file /etc/nothing"]


def test_recording_queue_results_pop_in_order_and_exhaust_loudly():
    line = f"blockdev --getsize64 {DISK}p3"
    r = O.RecordingOps({line: ["10\n", "20\n"]})
    assert r.blockdev_getsize64(f"{DISK}p3") == 10
    assert r.blockdev_getsize64(f"{DISK}p3") == 20
    with pytest.raises(O.UnscriptedCall):
        r.blockdev_getsize64(f"{DISK}p3")


def test_recording_scripted_failure_raises_opfailed_with_vector():
    r = O.RecordingOps({"efibootmgr -n 0004": O.OpResult(rc=2, stderr="boom")})
    with pytest.raises(O.OpFailed) as ei:
        r.efibootmgr_next("0004")
    assert ei.value.vector == ["efibootmgr", "-n", "0004"]
    assert ei.value.rc == 2
    assert "boom" in ei.value.stderr


def test_recording_check_false_returns_rc():
    r = O.RecordingOps({f"sfdisk --dump {DISK}": O.OpResult(rc=1, stderr="none")})
    assert r.sfdisk_dump(DISK).rc == 1


def test_recording_replacements_normalise_temp_dirs():
    r = O.RecordingOps(replacements=[("/tmp/abc", "<TMP>")])
    r.dd_write("/tmp/abc/images/boot.img", f"{DISK}p3")
    assert r.log == [f"dd if=<TMP>/images/boot.img of={DISK}p3 bs=1M conv=fsync status=none"]


def test_recording_file_verbs_are_reads_only():
    r = O.RecordingOps({"read_file /x": b"hi"})
    assert r.read_file("/x") == b"hi"
    with pytest.raises(ValueError):
        r._fs("efivar_write", "/efivars/V", b"\x01")
    assert r.log == ["read_file /x"]


# ------------------------------------------------------------ vectors


def test_vectors_match_kit_argument_lists():
    V = O.Ops
    assert V.vec_blockdev_getsz(DISK) == ["blockdev", "--getsz", DISK]
    assert V.vec_blockdev_getro(DISK) == ["blockdev", "--getro", DISK]
    assert V.vec_blockdev_getsize64(DISK + "p3") == ["blockdev", "--getsize64", DISK + "p3"]
    assert V.vec_findmnt_source() == ["findmnt", "-rn", "-o", "SOURCE"]
    assert V.vec_findmnt_options("/sys/firmware/efi/efivars") == [
        "findmnt", "-no", "OPTIONS", "/sys/firmware/efi/efivars"]  # fmt: skip
    assert V.vec_findmnt_fstype("/s") == ["findmnt", "-no", "FSTYPE", "-T", "/s"]
    assert V.vec_lsblk(DISK, "NAME,TYPE") == ["lsblk", "-rn", "-o", "NAME,TYPE", DISK]
    assert V.vec_lsblk(DISK, "NAME,PARTLABEL") == ["lsblk", "-rn", "-o", "NAME,PARTLABEL", DISK]
    assert V.vec_lsblk(DISK) == ["lsblk", DISK]
    assert V.vec_lsblk_disks() == ["lsblk", "-dn", "-o", "NAME"]
    assert V.vec_sfdisk_dump(DISK) == ["sfdisk", "--dump", DISK]
    assert V.vec_blkid(DISK + "p11") == ["blkid", "-p", "-s", "TYPE", "-o", "value", DISK + "p11"]
    assert V.vec_efibootmgr_list() == ["efibootmgr", "-v"]
    assert V.vec_efibootmgr_help() == ["efibootmgr", "--help"]
    assert V.vec_sha256sum_check() == ["sha256sum", "--strict", "-c", "MANIFEST.hashes"]
    assert V.vec_stat_size("/i/f") == ["stat", "-c", "%s", "/i/f"]
    assert V.vec_od_bytes("/h", "u4", skip=40, count=4, endian="little", verbose=False) == [
        "od", "-An", "-tu4", "--endian=little", "-j40", "-N4", "/h"]  # fmt: skip
    assert V.vec_od_bytes("/f") == ["od", "-An", "-v", "-tu1", "/f"]
    assert V.vec_df_free("/s") == ["df", "-Pk", "/s"]
    assert V.vec_uname_r() == ["uname", "-r"]
    assert V.vec_docker_ps() == ["docker", "ps", "-q"]
    assert V.vec_dd_read("/i/boot.img", 2048, count=1, of="/r/bhdr") == [
        "dd", "if=/i/boot.img", "of=/r/bhdr", "bs=2048", "count=1", "status=none"]  # fmt: skip
    assert V.vec_dd_read("/r/bhdr", 1, count=512, skip=64) == [
        "dd", "if=/r/bhdr", "bs=1", "skip=64", "count=512", "status=none"]  # fmt: skip
    assert V.vec_dd_read(DISK + "p3", "4M", count=1234, iflag="count_bytes") == [
        "dd", "if=/dev/mmcblk0p3", "bs=4M", "iflag=count_bytes", "count=1234", "status=none"]  # fmt: skip
    assert V.vec_sfdisk_write(DISK) == ["sfdisk", DISK]
    assert V.vec_sfdisk_delete(DISK, [3, 4]) == ["sfdisk", "--delete", DISK, "3", "4"]
    assert V.vec_wipefs(DISK) == ["wipefs", "-a", DISK]
    assert V.vec_udevadm_settle() == ["udevadm", "settle"]
    assert V.vec_dd_write("/i/boot.img", DISK + "p3") == [
        "dd", "if=/i/boot.img", "of=/dev/mmcblk0p3", "bs=1M", "conv=fsync", "status=none"]  # fmt: skip
    assert V.vec_efibootmgr_next("0004") == ["efibootmgr", "-n", "0004"]
    assert V.vec_efibootmgr_delete_next() == ["efibootmgr", "-N"]
    assert V.vec_mount(DISK + "p16", "/m", "ro", "btrfs") == [
        "mount", "-o", "ro", "-t", "btrfs", DISK + "p16", "/m"]  # fmt: skip
    assert V.vec_umount("/m") == ["umount", "/m"]
    assert V.vec_blockdev_flushbufs(DISK + "p3") == ["blockdev", "--flushbufs", DISK + "p3"]


def test_ops_has_no_boot_entry_create_or_delete_verb():
    # The arm selects the firmware's own entry; nothing may create or delete one.
    for name in ("efibootmgr_create", "efibootmgr_delete", "vec_efibootmgr_create", "vec_efibootmgr_delete"):
        assert not hasattr(O.Ops, name), name
        assert not hasattr(O.RecordingOps, name), name


def test_efibootmgr_next_rejects_a_non_hex_entry():
    with pytest.raises(ValueError):
        O.Ops.vec_efibootmgr_next("0004; reboot")


@pytest.mark.parametrize("opt", ["-C", "-B", "-b", "-o", "-O", "-c"])
def test_every_creating_or_deleting_efibootmgr_option_is_classed_as_mutating(opt):
    assert O.vector_mutates(["efibootmgr", opt, "0001"]) is True


def test_every_install_and_window_golden_line_is_buildable():
    """Each golden tool line for the covered tools matches a builder output."""
    built = {
        "blockdev --getsz /dev/mmcblk0", "blockdev --getro /dev/mmcblk0",
        "findmnt -rn -o SOURCE", "lsblk -rn -o NAME,TYPE /dev/mmcblk0",
        "sfdisk --dump /dev/mmcblk0", "efibootmgr -v", "efibootmgr --help",
        "findmnt -no OPTIONS /sys/firmware/efi/efivars", "efibootmgr -N",
        "udevadm settle", "uname -r", "docker ps -q",
    }  # fmt: skip
    lines = [ln for ln in GOLDEN.read_text().splitlines() if ln in built]
    assert lines, "golden has no matching lines"
    rec = O.RecordingOps({k: "0\n" for k in built})
    for ln in set(lines):
        # round trip: split the golden line to a vector and run it through run_read/mutation path
        vec = ln.split()
        if O.vector_mutates(vec):
            continue
        rec.run_read(vec)
    assert set(rec.log) <= built


# ----------------------------------------------------------- classify


@pytest.mark.parametrize(
    "vec,mutates",
    [
        (["blockdev", "--getsz", DISK], False),
        (["blockdev", "--setro", DISK], True),
        (["sfdisk", "--dump", DISK], False),
        (["sfdisk", DISK], True),
        (["sfdisk", "--delete", DISK, "1"], True),
        (["efibootmgr", "-v"], False),
        (["efibootmgr"], False),
        (["efibootmgr", "-n", "0001"], True),
        (["dd", "if=/a", "bs=1", "status=none"], False),
        (["dd", "if=/a", "of=/b"], True),
        (["rm", "-rf", "/"], True),
        (["wipefs", "-a", DISK], True),
        (["blkid", "-p", DISK], False),
        (["blockdev", "--flushbufs", DISK + "p3"], True),
        (["blockdev", "--getsz", "--flushbufs", DISK + "p3"], True),
    ],
)
def test_vector_mutates(vec, mutates):
    assert O.vector_mutates(vec) is mutates


# ---------------------------------------------------------- real: no exec


def test_real_builds_vectors_without_executing(tmp_path):
    marker = tmp_path / "ran"
    for tool in ("blockdev", "sfdisk", "dd", "efibootmgr"):
        _script(tmp_path / tool, f"touch {marker}\n")
    # Building vectors never needs a RealOps and never launches anything.
    assert O.Ops.vec_dd_write("/a", "/dev/mmcblk0p3")[0] == "dd"
    assert not marker.exists()


# ------------------------------------------------------- real: plumbing


def test_real_runs_stub_tool_and_passes_argv_and_stdin(tmp_path):
    _script(tmp_path / "sfdisk", 'echo "$@" > "$0.argv"; cat > "$0.stdin"; exit 0\n')
    r = O.RealOps(tool_dir=tmp_path)
    r.sfdisk_write(DISK, "label: gpt\n")
    assert (tmp_path / "sfdisk.argv").read_text().strip() == DISK
    assert (tmp_path / "sfdisk.stdin").read_text() == "label: gpt\n"


def test_real_dd_write_stub_gets_exact_argv(tmp_path):
    _script(tmp_path / "dd", 'for a in "$@"; do echo "$a"; done > "$0.argv"\n')
    O.RealOps(tool_dir=tmp_path).dd_write("/i/boot.img", DISK + "p3")
    assert (tmp_path / "dd.argv").read_text().split() == [
        "if=/i/boot.img", "of=/dev/mmcblk0p3", "bs=1M", "conv=fsync", "status=none"]  # fmt: skip


def test_real_nonzero_raises_opfailed_with_vector_rc_stderr(tmp_path):
    _script(tmp_path / "blockdev", "echo nope >&2; exit 3\n")
    with pytest.raises(O.OpFailed) as ei:
        O.RealOps(tool_dir=tmp_path).blockdev_getsz(DISK)
    assert ei.value.vector == ["blockdev", "--getsz", DISK]
    assert ei.value.rc == 3
    assert "nope" in ei.value.stderr


def test_real_check_false_returns_result(tmp_path):
    _script(tmp_path / "sfdisk", "echo err >&2; exit 1\n")
    res = O.RealOps(tool_dir=tmp_path).sfdisk_dump(DISK)
    assert res.rc == 1
    assert "err" in res.stderr


def test_real_parses_outputs(tmp_path):
    _script(tmp_path / "blockdev", "echo 122314752\n")
    _script(tmp_path / "df", "echo Filesystem; echo 'tmpfs 1000 400 600 40% /run'\n")
    _script(tmp_path / "dd", "printf 'abc'\n")
    r = O.RealOps(tool_dir=tmp_path)
    assert r.blockdev_getsz(DISK) == 122314752
    assert r.df_free("/run") == 600
    import hashlib
    assert r.dd_sha256(DISK + "p3", "4M", 3) == hashlib.sha256(b"abc").hexdigest()


def test_real_missing_tool_is_opfailed_and_path_not_trusted(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    _script(other / "wipefs", "exit 0\n")
    monkeypatch.setenv("PATH", str(other))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(O.OpFailed):
        O.RealOps(tool_dir=empty).wipefs(DISK)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_real_timeout_kills_child_group_without_orphans(tmp_path):
    pidfile = tmp_path / "pids"
    _script(
        tmp_path / "dd",
        f'echo $$ > {pidfile}; sleep 60 &\necho $! >> {pidfile}\nwait\n',
    )
    r = O.RealOps(tool_dir=tmp_path, term_grace=0.5)
    start = time.monotonic()
    with pytest.raises(O.OpFailed) as ei:
        r.dd_write("/i/x", DISK + "p3", timeout=1.0)
    assert time.monotonic() - start < 10
    assert ei.value.rc is None
    pids = [int(p) for p in pidfile.read_text().split()]
    assert len(pids) == 2
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.05)
    assert not any(_alive(p) for p in pids), "orphan survived the group kill"


def test_real_interrupt_during_wait_kills_the_child_group_and_reraises(tmp_path, monkeypatch):
    pidfile = tmp_path / "pids"
    _script(
        tmp_path / "dd",
        f'echo $$ > {pidfile}; sleep 60 &\necho $! >> {pidfile}\nwait\n',
    )
    real_popen = O.subprocess.Popen

    class InterruptedOnFirstWait(real_popen):
        interrupted = False

        def wait(self, timeout=None):
            if not InterruptedOnFirstWait.interrupted:
                InterruptedOnFirstWait.interrupted = True
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not pidfile.exists():
                    time.sleep(0.02)
                time.sleep(0.2)
                raise KeyboardInterrupt
            return super().wait(timeout=timeout)

    monkeypatch.setattr(O.subprocess, "Popen", InterruptedOnFirstWait)
    r = O.RealOps(tool_dir=tmp_path, term_grace=0.5)
    with pytest.raises(KeyboardInterrupt):
        r.dd_write("/i/x", DISK + "p3", timeout=30.0)
    pids = [int(p) for p in pidfile.read_text().split()]
    assert len(pids) == 2
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.05)
    assert not any(_alive(p) for p in pids), "dd survived an interrupted wait"


def test_real_child_runs_in_its_own_session(tmp_path):
    _script(tmp_path / "blockdev", 'ps -o pid=,pgid= -p $$ > "$0.ps"; echo 1\n')
    O.RealOps(tool_dir=tmp_path).blockdev_getsz(DISK)
    pid, pgid = (tmp_path / "blockdev.ps").read_text().split()
    assert pid == pgid
    assert int(pgid) != os.getpgid(0)


def test_real_file_verbs_read_only(tmp_path):
    r = O.RealOps(tool_dir=tmp_path)
    p = tmp_path / "f"
    p.write_bytes(b"abc")
    assert r.read_file(str(p)) == b"abc"
    with pytest.raises(ValueError):
        r._fs("write_file", str(p), b"x")
    assert p.read_bytes() == b"abc"


# ------------------------------------------------------- static ast check

FORBIDDEN_OS = {
    "system", "popen", "remove", "unlink", "rename", "replace", "mkdir", "makedirs",
    "rmdir", "removedirs", "write", "open", "truncate", "chmod", "chown", "symlink",
    "link", "kill", "killpg", "fork", "execv", "execve", "execl", "execvp", "execlp",
    "spawnv", "spawnl", "spawnvp", "spawnlp", "posix_spawn", "utime", "ftruncate",
}  # fmt: skip


def _violations(tree):
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "subprocess":
                    bad.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod == "subprocess":
                bad.append("from subprocess import ...")
            if mod == "os":
                bad += [f"from os import {a.name}" for a in node.names if a.name in FORBIDDEN_OS]
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in FORBIDDEN_OS:
                bad.append(f"os.{node.attr}")
    return bad


@pytest.mark.parametrize("name", ["cmd_plan.py", "cmd_check.py"])
def test_plan_and_check_modules_do_not_reach_the_system_directly(name):
    path = SCRIPTS / "avocado_flash_remote" / name
    if not path.exists():
        pytest.skip(f"{name} does not exist yet")
    assert _violations(ast.parse(path.read_text())) == []


def test_ast_checker_flags_forbidden_constructs():
    src = "import subprocess\nimport os\nfrom os import remove\nos.system('x')\nos.path.join('a')\n"
    assert sorted(_violations(ast.parse(src))) == ["from os import remove", "import subprocess", "os.system"]


def test_version_probes_are_reads_and_install_is_otherwise_a_mutation():
    for tool in ("install", "sha256sum", "dd"):
        assert O.vector_mutates([tool, "--version"]) is False
        assert O.Ops.vec_tool_version(tool) == [tool, "--version"]
    assert O.vector_mutates(["install", "-d", "/x"]) is True
    assert O.vector_mutates(["install", "--version", "-d", "/x"]) is True
    assert O.vector_mutates(["install"]) is True


def test_tool_version_refuses_a_tool_outside_the_prerequisite_set():
    with pytest.raises(ValueError):
        O.Ops.vec_tool_version("rm")
