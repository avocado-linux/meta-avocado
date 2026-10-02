"""Behavioural invariants beyond the recorded call log (task 7.2).

Failure injection through the real subprocess plumbing and through the write
state machine, dropped connections, signals to the runner, hostile file
names, a hostile locale, exact exit statuses, and the standing rule that no
injected failure ever leaves the board armed.

Everything runs against stub tools in a temp dir or RecordingOps. Every child
the tests start gets its own session, output goes to files, and only that
child's own process group is ever signalled.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tarfile
import textwrap
import time
from types import SimpleNamespace as NS

import devgraph
import pytest

from avocado_flash_remote import bundle, cli, cmd_check, cmd_plan, cmd_restore, cmd_write, host, layout, runner
from avocado_flash_remote import profile as prof
from avocado_flash_remote import state as statemod
from avocado_flash_remote.host import HostError, HostTimeout, RunResult, StubTransport
from avocado_flash_remote.images import ScanResult
from avocado_flash_remote.ops import FS_READ_KINDS, OpFailed, OpResult, RealOps, RecordingOps, vector_mutates

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent.parent / "avocado_flash_remote"
SHIPPED = PKG / "profiles" / "jetson-agx-orin-j5012.json"
_SERIAL = "0x0badc0de"


def _pin_serial(raw):
    """The shipped profile as an extension would pin it: a serial identity listed in checks."""
    doc = json.loads(raw)
    doc["target"]["identity"] = {"kind": "serial", "value": _SERIAL, "sysfs_attr": "serial"}
    doc["checks"] = list(doc["checks"]) + ["target-identity"]
    return json.dumps(doc).encode()


# Writes need a pinned identity, so the generic good-run profile is the shipped one with a serial.
SHIPPED_BYTES = _pin_serial(SHIPPED.read_bytes())
FIXTURE_BYTES = (PKG / "profiles" / "fixture-none.json").read_bytes()

DEV = "/dev/mmcblk0"
STAGE = "/run/emmc-test-images"
RUN_ID = "run-0001"
MACHINE_ID = "0123456789abcdef0123456789abcdef"
LABEL = "UEFI eMMC Device"
ORDER = "0001,0002,0000,0003,0004"
ENTRY = "0002"
# The firmware's own storage entry (full device path) is already listed; nothing creates it.
EFI_PRE = (
    f"BootCurrent: 0001\nTimeout: 5 seconds\nBootOrder: {ORDER}\nBoot0000* UEFI Shell\nBoot0001* UEFI NVMe\n"
    f"Boot{ENTRY}* {LABEL}\tVenHw(1e5a432c-0000-0000-0000-000000000000)/SD(0)\n"
)
EFI_AFTER = EFI_PRE
EFI_FINAL = EFI_PRE + f"BootNext: {ENTRY}\n"
NVME_ARG = "module_blacklist=nvme,nvme_core,pcie_tegra194"
BLANK = OpResult(rc=1, stderr=f"sfdisk: {DEV}: does not contain a recognized partition table\n")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def boot_header(arg=NVME_ARG):
    hdr = bytearray(2048)
    hdr[0:8] = b"ANDROID!"
    hdr[40:44] = (0).to_bytes(4, "little")
    cmd = f"console=ttyS0 {arg} quiet".encode()
    hdr[64 : 64 + len(cmd)] = cmd
    return bytes(hdr)


# ------------------------------------------------------------ process helpers


def alive(pid):
    """True while the pid is a live process; a zombie counts as gone."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


def wait_until(pred, timeout=15.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def kill_own_group(child):
    """Reap a child this test started; signals only its own group, never another."""
    if child.poll() is None:
        try:
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
        except ProcessLookupError:
            pass
        child.wait()


def spawn(cmd, tmp_path, name):
    out = open(tmp_path / f"{name}.out", "wb")
    err = open(tmp_path / f"{name}.err", "wb")
    child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    out.close()
    err.close()
    assert os.getpgid(child.pid) == child.pid
    return child


def make_tool(tool_dir, name, body):
    p = pathlib.Path(tool_dir) / name
    p.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    p.chmod(0o755)
    return p


@pytest.fixture
def tools(tmp_path):
    d = tmp_path / "tools"
    d.mkdir()
    return d


def real_ops(tools, **kw):
    kw.setdefault("term_grace", 0.5)
    return RealOps(tools, **kw)


# ======================================================================= 1
# Subprocess failures through RealOps with stub tools


def test_real_nonzero_exit_is_opfailed_with_rc_and_stderr(tools):
    make_tool(tools, "uname", "echo 'disk on fire' >&2\nexit 3\n")
    with pytest.raises(OpFailed) as ei:
        real_ops(tools).uname_r()
    assert ei.value.rc == 3
    assert ei.value.stderr == "disk on fire\n"
    assert ei.value.vector == ["uname", "-r"]


def test_real_missing_tool_is_opfailed_rc_none(tools):
    with pytest.raises(OpFailed) as ei:
        real_ops(tools).uname_r()
    assert ei.value.rc is None
    assert "not found" in ei.value.stderr


def test_real_timeout_kills_own_group_and_leaves_no_orphan(tools, tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    make_tool(tools, "uname", f"sleep 300 &\necho $! > {pidfile}\nwait\n")
    bystander = subprocess.Popen(
        ["sleep", "300"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )  # fmt: skip
    try:
        t0 = time.monotonic()
        with pytest.raises(OpFailed) as ei:
            real_ops(tools).uname_r(timeout=0.5)
        assert time.monotonic() - t0 < 10
        assert ei.value.rc is None
        assert "timed out after 0.5s" in ei.value.stderr
        gpid = int(pidfile.read_text())
        assert wait_until(lambda: not alive(gpid)), "the stub's own child outlived the timeout"
        assert alive(bystander.pid), "a process outside the stub's group was killed"
    finally:
        kill_own_group(bystander)


def test_real_timeout_with_a_term_ignoring_stub_is_still_killed(tools, tmp_path):
    pidfile = tmp_path / "stub.pid"
    make_tool(tools, "uname", f"trap '' TERM\necho $$ > {pidfile}\nwhile :; do sleep 1; done\n")
    with pytest.raises(OpFailed) as ei:
        real_ops(tools, term_grace=0.3).uname_r(timeout=0.5)
    assert ei.value.rc is None
    assert wait_until(lambda: not alive(int(pidfile.read_text())))


def test_real_one_mib_of_stderr_noise_on_success_does_not_deadlock(tools):
    make_tool(tools, "uname", "head -c 1048576 /dev/zero | tr '\\000' x >&2\necho 5.15.0\n")
    t0 = time.monotonic()
    res = real_ops(tools)._run(["uname", "-r"])
    assert time.monotonic() - t0 < 20
    assert res.rc == 0
    assert res.text == "5.15.0\n"
    assert len(res.stderr) == 1048576


def test_real_dd_stderr_noise_with_digest_still_hashes_stdout(tools):
    make_tool(tools, "dd", "printf 'hello' \necho '1+0 records in' >&2\necho '1+0 records out' >&2\n")
    digest = real_ops(tools).dd_sha256("/dev/x", "4M", 5)
    assert digest == hashlib.sha256(b"hello").hexdigest()


def test_real_exit_141_is_reported_exactly(tools):
    make_tool(tools, "uname", "yes | head -c 1 >/dev/null\nexit 141\n")
    with pytest.raises(OpFailed) as ei:
        real_ops(tools).uname_r()
    assert ei.value.rc == 141


def test_real_death_by_sigpipe_is_reported_as_minus_13(tools):
    make_tool(tools, "uname", "kill -PIPE $$\nsleep 5\n")
    with pytest.raises(OpFailed) as ei:
        real_ops(tools).uname_r()
    assert ei.value.rc == -signal.SIGPIPE


def test_real_short_read_is_not_detected_by_the_ops_layer_only_by_digest(tools):
    # The module's rule: RealOps never inspects dd's record counts. A short
    # read is caught because its sha256 differs from the planned one.
    make_tool(tools, "dd", "printf 'abc'\necho '0+1 records in' >&2\necho '0+1 records out' >&2\n")
    expected_full = hashlib.sha256(b"abcdefghij").hexdigest()
    got = real_ops(tools).dd_sha256("/dev/x", "4M", 10)
    assert got == hashlib.sha256(b"abc").hexdigest()
    assert got != expected_full


def test_real_short_write_on_stdin_feed_is_reported_by_the_tool_rc(tools):
    # A tool that consumes only part of stdin and fails: the failure surfaces
    # with the tool's rc (stdin is a temp file, so there is no EPIPE to hit).
    make_tool(tools, "sfdisk", "head -c 4 >/dev/null\necho 'short write' >&2\nexit 1\n")
    with pytest.raises(OpFailed) as ei:
        real_ops(tools).sfdisk_write(DEV, "label: gpt\n" * 1000)
    assert ei.value.rc == 1 and "short write" in ei.value.stderr


# ======================================================================= 2
# run_write failure injection at every step


class Env:
    """One scripted board plus a plan record for it (copied from test_cmd_write)."""

    def __init__(self, tmp_path, profile_bytes=SHIPPED_BYTES):
        self.tmp = pathlib.Path(tmp_path)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.profile = prof.load_profile_bytes(profile_bytes)
        self.phash = prof.profile_hash(profile_bytes)
        self.state_dir = self.tmp / "state"
        self.efivars = self.tmp / "efivars"
        self.efivars.mkdir(exist_ok=True)
        (self.efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(bytes([7, 0, 0, 0, 0]))
        self.scans = {}
        for img in self.profile.images.values():
            size = 4096 + 512 * len(self.scans)
            self.scans.setdefault(img.file, ScanResult(size, sha("content-" + img.file), False, (1, 1, size, 1)))
        self.sizes = {role: self.scans[img.file].size for role, img in self.profile.images.items()}
        self.table = layout.sfdisk_input(self.profile.layout.params, DEV)
        self.plan = {
            "schema_version": 1,
            "run_id": RUN_ID,
            "profile_hash": self.phash,
            "board_identity": {"machine_id": MACHINE_ID, "device_serial": _SERIAL},
            "device": DEV,
            "image_hashes": {r: self.scans[i.file].sha256 for r, i in self.profile.images.items()},
            "image_sizes": {r: self.scans[i.file].size for r, i in self.profile.images.items()},
            "table_hash": hashlib.sha256(self.table.encode()).hexdigest(),
            "arm": {"strategy": "uefi-bootnext", "label": LABEL, "preexisting_boot_order": ORDER,
                    "preexisting_next": "", "entry_number": ENTRY, "next_armed": False},
            "created_utc": "2026-01-01T00:00:00Z",
        }  # fmt: skip

    def node(self, role):
        return layout.partition_node(DEV, self.profile.images[role].partition)

    def src(self, role):
        return f"{STAGE}/{self.profile.images[role].file}"

    def dd_key(self, role):
        return f"dd if={self.src(role)} of={self.node(role)} bs=1M conv=fsync status=none"

    def readback_key(self, role):
        return f"dd if={self.node(role)} bs=4M iflag=count_bytes count={self.sizes[role]} status=none"

    def guard_key(self, name):
        num = next(p["number"] for p in self.profile.layout.params["table"] if p["name"] == name)
        return f"dd if={layout.partition_node(DEV, num)} bs=2048 count=1 status=none"

    def script(self, **over):
        names = sorted({i.file for i in self.profile.images.values()})
        s = {
            f"lsblk -rn -o TYPE {DEV}": "disk\n",
            f"lsblk -rn -o NAME,TYPE {DEV}": "mmcblk0 disk\n",
            f"blockdev --getro {DEV}": "0\n",
            f"blockdev --getsz {DEV}": f"{self.profile.target.sectors}\n",
            f"sfdisk --dump {DEV}": [BLANK, BLANK, self.table],
            "findmnt -rn -o SOURCE": "/dev/nvme0n1p1\n/dev/nvme0n1p2\n",
            "findmnt -no SOURCE -T /": "/dev/nvme0n1p2\n",
            f"findmnt -no SOURCE -T {STAGE}": "tmpfs\n",
            "findmnt -no SOURCE -T /etc/ssh": "/dev/nvme0n1p2\n",
            "read_file /sys/block/mmcblk0/device/serial": _SERIAL + "\n",
            "efibootmgr --help": "Usage: efibootmgr [-c|-C] [-d DISK]\n  -C | --create-only\n",
            "efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, EFI_FINAL],
            f"findmnt -no OPTIONS {self.efivars}": "rw,nosuid,nodev,noexec,relatime\n",
            f"read_file {STAGE}/MANIFEST.hashes": "".join(f"{'a' * 64}  {n}\n" for n in names),
            "sha256sum --strict -c MANIFEST.hashes": "".join(f"{n}: OK\n" for n in names),
            f"df -Pk {STAGE}": f"Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 100 1 12156576 1% {STAGE}\n",
            f"findmnt -no FSTYPE -T {STAGE}": "tmpfs\n",
            "uname -r": "5.15.148-tegra\n",
            "docker ps -q": "a\n",
            "read_file /sys/block/mmcblk0/device/life_time": "0x01 0x01\n",
            "read_file /sys/block/mmcblk0/device/pre_eol_info": "0x01\n",
            "read_file /etc/machine-id": MACHINE_ID + "\n",
            f"blkid -p -s TYPE -o value {self.node('esp')}": "vfat\n",
            f"efibootmgr -n {ENTRY}": 0,
        }
        for n in names:
            s[f"stat -c %s {STAGE}/{n}"] = "10\n"
        for p in self.profile.layout.params["table"]:
            s[f"blockdev --getsize64 {layout.partition_node(DEV, p['number'])}"] = f"{p['size'] * 512}\n"
        for role in self.profile.images:
            s[self.readback_key(role)] = OpResult(digest=self.plan["image_hashes"][role])
        for name in ("A_kernel", "B_kernel"):
            s[self.guard_key(name)] = boot_header()
        s.update(devgraph.standard_script())
        s.update(over)
        return s

    def run(self, ops=None, *, script=None, plan="default", confirm=None, assume_yes=False, writer=None,
            scanner=None, reverifier=None, **kw):  # fmt: skip
        ops = ops if ops is not None else RecordingOps(script if script is not None else self.script())
        plan_obj = self.plan if plan == "default" else plan
        lines = []
        res = cmd_write.run_write(
            ops, self.profile, self.phash,
            staging_dir=STAGE, state_dir=self.state_dir, run_dir=str(self.tmp / "run"),
            plan_loader=lambda: plan_obj, record_writer=writer or (lambda *a: "x"),
            confirm=confirm if confirm is not None else (lambda dev: dev),
            assume_yes=assume_yes, efivars_dir=str(self.efivars), out=lines.append,
            scanner=scanner or (lambda path: self.scans[path.rsplit("/", 1)[-1]]),
            reverifier=reverifier or (lambda path, scan: None),
            stat_fn=lambda path: self.scans[path.rsplit("/", 1)[-1]].identity,
            hash_fn=lambda path: self.scans[path.rsplit("/", 1)[-1]].sha256,
            **kw,
        )  # fmt: skip
        return res, ops


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def mutations(ops):
    return [c for c in ops.calls if (c.kind == "exec" and vector_mutates(c.vector)) or (c.kind == "fs" and c.vector[0] not in FS_READ_KINDS)]


def lock_is_free(env):
    with statemod.OnBoardLock(env.state_dir / "lock", run_id="probe"):
        pass


@pytest.fixture(scope="module")
def good_mutations(tmp_path_factory):
    e = Env(tmp_path_factory.mktemp("good"))
    res, ops = e.run()
    assert res.exit_code == 0, res.lines
    return [c.line for c in mutations(ops)]


N_ROLES = len(prof.load_profile_bytes(SHIPPED_BYTES).images)
ROLE_NAMES = list(prof.load_profile_bytes(SHIPPED_BYTES).images)


def _point_ids():
    ids = ["sfdisk-write", "table-no-label", "table-partition-size-wrong", "table-partition-missing"]
    for r in ROLE_NAMES:
        ids += [f"dd-{r}", f"readback-fails-{r}", f"readback-short-{r}"]
    ids += ["esp-not-vfat", "guard-A", "guard-B", "arm-bootorder-moved", "arm-next-fails"]
    return ids


FAIL_POINTS = _point_ids()
TOLERATED_POINTS = ["settle-fails", "evidence-write-fails"]
# 4 table + 3 per image + 5 esp/guard/arm + 2 tolerated; a removed point fails here. 33 -> 32 in task 5.36:
# the arm-create-fails point is gone because the tool no longer creates a boot entry.
INJECTION_POINT_COUNT = 32


def test_injection_point_count_is_pinned():
    assert N_ROLES == 7
    assert len(FAIL_POINTS) + len(TOLERATED_POINTS) == INJECTION_POINT_COUNT
    assert len(set(FAIL_POINTS)) == len(FAIL_POINTS)


def make_point(env, pid, good):
    """(script overrides, k) where k = how many of the good run's mutating calls may have happened."""
    d = layout.partition_node
    if pid == "sfdisk-write":
        return {f"sfdisk {DEV}": OpFailed(["sfdisk", DEV], 1, "boom")}, 1
    if pid == "table-no-label":
        return {f"sfdisk --dump {DEV}": [BLANK, BLANK, BLANK]}, 2
    if pid == "table-partition-size-wrong":
        return {f"blockdev --getsize64 {d(DEV, 3)}": "123\n"}, 2
    if pid == "table-partition-missing":
        node = d(DEV, 1)
        kept = [ln for ln in env.table.splitlines() if not ln.startswith(node + " ") and not ln.startswith(node + ":")]
        assert len(kept) == len(env.table.splitlines()) - 1
        return {f"sfdisk --dump {DEV}": [BLANK, BLANK, "\n".join(kept) + "\n"]}, 2
    for j, r in enumerate(ROLE_NAMES):
        if pid == f"dd-{r}":
            return {env.dd_key(r): OpFailed(["dd"], 1, "io error")}, 3 + j
        if pid == f"readback-fails-{r}":
            return {env.readback_key(r): OpFailed(["dd"], 5, "i/o error")}, 3 + j
        if pid == f"readback-short-{r}":
            short = OpResult(digest=sha("short"), stderr="0+1 records in\n0+1 records out\n")
            return {env.readback_key(r): short}, 3 + j
    n = 2 + N_ROLES
    if pid == "esp-not-vfat":
        return {f"blkid -p -s TYPE -o value {env.node('esp')}": "ext4\n"}, n
    if pid == "guard-A":
        return {env.guard_key("A_kernel"): boot_header("quiet")}, n
    if pid == "guard-B":
        return {env.guard_key("B_kernel"): boot_header("quiet")}, n
    if pid == "arm-bootorder-moved":
        return {"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE.replace(ORDER, "0002,0001")]}, n
    assert good[n] == f"efibootmgr -n {ENTRY}" and len(good) == n + 1
    if pid == "arm-next-fails":
        return {f"efibootmgr -n {ENTRY}": OpFailed(["efibootmgr", "-n", ENTRY], 1, "x")}, n + 1
    raise AssertionError(pid)


def never_armed_unless_next_issued(ops, res_state):
    """Scan the log: 'armed' only if -n was issued, no creating option ever, and no dd after the arm call."""
    log = ops.log
    nexts = [i for i, ln in enumerate(log) if ln.startswith("efibootmgr -n ")]
    assert not [ln for ln in log if ln.startswith("efibootmgr") and set(ln.split()[1:]) & {"-C", "-B", "-b", "-o", "-O", "-c"}]
    phases = [p["phase"] for p in res_state.data["phases_done"]]
    if "armed" in phases:
        assert nexts, "state says armed but no efibootmgr -n was ever issued"
        assert res_state.data["armed"]["entry_number"]
    first_arm = min(nexts, default=len(log))
    for i, ln in enumerate(log):
        if ln.startswith("dd ") and i > first_arm:
            raise AssertionError(f"dd after the first arm call: {ln}")


def assert_failed_point(env, res, ops, k, good, pid=None):
    assert res.exit_code == 1, res.lines
    r = statemod.load_state(env.state_dir)
    assert r.status == "ok"
    st = r.state
    # The arm step that began mutating boot variables stays in `arming` (armed state unknown).
    stays_arming = pid == "arm-next-fails"
    want = "arming" if stays_arming else "failed"
    assert st.phase == want and res.final_phase == want
    assert st.data["error"]
    lock_is_free(env)
    assert [c.line for c in mutations(ops)] == good[:k], "a mutating call ran past the failure point"
    log = ops.log
    assert any(ln.startswith("efibootmgr -n ") for ln in log) == (k >= len(good))
    never_armed_unless_next_issued(ops, st)
    phases = [p["phase"] for p in st.data["phases_done"]]
    assert ("armed" in phases) == (k == len(good) and not stays_arming)
    text = "\n".join(res.lines)
    assert "recovery:" in text
    if stays_arming:
        assert "DO NOT REBOOT" in text and "the board was not armed" not in text
    else:
        assert ("the board WAS armed" in text) == (k == len(good))
        assert ("the board was not armed" in text) == (k != len(good))


@pytest.mark.parametrize("pid", FAIL_POINTS)
def test_injected_failure_records_failed_never_arms_and_blocks_rerun(env, good_mutations, pid):
    over, k = make_point(env, pid, good_mutations)
    res, ops = env.run(script=env.script(**over))
    assert_failed_point(env, res, ops, k, good_mutations, pid)
    res2, ops2 = env.run()
    assert res2.exit_code == 1
    assert mutations(ops2) == []
    text2 = "\n".join(res2.lines)
    assert ("previous run is not finished" if pid == "arm-next-fails" else "already used") in text2


@pytest.mark.parametrize("pid", FAIL_POINTS)
def test_injected_failure_whose_failed_record_cannot_be_written_leaves_last_phase(
    env, good_mutations, monkeypatch, pid
):
    real = cmd_write.transition

    def flaky(state, phase, **kw):
        if phase == "failed":
            raise OSError("disk went away")
        return real(state, phase, **kw)

    monkeypatch.setattr(cmd_write, "transition", flaky)
    over, k = make_point(env, pid, good_mutations)
    res, ops = env.run(script=env.script(**over))
    assert res.exit_code == 1
    r = statemod.load_state(env.state_dir)
    assert r.status == "ok", "state must stay parseable"
    assert r.state.phase in statemod.PHASES and r.state.phase not in statemod.TERMINAL
    assert res.final_phase == r.state.phase
    lock_is_free(env)
    assert [c.line for c in mutations(ops)] == good_mutations[:k]
    never_armed_unless_next_issued(ops, r.state)
    res2, ops2 = env.run()
    assert res2.exit_code == 1 and mutations(ops2) == []
    text = "\n".join(res2.lines)
    assert "previous run is not finished" in text and "Permitted recovery" in text and RUN_ID in text


def test_tolerated_injection_settle_failure_still_completes(env, good_mutations):
    res, ops = env.run(script=env.script(**{"udevadm settle": OpFailed(["udevadm", "settle"], 127, "not found")}))
    assert res.exit_code == 0 and res.final_phase == "complete"
    assert "udevadm settle failed" in "\n".join(res.lines)
    assert [c.line for c in mutations(ops)] == good_mutations
    lock_is_free(env)


def test_tolerated_injection_evidence_write_failure_does_not_change_the_outcome(env, good_mutations):
    def writer(*a):
        raise OSError("read-only fs")

    res, ops = env.run(writer=writer)
    assert res.exit_code == 0 and res.final_phase == "complete"
    assert "cannot write write.json" in "\n".join(res.lines)
    assert [c.line for c in mutations(ops)] == good_mutations


def test_evidence_write_failure_on_a_failed_run_keeps_the_failed_outcome(env):
    def writer(*a):
        raise OSError("read-only fs")

    res, ops = env.run(script=env.script(**{env.dd_key("dtb"): OpFailed(["dd"], 1, "io")}), writer=writer)
    assert res.exit_code == 1 and res.final_phase == "failed"
    assert statemod.load_state(env.state_dir).state.phase == "failed"


def test_aggregate_no_arm_call_follows_any_earlier_failure(tmp_path, good_mutations):
    seen = 0
    for pid in FAIL_POINTS:
        e = Env(tmp_path / pid)
        over, k = make_point(e, pid, good_mutations)
        res, ops = e.run(script=e.script(**over))
        assert res.exit_code == 1
        seen += 1
        if k < len(good_mutations):
            assert not [ln for ln in ops.log if ln.startswith("efibootmgr -n")], pid
        assert [c.line for c in mutations(ops)] == good_mutations[:k], pid
    assert seen == len(FAIL_POINTS) == 30


# ======================================================================= 3
# Dropped SSH connection


class Board:
    """Scripted board: answers the host's calls the way the runner would (copied, trimmed)."""

    def __init__(self, tmp_path, *, write_phase="complete", corrupt_write=False):
        self.tmp = tmp_path / "board"
        self.tmp.mkdir()
        self.write_phase = write_phase
        self.corrupt_write = corrupt_write
        self.staged = False
        self.phase = None
        self.run_id = None
        self.requests = {}
        self.runs = []
        self.records = {}
        self.status_script = None  # phases or exceptions consumed by status polls
        self.write_exc = None
        self.nonce = "0" * 16
        self.stub = StubTransport(self.handle)

    def _records(self, name, with_write):
        from avocado_flash_remote import evidence

        d = self.tmp / name
        d.mkdir()
        rs = evidence.RecordSet(
            d, "t", "1", "p" * 64, {"boot.img": "a" * 64}, {"id": "x"}, [],
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        )  # fmt: skip
        rs.add("plan.json", {"run_id": self.run_id})
        if with_write:
            rs.add("write.json", {"ok": True})
        rs.finalize("runner-complete")
        if with_write and self.corrupt_write:
            (d / "write.json").write_bytes(b'{"ok": false}\n')
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for p in sorted(d.iterdir()):
                tf.add(str(p), arcname="./" + p.name)
        return buf.getvalue()

    def handle(self, argv, stdin, sudo):
        argv = list(argv)
        if argv[:3] == ["sudo", "-n", "true"] and not sudo:
            return RunResult(0)
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        elif argv[:4] == ["sudo", "-S", "-p", ""]:
            argv = argv[4:]
        if argv[:2] == ["tar", "-C"] and argv[-2:] == ["-xf", "-"]:
            self.staged = True
            return RunResult(0)
        if argv[:2] == ["tar", "-C"] and "-cf" in argv:
            return RunResult(0, self.records[argv[2]])
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n")
        if argv[0] == "sh" and argv[2:3] and argv[2].startswith("d="):
            return RunResult(0, b"Filesystem 1024-blocks Used Available Capacity Mounted on\ntmpfs 9 1 999999 1% /run\n")
        if argv[0] == "sh" and "cat >" in argv[2]:
            self.requests[argv[-1]] = json.loads(stdin)
            return RunResult(0)
        if argv[0] == "sh" and "exit 3" in argv[2]:
            # The runner's marker probe: `accepted` carries this invocation's nonce, there is no verdict yet.
            if argv[-1].endswith("/accepted"):
                return RunResult(0, f"4242\nnonce={self.nonce}\n".encode())
            return RunResult(3)
        if argv[0] == "test":
            return RunResult(0 if self.staged else 1)
        if argv[0] == "tail":
            return RunResult(0, b"runner log line\n")
        if len(argv) >= 3 and argv[1] == "-c":
            return RunResult(0, b"OK 3.12.1\n")
        if argv[0] == "python3":
            return self._runner(argv)
        return RunResult(0)

    def _runner(self, argv):
        sub = argv[2]
        req = self.requests[argv[4]]
        self.runs.append((sub, req, "--detach" in argv))
        if sub == "plan":
            self.run_id = req["run_id"]
            self.records[req["run_dir"]] = self._records("plan", False)
            self.phase = "planned"
            return RunResult(0, b"plan: ok\n")
        if sub == "write":
            self.nonce = req["invocation_nonce"]
            if self.write_exc is not None:
                raise self.write_exc
            self.records[req["run_dir"]] = self._records("write", True)
            self.phase = self.write_phase
            return RunResult(0, f"detached: run={self.run_id} log=x\n".encode())
        if sub == "status":
            if self.status_script:
                item = self.status_script.pop(0)
                if isinstance(item, BaseException):
                    raise item
                self.phase = item
            return RunResult(0, f"status: {self.phase} run={self.run_id} recovery=none-recorded\n".encode())
        return RunResult(0, b"ok\n")

    def factory(self, host_arg, ssh_opts, batch):
        return self.stub


@pytest.fixture
def images(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    lines = []
    for name in ("boot.img", "esp.img", "data.img"):
        data = (name.encode() + b"-payload") * 50
        (d / name).write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (d / "MANIFEST.hashes").write_text("".join(lines))
    return d


def cli_args(images, tmp_path, sub, *extra):
    return [sub, "--board", "fixture-none", "--images", str(images), "--evidence-dir", str(tmp_path / "ev"),
            "--host", "op@board.local", *extra]  # fmt: skip


def cli_run(argv, board, **kw):
    lines = []
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("confirm", lambda prompt: "/dev/loop-fixture")
    kw.setdefault("poll_interval", 1.0)
    rc = cli.main(argv, transport_factory=board.factory, out=lines.append, **kw)
    return rc, "\n".join(map(str, lines))


def stage_and_plan(images, tmp_path, board):
    assert cli_run(cli_args(images, tmp_path, "stage"), board)[0] == 0
    assert cli_run(cli_args(images, tmp_path, "plan"), board)[0] == 0
    return sorted(p.name for p in (tmp_path / "ev").iterdir() if p.is_dir())[0]


def test_dropped_connection_while_polling_reconciles_and_reports_failed_phase(images, tmp_path):
    board = Board(tmp_path)
    rid = stage_and_plan(images, tmp_path, board)
    board.status_script = [HostTimeout("ssh to op@board.local timed out after 120s"), HostError("connection reset"), "failed"]
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert text.count("connection problem, will retry") == 2
    assert "write NOT COMPLETE: the board ended in phase failed" in text
    assert "write COMPLETE" not in text
    assert [r[0] for r in board.runs].count("status") == 3


def test_dropped_connection_that_never_returns_is_not_complete(images, tmp_path):
    board = Board(tmp_path)
    rid = stage_and_plan(images, tmp_path, board)
    board.status_script = [HostTimeout("timed out")] * 50
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid, "--wait-seconds", "3"), board)
    assert rc == 1
    assert "write still in progress after 3s" in text
    assert "write COMPLETE" not in text


def test_dropped_connection_then_in_flight_phase_reports_still_in_progress(images, tmp_path):
    board = Board(tmp_path)
    rid = stage_and_plan(images, tmp_path, board)
    board.status_script = ["image-writing", HostError("reset"), "image-writing"] + [HostError("reset")] * 20
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid, "--wait-seconds", "5"), board)
    assert rc == 1
    assert "write still in progress" in text and "write COMPLETE" not in text


def test_dropped_connection_then_complete_phase_with_corrupt_records_is_not_complete(images, tmp_path, capsys):
    board = Board(tmp_path, corrupt_write=True)
    rid = stage_and_plan(images, tmp_path, board)
    board.status_script = [HostTimeout("timed out"), "complete"]
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "records not verified" in text + capsys.readouterr().err


def test_dropped_connection_then_complete_phase_with_good_records_completes(images, tmp_path):
    board = Board(tmp_path)
    rid = stage_and_plan(images, tmp_path, board)
    board.status_script = [HostTimeout("timed out"), "complete"]
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 0 and "write COMPLETE" in text


def test_connection_dropped_on_the_detached_write_call_itself_is_exit_1_not_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    rid = stage_and_plan(images, tmp_path, board)
    board.write_exc = HostTimeout("ssh to op@board.local timed out after 120s")
    rc, text = cli_run(cli_args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "timed out" in capsys.readouterr().err


def test_detached_runner_grandchild_outlives_its_parent(tmp_path):
    info = bundle.build_bundle(FIXTURE_BYTES, tmp_path / "r.pyz", "t")
    req = tmp_path / "req.json"
    req.write_text(json.dumps({
        "staging_dir": "/stage", "state_dir": str(tmp_path / "state"), "run_dir": str(tmp_path / "state" / "r1" / "records"),
        "run_id": "r1", "plan_path": str(tmp_path / "plan.json"), "invocation_nonce": "f6" * 8, "tool_version": "t",
    }))  # fmt: skip
    started, done = tmp_path / "started.json", tmp_path / "done"
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import json, os, sys, time
        sys.path.insert(0, {str(PKG.parent)!r})
        from avocado_flash_remote import runner

        def stub(*a, **k):
            with open({str(started)!r}, "w") as f:
                json.dump({{"pid": os.getpid(), "pgid": os.getpgid(0), "sid": os.getsid(0)}}, f)
            time.sleep(1.5)
            open({str(done)!r}, "w").write("done")
            return type("R", (), {{"exit_code": 0}})()

        import dataclasses
        _real = runner.load_profile_bytes
        runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={str(tmp_path / "state")!r})
        runner.run_write = stub
        sys.exit(runner.main(["write", "--request", {str(req)!r}, "--detach"], archive={str(info.path)!r}))
    """))
    child = spawn([sys.executable, str(driver)], tmp_path, "driver")
    grand = None
    try:
        assert child.wait(timeout=30) == 0, (tmp_path / "driver.err").read_text()
        assert wait_until(started.exists)
        m = json.loads(started.read_text())
        grand = m["pid"]
        assert grand != child.pid
        # double fork: the grandchild sits in a session its (exited) parent created, and leads nothing
        assert m["sid"] == m["pgid"] != grand, "grandchild must not be a session leader"
        assert m["sid"] != child.pid, "grandchild must have left the launcher's session"
        assert child.poll() == 0
        assert alive(grand) and not done.exists()
        assert wait_until(done.exists, timeout=15)
    finally:
        kill_own_group(child)
        if grand is not None and alive(grand):
            try:
                os.kill(grand, signal.SIGKILL)  # the process this test started, by pid only
            except ProcessLookupError:
                pass


# ======================================================================= 4
# Signals to the runner


class BlockingOps(RecordingOps):
    """RecordingOps whose first dd write blocks, after marking that it did."""

    def __init__(self, script, marker, log_path):
        super().__init__(script)
        self.marker = marker
        self.log_path = log_path

    def _exec(self, vec, **kw):
        res = super()._exec(vec, **kw)
        if vec[0] == "dd" and any(a.startswith("of=") for a in vec):
            pathlib.Path(self.marker).write_text("blocking")
            time.sleep(120)
        return res

    def dump(self):
        pathlib.Path(self.log_path).write_text(json.dumps(self.log))


def _runner_signal_setup(tmp_path):
    e = Env(tmp_path)
    info = bundle.build_bundle(SHIPPED_BYTES, tmp_path / "r.pyz", "t")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(e.plan))
    req = tmp_path / "req.json"
    req.write_text(json.dumps({
        "staging_dir": STAGE, "state_dir": str(e.state_dir), "run_dir": str(e.state_dir / "r1" / "records"),
        "run_id": RUN_ID, "plan_path": str(plan), "assume_yes": True, "efivars_dir": str(e.efivars),
        "profile_hash": e.phash, "tool_version": "t",
    }))  # fmt: skip
    marker, logp = tmp_path / "blocking", tmp_path / "ops-log.json"
    driver = tmp_path / "sigdriver.py"
    driver.write_text(textwrap.dedent(f"""
        import pathlib, sys
        sys.path.insert(0, {str(PKG.parent)!r})
        sys.path.insert(0, {str(HERE)!r})
        import test_invariants as T
        from avocado_flash_remote import cmd_write, runner

        env = T.Env(pathlib.Path({str(tmp_path)!r}))
        ops = T.BlockingOps(env.script(), {str(marker)!r}, {str(logp)!r})

        def wrapper(real, profile, phash, **kw):
            kw["scanner"] = lambda p: env.scans[p.rsplit("/", 1)[-1]]
            kw["reverifier"] = lambda p, s: None
            kw["stat_fn"] = lambda p: env.scans[p.rsplit("/", 1)[-1]].identity
            kw["hash_fn"] = lambda p: env.scans[p.rsplit("/", 1)[-1]].sha256
            kw["file_reader"] = lambda p: T.boot_header()
            return cmd_write.run_write(ops, profile, phash, **kw)

        import dataclasses
        _real = runner.load_profile_bytes
        runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={str(tmp_path / "state")!r})
        runner.run_write = wrapper
        try:
            rc = runner.main(["write", "--request", {str(req)!r}], archive={str(info.path)!r})
        finally:
            ops.dump()
        sys.exit(rc)
    """))
    return e, driver, marker, logp


@pytest.mark.parametrize("sig,expected_rc", [(signal.SIGINT, 130), (signal.SIGTERM, -signal.SIGTERM)])
def test_signal_to_the_runner_leaves_parseable_state_and_a_free_lock(tmp_path, sig, expected_rc):
    e, driver, marker, logp = _runner_signal_setup(tmp_path)
    child = spawn([sys.executable, str(driver)], tmp_path, "sig")
    try:
        assert wait_until(marker.exists, timeout=30), (tmp_path / "sig.err").read_text()
        assert os.getpgid(child.pid) == child.pid
        os.kill(child.pid, sig)  # only the child we started, by pid
        rc = child.wait(timeout=20)
    finally:
        kill_own_group(child)
    assert rc == expected_rc, (tmp_path / "sig.err").read_text()
    r = statemod.load_state(e.state_dir)
    assert r.status == "ok"
    if sig == signal.SIGINT:
        # KeyboardInterrupt path: cmd_write records failed, the runner maps it to 130
        assert r.state.phase == "failed"
        assert r.state.data["error"] == "KeyboardInterrupt"
        log = json.loads(logp.read_text())
    else:
        # SIGTERM has no handler: the process dies where it stands and the last
        # durable phase is what the next session sees (not terminal => recovery).
        assert r.state.phase == "image-writing"
        assert not logp.exists()
        with pytest.raises(statemod.RerunRefused, match="Permitted recovery"):
            statemod.check_rerun_allowed(e.state_dir)
        log = None
    lock_is_free(e)
    if log is not None:
        assert not [ln for ln in log if ln.startswith("efibootmgr -n")]
    assert "armed" not in [p["phase"] for p in r.state.data["phases_done"]]


# ======================================================================= 5
# Unusual file names

BAD_NAMES = ["-rf.img", "-", "a/b.img", "../x.img", "..", ".", "a\\b.img", "/etc/passwd"]
ODD_ALLOWED = ["with space.img", "a'b.img", 'a"b.img', ";rm -rf x", "образ-é.img", "line\nbreak.img", "$(id).img", "*.img"]


def profile_with_file(name):
    doc = json.loads(SHIPPED_BYTES)
    doc["images"]["dtb"]["file"] = name
    return json.dumps(doc).encode()


@pytest.mark.parametrize("name", BAD_NAMES)
def test_profile_loader_rejects_separators_dots_and_leading_dash(name):
    with pytest.raises(prof.ProfileError, match="plain file name"):
        prof.load_profile_bytes(profile_with_file(name))


@pytest.mark.parametrize("name", ODD_ALLOWED)
def test_profile_loader_accepts_odd_but_separator_free_names(name):
    p = prof.load_profile_bytes(profile_with_file(name))
    assert p.images["dtb"].file == name


@pytest.mark.parametrize("name", ODD_ALLOWED + ["-rf.img"])
def test_host_manifest_gate_is_stricter_and_rejects_them_all(tmp_path, name):
    d = tmp_path / "imgs"
    d.mkdir()
    try:
        (d / name).write_bytes(b"x")
    except (OSError, ValueError):
        pass
    (d / "MANIFEST.hashes").write_text(f"{'a' * 64}  {name}\n")
    with pytest.raises(HostError, match="unsafe file name|unparseable|missing"):
        host._parse_manifest(d)


ODD_E2E = ["with space.img", "a'b.img", 'a"b.img', ";rm -rf x.img", "образ-é.img", "$(id).img"]


@pytest.mark.parametrize("name", ODD_E2E)
def test_odd_image_name_stays_one_argv_element_through_a_whole_write(tmp_path, name):
    e = Env(tmp_path, profile_with_file(name))
    res, ops = e.run()
    assert res.exit_code == 0, res.lines
    dtb_src = f"{STAGE}/{name}"
    dd = [c.vector for c in mutations(ops) if c.vector[0] == "dd" and f"if={dtb_src}" in c.vector]
    assert len(dd) == 1
    assert len(dd[0]) == 6  # dd if= of= bs= conv= status=: no shell splitting happened
    assert dd[0][1] == f"if={dtb_src}"
    assert dd[0][2] == f"of={e.node('dtb')}"
    for c in ops.calls:
        assert isinstance(c.vector, list) and all(isinstance(a, str) for a in c.vector)


@pytest.mark.parametrize("name", ODD_ALLOWED)
def test_real_ops_passes_odd_names_as_single_argv_elements(tools, tmp_path, name):
    argsfile = tmp_path / "args"
    make_tool(tools, "dd", f"printf '%s\\0' \"$@\" > {argsfile}\nprintf x\n")
    make_tool(tools, "stat", f"printf '%s\\0' \"$@\" > {argsfile}\necho 1\n")
    ops = real_ops(tools)
    src = f"{STAGE}/{name}"
    ops.dd_write(src, "/dev/mmcblk0p3")
    want = ["if=" + src, "of=/dev/mmcblk0p3", "bs=1M", "conv=fsync", "status=none"]
    assert argsfile.read_bytes().split(b"\0")[:-1] == [a.encode() for a in want]
    ops.stat_size(src)
    assert argsfile.read_bytes().split(b"\0")[:-1] == [b"-c", b"%s", src.encode()]
    ops.dd_sha256(src, "4M", 1)
    assert argsfile.read_bytes().split(b"\0")[0] == b"if=" + src.encode()


@pytest.mark.parametrize("name", ODD_ALLOWED)
def test_shlex_join_round_trips_odd_names_and_ssh_command_line_keeps_one_remote_string(name):
    vec = ["dd", f"if={STAGE}/{name}", "of=/dev/mmcblk0p3", "bs=1M"]
    assert shlex.split(shlex.join(vec)) == vec
    cl = host.SshTransport("op@board.local").command_line(vec)
    assert cl[-3:-1] == ["--", "op@board.local"]
    assert cl[-1] == shlex.join(vec)
    assert shlex.split(cl[-1]) == vec


# ======================================================================= 6
# Locale

LOCALES = ["C", "de_DE.UTF-8", "tr_TR.UTF-8"]
DF_HEAD = "Filesystem 1K-blocks Used Available Use% Mounted on\n"


@pytest.mark.parametrize("loc", LOCALES)
def test_real_ops_forces_c_locale_whatever_the_parent_has(tools, monkeypatch, loc):
    monkeypatch.setenv("LC_ALL", loc)
    monkeypatch.setenv("LANG", loc)
    monkeypatch.setenv("LC_NUMERIC", loc)
    monkeypatch.setenv("LANGUAGE", "de")
    make_tool(tools, "uname", "env\n")
    ops = real_ops(tools)
    out = dict(ln.split("=", 1) for ln in ops._run(["uname", "-r"]).text.splitlines() if "=" in ln)
    assert out["LC_ALL"] == "C"
    for k in ("LANG", "LC_NUMERIC", "LANGUAGE", "LC_MESSAGES", "LC_CTYPE"):
        assert k not in out, f"{k} leaked into the child"
    assert out["PATH"] == os.pathsep.join([str(tools), "/usr/sbin", "/usr/bin", "/sbin", "/bin"])
    assert ops._env() == {"PATH": out["PATH"], "LC_ALL": "C"}


@pytest.mark.parametrize("loc", LOCALES)
def test_locale_dependent_tool_output_is_plain_because_children_run_in_c(tools, monkeypatch, loc):
    monkeypatch.setenv("LC_ALL", loc)
    make_tool(tools, "df", f"""\
        if [ "$LC_ALL" = C ]; then v=12156576; else v=12156,576; fi
        echo '{DF_HEAD.strip()}'
        echo "tmpfs 100 1 $v 1% /x"
    """)
    assert real_ops(tools).df_free("/x") == 12156576


@pytest.mark.parametrize("loc", LOCALES)
def test_a_tool_that_ignores_c_and_prints_a_decimal_comma_fails_closed(tools, monkeypatch, loc):
    monkeypatch.setenv("LC_ALL", loc)
    make_tool(tools, "df", f"echo '{DF_HEAD.strip()}'\necho 'tmpfs 100 1 12156,576 1% /x'\n")
    with pytest.raises(ValueError):
        real_ops(tools).df_free("/x")


@pytest.mark.parametrize("rendering", ["12156,576", "12.156.576", "12 156 576", "12 156 576", "1.2E+7", "0x1f", ""])
@pytest.mark.parametrize("loc", LOCALES)
def test_df_parsers_never_report_more_free_space_than_there_is(monkeypatch, loc, rendering):
    monkeypatch.setenv("LC_ALL", loc)
    true_kib = 12156576
    text = f"{DF_HEAD}tmpfs 100 1 {rendering} 1% /x\n"
    ops = RecordingOps({"df -Pk /x": text})
    try:
        got = ops.df_free("/x")
    except (ValueError, IndexError):
        got = None  # refused: fine
    assert got is None or got <= true_kib
    assert got != true_kib, "only the plain number may ever parse to the true value"
    profile = NS(staging=NS(dir="/x", min_free_kib=1000))
    t = StubTransport(lambda argv, stdin, sudo: RunResult(0, text.encode()))
    try:
        avail = host.check_staging_space(t, profile)
    except HostError:
        avail = None
    assert avail is None or avail <= true_kib


@pytest.mark.parametrize("loc", LOCALES)
def test_numeric_tool_outputs_fail_closed_on_locale_formatting(monkeypatch, loc):
    monkeypatch.setenv("LC_ALL", loc)
    for bad in ("122.314.752\n", "122314752,0\n", "1,5\n", "\n"):
        ops = RecordingOps({f"blockdev --getsz {DEV}": bad, f"blockdev --getsize64 {DEV}": bad, "stat -c %s /x": bad})
        for call in (lambda: ops.blockdev_getsz(DEV), lambda: ops.blockdev_getsize64(DEV), lambda: ops.stat_size("/x")):
            with pytest.raises(ValueError):
                call()


@pytest.mark.parametrize("loc", LOCALES)
def test_efibootmgr_and_sfdisk_parsers_ignore_the_process_locale(monkeypatch, loc):
    from avocado_flash_remote import arm as armmod

    monkeypatch.setenv("LC_ALL", loc)
    assert armmod.boot_order_of(EFI_FINAL) == ORDER
    assert armmod.boot_next_of(EFI_FINAL) == ENTRY
    assert armmod.entries_with_label(EFI_AFTER, LABEL) == [ENTRY]
    assert armmod.entries_with_label(EFI_AFTER.replace(LABEL, LABEL.upper()), LABEL) == []
    m = cmd_write._DUMP_PART_RE.match("/dev/mmcblk0p1 : start=2048, size=409600, type=X")
    assert m and (int(m.group(2)), int(m.group(3))) == (2048, 409600)
    assert cmd_write._DUMP_PART_RE.match("/dev/mmcblk0p1 : start=2.048, size=409600") is None


@pytest.mark.parametrize("loc", LOCALES)
def test_a_whole_write_is_identical_under_any_parent_locale(tmp_path, monkeypatch, loc, good_mutations):
    monkeypatch.setenv("LC_ALL", loc)
    monkeypatch.setenv("LANG", loc)
    res, ops = Env(tmp_path).run()
    assert res.exit_code == 0
    assert [c.line for c in mutations(ops)] == good_mutations


# ======================================================================= 7
# Exact exit statuses


def profile_with_checks(checks):
    doc = json.loads(SHIPPED_BYTES)
    doc["checks"] = list(checks)
    return prof.load_profile_bytes(json.dumps(doc).encode())


def _check(script, checks=("emmc-exists",)):
    return cmd_check.run_check(RecordingOps(script), profile_with_checks(checks), staging_dir=STAGE, out=lambda x: None)


def _plan(tmp_path, over=None):
    e = Env(tmp_path)
    manifest = "".join(f"{s.sha256}  {name}\n" for name, s in e.scans.items())
    script = e.script(**{f"read_file {STAGE}/MANIFEST.hashes": manifest}, **(over or {}))
    return cmd_plan.run_plan(
        RecordingOps(script), e.profile, e.phash, staging_dir=STAGE, run_dir=str(tmp_path / "run"), run_id=RUN_ID,
        record_writer=lambda *a: "x", out=lambda x: None, scanner=lambda p: e.scans[p.rsplit("/", 1)[-1]],
    )  # fmt: skip


def _restore(tmp_path, *, unparseable):
    staging = tmp_path / "var" / "lib" / "staging"
    sd = tmp_path / "state"
    sd.mkdir()
    if unparseable:
        (sd / "current").write_text("x\n")
    prof_ns = NS(arm=NS(strategy="uefi-bootnext", params={"entry_label": LABEL}), staging=NS(dir=str(staging)))
    return cmd_restore.run_restore(RecordingOps({}), prof_ns, state_dir=sd, staging_dir=str(staging), out=lambda x: None)


def _cli(argv, **kw):
    return cli.main(argv, out=lambda x: None, sleep=lambda s: None, **kw)


def _raises(exc):
    def f(*a, **k):
        raise exc

    return f


def _runner_main(tmp_path, argv, *, req=None, monkeypatch=None, patch=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    info = bundle.build_bundle(FIXTURE_BYTES, tmp_path / "r.pyz", "t")
    rq = tmp_path / "req.json"
    rq.write_text(json.dumps(req if req is not None else {"state_dir": str(tmp_path / "st")}))
    if patch:
        monkeypatch.setattr(runner, patch[0], patch[1])
    return runner.main([a.replace("@REQ", str(rq)) for a in argv], archive=info.path)


def test_hard_coded_exit_constants():
    assert (runner.EXIT_PROFILE, runner.EXIT_USAGE, runner.EXIT_ERROR, runner.EXIT_INTERRUPTED) == (3, 64, 70, 130)


def test_exit_status_table(tmp_path, monkeypatch, capsys):
    from avocado_flash_remote.cmd_status import run_status

    ok_check = {f"lsblk -rn -o TYPE {DEV}": "disk\n"}
    rows = []

    def row(name, expected, fn):
        rows.append((name, expected, fn))

    row("check ok", 0, lambda: _check(ok_check).exit_code)
    row("check fail", 1, lambda: _check({f"lsblk -rn -o TYPE {DEV}": "loop\n"}).exit_code)
    row("check not examined", 2, lambda: _check({}).exit_code)
    row("check no checks listed", 2, lambda: _check({}, checks=()).exit_code)
    row("plan ok", 0, lambda: _plan(tmp_path / "p1").exit_code)
    row("plan refuse", 1, lambda: _plan(tmp_path / "p2", {f"blockdev --getsz {DEV}": "1\n"}).exit_code)
    e1 = Env(tmp_path / "w1")
    row("write ok", 0, lambda: e1.run()[0].exit_code)
    e2 = Env(tmp_path / "w2")
    row("write refuse (no plan)", 1, lambda: e2.run(plan=None)[0].exit_code)
    e3 = Env(tmp_path / "w3")
    row("write fail", 1, lambda: e3.run(script=e3.script(**{e3.dd_key("dtb"): OpFailed(["dd"], 1, "io")}))[0].exit_code)
    (tmp_path / "r1").mkdir()
    row("restore ok", 0, lambda: _restore(tmp_path / "r1", unparseable=False).exit_code)
    (tmp_path / "r2").mkdir()
    row("restore refuse", 1, lambda: _restore(tmp_path / "r2", unparseable=True).exit_code)
    row("status ok", 0, lambda: run_status(tmp_path / "nostate", out=lambda x: None).exit_code)
    row("runner usage (unknown sub)", 64, lambda: runner.main(["bogus"]))
    row("runner usage (no args)", 64, lambda: runner.main([]))
    row("runner profile mismatch", 3, lambda: _runner_main(tmp_path / "ru", ["check", "--request", "@REQ"], req={"profile_hash": "0" * 64}))
    row("runner passes subcommand code", 0, lambda: _runner_main(tmp_path / "rk", ["status", "--request", "@REQ"]))
    row("runner unexpected error", 70, lambda: _runner_main(tmp_path / "re", ["status", "--request", "@REQ"], monkeypatch=monkeypatch, patch=("run_status", _raises(RuntimeError("kaput")))))
    row("runner interrupt", 130, lambda: _runner_main(tmp_path / "ri", ["status", "--request", "@REQ"], monkeypatch=monkeypatch, patch=("run_status", _raises(KeyboardInterrupt()))))
    row("cli usage (unknown sub)", 64, lambda: _cli(["frobnicate"]))
    row("cli usage (no sub)", 64, lambda: _cli([]))
    row("cli usage (missing host)", 64, lambda: _cli(["check", "--board", "fixture-none"]))
    row("cli usage (hostile host)", 64, lambda: _cli(["check", "--board", "fixture-none", "--host=-oProxyCommand=x"]))
    row("cli unknown board", 64, lambda: _cli(["check", "--board", "nope", "--host", "h"]))
    row("cli help", 0, lambda: _cli(["--help"]))
    row("cli interrupt", 130, lambda: _cli(["status", "--board", "fixture-none", "--host", "h"], transport_factory=_raises(KeyboardInterrupt())))
    row("cli unexpected error", 70, lambda: _cli(["status", "--board", "fixture-none", "--host", "h"], transport_factory=_raises(RuntimeError("x"))))
    row("cli host failure", 1, lambda: _cli(["status", "--board", "fixture-none", "--host", "h"], transport_factory=_raises(HostError("boom"))))
    row("cli write without plan record", 1, lambda: _cli(["write", "--board", "fixture-none", "--host", "h", "--run-id", "nope", "--evidence-dir", str(tmp_path / "noev")], transport_factory=_raises(AssertionError("no contact"))))
    results = {name: (want, fn()) for name, want, fn in rows}
    capsys.readouterr()
    wrong = {n: v for n, v in results.items() if v[0] != v[1]}
    assert not wrong, wrong
    assert len(results) == 28


def test_status_unreadable_state_is_exit_1(tmp_path):
    from avocado_flash_remote.cmd_status import run_status

    (tmp_path / "current").write_text("zz\n")
    assert run_status(tmp_path, out=lambda x: None).exit_code == 1


# ---------------------------------------------------------------- 5.20: recovery promises


def test_no_recovery_text_promises_a_new_plan_without_naming_the_wipe_the_profile_needs(tmp_path):
    """The shipped profile sets require_empty, so plan refuses a disk that already has a table."""
    assert prof.load_profile_bytes(SHIPPED_BYTES).target.require_empty is True
    texts = []
    for action in set(statemod.RECOVERY.values()):
        texts.append(statemod._RECOVERY_TEXT[action])
    s = statemod.create_run(
        tmp_path, run_id="r1", profile_hash="p", plan_hash="q", board_identity={}, image_roles=["boot"], arm=True
    )
    s = statemod.transition(s, "table-writing")
    texts.append(statemod.describe_recovery(statemod.transition(s, "failed", error="boom")))
    for text in texts:
        low = text.lower()
        promises_replan = "plan and write again" in low or "plan again" in low or "from the start" in low
        if promises_replan:
            assert "wipe" in low and "stage" in low, text
