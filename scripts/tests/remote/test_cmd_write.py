"""Tests for the ``write`` subcommand core.

Everything runs against ``RecordingOps`` with scripted results: no real
device, no real dd or sfdisk. The hard rules are asserted over the recorded
call log, not just over return codes.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from avocado_flash_remote import cmd_write, layout
from avocado_flash_remote import profile as prof
from avocado_flash_remote import state as statemod
from avocado_flash_remote.images import ImageChanged, ScanResult
from avocado_flash_remote.ops import (
    OpFailed,
    OpResult,
    RecordingOps,
    vector_mutates,
)

HERE = pathlib.Path(__file__).resolve().parent
PROFILE_PATH = HERE.parent.parent / "avocado_flash_remote" / "profiles" / "jetson-agx-orin-j5012.json"
GOLDEN = HERE / "golden" / "calls.log"
DEV = "/dev/mmcblk0"
STAGE = "/run/emmc-test-images"
RUN_ID = "run-0001"
MACHINE_ID = "0123456789abcdef0123456789abcdef"
LABEL = "avocado-emmc-oneshot"
ORDER = "0001,0002,0000,0003,0004"
ENTRY = "0005"
EFI_PRE = f"BootCurrent: 0001\nTimeout: 5 seconds\nBootOrder: {ORDER}\nBoot0000* UEFI Shell\nBoot0001* UEFI NVMe\n"
EFI_AFTER = EFI_PRE + f"Boot{ENTRY}* {LABEL}\n"
EFI_FINAL = EFI_AFTER + f"BootNext: {ENTRY}\n"
NVME_ARG = "module_blacklist=nvme,nvme_core,pcie_tegra194"
BLANK = OpResult(rc=1, stderr=f"sfdisk: {DEV}: does not contain a recognized partition table\n")
SHIPPED_BYTES = PROFILE_PATH.read_bytes()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def boot_header(arg=NVME_ARG):
    hdr = bytearray(2048)
    hdr[0:8] = b"ANDROID!"
    hdr[40:44] = (0).to_bytes(4, "little")
    cmd = f"console=ttyS0 {arg} quiet".encode()
    hdr[64 : 64 + len(cmd)] = cmd
    return bytes(hdr)


class Env:
    """One scripted board plus a plan record for it."""

    def __init__(self, tmp_path, profile_bytes=SHIPPED_BYTES):
        self.tmp = tmp_path
        self.profile = prof.load_profile_bytes(profile_bytes)
        self.phash = prof.profile_hash(profile_bytes)
        self.state_dir = tmp_path / "state"
        self.efivars = tmp_path / "efivars"
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
            "board_identity": {"machine_id": MACHINE_ID, "device_serial": "unavailable"},
            "device": DEV,
            "image_hashes": {r: self.scans[i.file].sha256 for r, i in self.profile.images.items()},
            "image_sizes": {r: self.scans[i.file].size for r, i in self.profile.images.items()},
            "table_hash": hashlib.sha256(self.table.encode()).hexdigest(),
            "arm": {"strategy": "uefi-bootnext", "label": LABEL, "preexisting_boot_order": ORDER,
                    "preexisting_next": "", "entry_number": "", "next_armed": False},
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
            # check, plan's empty test, then the post-write verification
            f"sfdisk --dump {DEV}": [BLANK, BLANK, self.table],
            "findmnt -rn -o SOURCE": "/dev/nvme0n1p1\n/dev/nvme0n1p2\n",
            "findmnt -no SOURCE -T /": "/dev/nvme0n1p2\n",
            f"findmnt -no SOURCE -T {STAGE}": "tmpfs\n",
            "findmnt -no SOURCE -T /etc/ssh": "/dev/nvme0n1p2\n",
            "efibootmgr --help": "Usage: efibootmgr [-c|-C] [-d DISK]\n  -C | --create-only\n",
            # check, prepare (pre-flight), arm: pre / after-create / final
            "efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, EFI_AFTER, EFI_FINAL],
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
        s.update(over)
        return s

    def run(self, ops=None, *, script=None, plan="default", confirm=None, assume_yes=False, scanner=None,
            reverifier=None, **kw):  # fmt: skip
        ops = ops if ops is not None else RecordingOps(script if script is not None else self.script())
        plan_obj = self.plan if plan == "default" else plan
        recs = []

        def writer(run_dir, name, data):
            recs.append((run_dir, name, data))
            return "x"

        def default_scanner(path):
            return self.scans[path.rsplit("/", 1)[-1]]

        lines = []
        res = cmd_write.run_write(
            ops, self.profile, self.phash,
            staging_dir=STAGE, state_dir=self.state_dir, run_dir=str(self.tmp / "run"),
            plan_loader=lambda: plan_obj, record_writer=writer,
            confirm=confirm if confirm is not None else (lambda dev: dev),
            assume_yes=assume_yes, efivars_dir=str(self.efivars),
            out=lines.append,
            scanner=scanner or default_scanner,
            reverifier=reverifier or (lambda path, scan: None),
            **kw,
        )  # fmt: skip
        assert res.lines == lines
        res.records = recs
        return res, ops


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def mutations(ops):
    return [c for c in ops.calls if (c.kind == "exec" and vector_mutates(c.vector)) or (c.kind == "fs" and c.vector[0] != "read_file")]


def assert_clean_refusal(res, ops, *needles):
    assert res.exit_code == 1
    assert mutations(ops) == []
    text = "\n".join(res.lines)
    assert "write refused:" in text
    assert "nothing was written to the board" in text
    for n in needles:
        assert n in text, (n, text)


def current_phase(env):
    r = statemod.load_state(env.state_dir)
    assert r.status == "ok", r
    return r.state.phase


def lock_is_free(env):
    with statemod.OnBoardLock(env.state_dir / "lock", run_id="probe"):
        pass


# ----------------------------------------------------------------- good run


def test_good_run_completes_and_records_every_transition(env):
    res, ops = env.run()
    assert res.exit_code == 0, res.lines
    assert res.final_phase == "complete"
    assert res.run_id == RUN_ID
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "complete"
    phases = [p["phase"] for p in st.data["phases_done"]]
    expected = ["planned", "table-writing", "table-written"] + ["image-writing", "image-written"] * len(env.profile.images)
    assert phases == expected + ["verified", "arming", "armed", "complete"]
    for role, img in st.data["images"].items():
        assert img["state"] == "written"
        assert img["bytes_written"] == env.sizes[role]
        assert img["expected_sha256"] == img["readback_sha256"] == env.plan["image_hashes"][role]
    assert st.data["armed"]["entry_number"] == ENTRY
    assert st.data["armed"]["next_armed"] is True
    text = "\n".join(res.lines)
    assert f"BootNext: {ENTRY} armed, BootOrder unchanged: {ORDER}" in text
    assert "next: systemctl reboot" in text
    assert [r[1] for r in res.records] == ["write.json"]
    assert res.records[0][2]["phase"] == "complete"
    lock_is_free(env)


def test_good_run_scans_each_staged_file_once(env):
    seen = []

    def scanner(path):
        seen.append(path)
        return env.scans[path.rsplit("/", 1)[-1]]

    res, _ = env.run(scanner=scanner)
    assert res.exit_code == 0
    assert sorted(seen) == sorted({f"{STAGE}/{i.file}" for i in env.profile.images.values()})


def _golden_mutating():
    lines, cur = [], None
    for ln in GOLDEN.read_text().splitlines():
        if ln.startswith("=== CASE "):
            cur = ln[9:]
            continue
        if cur != "install:ok":
            continue
        tok = ln.split()
        if tok[:1] == ["sfdisk"] and len(tok) == 2:
            lines.append(ln)
        elif tok[:2] == ["udevadm", "settle"]:
            lines.append(ln)
        elif tok[:1] == ["dd"] and any(t.startswith("of=/dev/") for t in tok):
            lines.append(ln)
        elif tok[:2] in (["efibootmgr", "-C"], ["efibootmgr", "-n"]):
            lines.append(ln)
    return lines


def _norm_dd(line):
    # The kit's test used its own file names under <TMP>/images; the source
    # path is asserted separately against the profile, so only the rest of a
    # dd write is compared here.
    return " ".join("if=SRC" if t.startswith("if=") else t for t in line.split())


def test_mutating_calls_match_the_golden_good_run(env):
    res, ops = env.run()
    assert res.exit_code == 0
    ours = [c.line for c in mutations(ops)]
    golden = _golden_mutating()
    assert len(golden) == 1 + 1 + 7 + 2
    # Intentional differences from the kit, none of them in the mutating
    # sequence: the kit reads every image back after all writes, this tool
    # reads each back right after its own write; the kit reads the boot
    # header with `dd of=<file>` scratch copies, this tool reads it straight
    # from the partition. Both are reads. The mutating verbs and their order
    # are the contract, and are identical.
    assert [_norm_dd(x) for x in ours] == [_norm_dd(x) for x in golden]
    dd_sources = [c.vector[1][3:] for c in mutations(ops) if c.vector[0] == "dd"]
    assert dd_sources == [env.src(r) for r in env.profile.images]


def test_hard_rules_over_the_call_log(env):
    res, ops = env.run()
    assert res.exit_code == 0
    allowed_dd = {layout.partition_node(DEV, i.partition) for i in env.profile.images.values()}
    for c in ops.calls:
        v = c.vector
        if v[0] == "dd" and any(a.startswith("of=") for a in v):
            assert [a[3:] for a in v if a.startswith("of=")][0] in allowed_dd
        if v[0] == "sfdisk":
            assert v[-1] == DEV
        if v[0] == "efibootmgr":
            assert not {"-o", "-O", "-c", "-B", "-N"} & set(v[1:])
    sf = [c for c in ops.calls if c.vector == ["sfdisk", DEV]]
    assert len(sf) == 1 and sf[0].stdin.decode() == env.table
    # reads: the table verification and every per-image read-back come after their write
    log = ops.log
    for role in env.profile.images:
        assert log.index(env.dd_key(role)) < log.index(env.readback_key(role))


def test_first_mutation_follows_confirm_and_every_precheck(env):
    seen = {}

    def confirm(dev):
        seen["dev"] = dev
        seen["mutations_before"] = len(mutations(ops))
        seen["calls_before"] = len(ops.calls)
        return dev

    ops = RecordingOps(env.script())
    res, _ = env.run(ops, confirm=confirm)
    assert res.exit_code == 0
    assert seen["dev"] == DEV
    assert seen["mutations_before"] == 0
    assert seen["calls_before"] > 10  # the check and the re-tests ran first
    first_mut = next(i for i, c in enumerate(ops.calls) if c.kind == "exec" and vector_mutates(c.vector))
    assert first_mut >= seen["calls_before"]


def test_assume_yes_skips_confirm(env):
    def boom(dev):
        raise AssertionError("confirm must not be called")

    res, _ = env.run(confirm=boom, assume_yes=True)
    assert res.exit_code == 0


def test_udevadm_settle_failure_is_tolerated_like_the_kit(env):
    res, _ = env.run(script=env.script(**{"udevadm settle": OpFailed(["udevadm", "settle"], 127, "not found")}))
    assert res.exit_code == 0
    assert "udevadm settle failed" in "\n".join(res.lines)


def test_no_arm_strategy_completes_without_efibootmgr_writes(tmp_path):
    doc = json.loads(SHIPPED_BYTES)
    doc["arm"] = {"strategy": "none", "params": {}}
    doc["guard"] = {"strategy": "none", "params": {}}
    doc["checks"] = [c for c in doc["checks"] if c not in ("boot-order-unchanged", "boot-next-unset",
                     "no-stale-oneshot-entry", "efibootmgr-supports-create")]  # fmt: skip
    e = Env(tmp_path, json.dumps(doc).encode())
    e.plan["arm"] = {"strategy": "none"}
    res, ops = e.run()
    assert res.exit_code == 0, res.lines
    assert res.final_phase == "complete"
    assert not [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]
    assert "nothing was armed" in "\n".join(res.lines)


# ----------------------------------------------------------------- refusals


def test_no_plan_record_refuses(env):
    res, ops = env.run(plan=None)
    assert_clean_refusal(res, ops, "no plan record: run plan first")
    assert statemod.load_state(env.state_dir).status == "absent"


def test_plan_loader_oserror_is_no_plan(env):
    def loader():
        raise FileNotFoundError("plan.json")

    ops = RecordingOps(env.script())
    res = cmd_write.run_write(
        ops, env.profile, env.phash, staging_dir=STAGE, state_dir=env.state_dir, run_dir="/x",
        plan_loader=loader, confirm=lambda d: d, scanner=lambda p: env.scans[p.rsplit("/", 1)[-1]],
    )  # fmt: skip
    assert_clean_refusal(res, ops, "no plan record")


def test_changed_image_names_the_roles(env):
    changed = ScanResult(1, sha("different"), False, (1, 1, 1, 1))

    def scanner(path):
        name = path.rsplit("/", 1)[-1]
        return changed if name == env.profile.images["dtb"].file else env.scans[name]

    res, ops = env.run(scanner=scanner)
    assert_clean_refusal(res, ops, "staged image changed since the plan", "dtb")
    assert statemod.load_state(env.state_dir).status == "absent"


def test_missing_staged_image_refuses(env):
    def scanner(path):
        raise FileNotFoundError(path)

    res, ops = env.run(scanner=scanner)
    assert_clean_refusal(res, ops, "cannot be read")


def test_board_identity_changed_names_it(env):
    res, ops = env.run(script=env.script(**{"read_file /etc/machine-id": "ffffffffffffffffffffffffffffffff\n"}))
    assert_clean_refusal(res, ops, "board identity changed since the plan")


def test_device_serial_changed_names_board_identity(env):
    env.plan["board_identity"] = {"machine_id": MACHINE_ID, "device_serial": "0xDEADBEEF"}
    res, ops = env.run()
    assert_clean_refusal(res, ops, "board identity changed")


def test_stale_plan_from_another_profile_refuses(env):
    env.plan["profile_hash"] = "0" * 64
    res, ops = env.run()
    assert_clean_refusal(res, ops, "profile changed since the plan")


def test_plan_for_another_device_refuses(env):
    env.plan["device"] = "/dev/sdb"
    res, ops = env.run()
    assert_clean_refusal(res, ops, "plan was made for /dev/sdb")


def test_table_hash_mismatch_refuses(env):
    env.plan["table_hash"] = "1" * 64
    res, ops = env.run()
    assert_clean_refusal(res, ops, "table hash")


def test_malformed_plan_refuses(env):
    script = env.script()
    del env.plan["image_hashes"]
    res, ops = env.run(script=script)
    assert_clean_refusal(res, ops, "malformed")


def test_wrong_confirmation_refuses_with_zero_mutations(env):
    res, ops = env.run(confirm=lambda dev: "/dev/mmcblk1")
    assert_clean_refusal(res, ops, "confirmation did not match")
    assert statemod.load_state(env.state_dir).status == "absent"
    lock_is_free(env)


def test_missing_confirm_without_assume_yes_refuses(env):
    ops = RecordingOps(env.script())
    res = cmd_write.run_write(
        ops, env.profile, env.phash, staging_dir=STAGE, state_dir=env.state_dir, run_dir="/x",
        plan_loader=lambda: env.plan, efivars_dir=str(env.efivars),
        scanner=lambda p: env.scans[p.rsplit("/", 1)[-1]],
    )  # fmt: skip
    assert_clean_refusal(res, ops, "no confirmation available")


def test_failing_check_blocks_before_any_mutation(env):
    res, ops = env.run(script=env.script(**{"findmnt -rn -o SOURCE": "/dev/mmcblk0p1\n"}))
    assert_clean_refusal(res, ops, "pre-flight check did not pass", "FAIL")
    lock_is_free(env)


def test_root_backing_retest_refuses(env):
    res, ops = env.run(script=env.script(**{"findmnt -no SOURCE -T /": "/dev/mmcblk0p1\n"}))
    assert_clean_refusal(res, ops, "backs the running root")


def test_bootorder_changed_since_plan_refuses(env):
    env.plan["arm"]["preexisting_boot_order"] = "0002,0001"
    res, ops = env.run(script=env.script(**{"efibootmgr -v": [EFI_PRE] * 3}))
    assert_clean_refusal(res, ops)


def test_unreadable_pre_check_is_a_refusal_not_a_crash(env):
    script = env.script()
    del script["read_file /etc/machine-id"]
    res, ops = env.run(script=script)
    assert_clean_refusal(res, ops)


def test_concurrent_run_refused_naming_holder(env):
    with statemod.OnBoardLock(env.state_dir / "lock", run_id="other-run"):
        res, ops = env.run()
    assert_clean_refusal(res, ops, "another run holds the lock", "other-run")
    assert statemod.load_state(env.state_dir).status == "absent"


def test_unparseable_prior_state_refuses(env):
    env.state_dir.mkdir()
    (env.state_dir / "current").write_text("old-run\n")
    (env.state_dir / "old-run").mkdir()
    (env.state_dir / "old-run" / "state.json").write_text("{not json")
    res, ops = env.run()
    assert_clean_refusal(res, ops, "previous run is not finished", "unparseable")


def test_acknowledged_prior_run_is_recovery_only_not_a_write(env):
    res, _ = env.run(script=env.script(**{env.dd_key("dtb"): OpFailed(["dd"], 1, "io error")}))
    assert res.exit_code == 1
    # Make the failed run look interrupted, then acknowledge it.
    st = statemod.load_state(env.state_dir).state
    st.data["phase"] = "image-writing"
    (st.run_dir / "state.json").write_text(json.dumps(st.data))
    env.plan = dict(env.plan, run_id="run-0002")
    res2, ops2 = env.run(ack_run_id=RUN_ID)
    assert_clean_refusal(res2, ops2, "recovery only")


def test_used_plan_cannot_be_reused_after_failure(env):
    res, _ = env.run(script=env.script(**{env.dd_key("dtb"): OpFailed(["dd"], 1, "io error")}))
    assert res.exit_code == 1 and res.final_phase == "failed"
    res2, ops2 = env.run()
    assert_clean_refusal(res2, ops2, "already used")


def test_fresh_plan_after_a_terminal_run_is_allowed(env):
    res, _ = env.run(script=env.script(**{env.dd_key("dtb"): OpFailed(["dd"], 1, "io error")}))
    assert res.exit_code == 1
    env.plan = dict(env.plan, run_id="run-0002")
    res2, _ = env.run()
    assert res2.exit_code == 0 and res2.run_id == "run-0002"


# -------------------------------------------------------- failure injection


def test_readback_mismatch_records_failed_and_never_arms(env):
    bad = OpResult(digest="f" * 64)
    res, ops = env.run(script=env.script(**{env.readback_key("dtb"): bad}))
    assert res.exit_code == 1
    assert res.final_phase == "failed"
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "failed"
    assert "does not match the planned checksum" in st.data["error"]
    assert env.plan["image_hashes"]["dtb"] in st.data["error"] and "f" * 64 in st.data["error"]
    assert [p["phase"] for p in st.data["phases_done"]][-2:] == ["image-writing", "failed"]
    written = [c.vector[2][3:] for c in mutations(ops) if c.vector[0] == "dd"]
    assert written == [env.node(r) for r in ("boot", "boot_b", "dtb")]  # nothing after the bad image
    assert not [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]
    assert not [c for c in ops.calls if c.vector[0] == "dd" and f"if={env.node('boot')}" in c.vector and "bs=2048" in c.vector]
    assert "the board was not armed" in "\n".join(res.lines)
    lock_is_free(env)


ROLES = ["boot", "dtb_b", "var"]  # first, middle and last image of seven


def _inject_cases():
    cases = [
        ("sfdisk-write", lambda e: {f"sfdisk {DEV}": OpFailed(["sfdisk", DEV], 1, "boom")}, "table-writing"),
        ("table-has-no-label", lambda e: {f"sfdisk --dump {DEV}": [BLANK, BLANK, BLANK]}, "table-written"),
        ("partition-size-wrong", lambda e: {f"blockdev --getsize64 {layout.partition_node(DEV, 3)}": "123\n"},
         "table-written"),
    ]  # fmt: skip
    for r in ROLES:
        cases.append((f"dd-{r}", lambda e, r=r: {e.dd_key(r): OpFailed(["dd"], 1, "io")}, "image-writing"))
        cases.append((f"readback-{r}", lambda e, r=r: {e.readback_key(r): OpFailed(["dd"], 1, "io")}, "image-writing"))
    cases.append(("esp-not-vfat", lambda e: {f"blkid -p -s TYPE -o value {e.node('esp')}": "ext4\n"}, "image-written"))
    cases.append(("guard-fails", lambda e: {e.guard_key("B_kernel"): boot_header("quiet")}, "verified"))
    cases.append(("arm-next-fails", lambda e: {f"efibootmgr -n {ENTRY}": OpFailed(["efibootmgr", "-n", ENTRY], 1, "x")},
                  "arming"))  # entry exists and BootNext may be set: stays arming  # fmt: skip
    cases.append(("arm-bootorder-moved", lambda e: {"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE.replace(ORDER, "0002,0001")]},
                  "arming"))  # write-ahead: arming was durable before the failed arm step  # fmt: skip
    return cases


@pytest.mark.parametrize("name,inject,crash_phase", _inject_cases(), ids=[c[0] for c in _inject_cases()])
def test_failure_at_each_step_records_failed_and_blocks_a_rerun(env, name, inject, crash_phase):
    res, ops = env.run(script=env.script(**inject(env)))
    assert res.exit_code == 1, res.lines
    # a failure after the arm step touched the boot variables stays in `arming`
    expect = "arming" if name == "arm-next-fails" else "failed"
    assert current_phase(env) == expect
    assert res.final_phase == expect
    assert statemod.load_state(env.state_dir).state.data["error"]
    lock_is_free(env)
    efi_writes = [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]
    if name.startswith(("sfdisk", "table", "partition")):
        assert not [c for c in mutations(ops) if c.vector[0] == "dd"]
    assert not efi_writes or name.startswith("arm")
    if name != "arm-next-fails":
        assert not [c for c in efi_writes if c.vector[:2] == ["efibootmgr", "-n"]]
    assert "recovery:" in "\n".join(res.lines)
    # The same plan cannot be replayed over a failed (or possibly armed) run.
    res2, ops2 = env.run()
    assert_clean_refusal(res2, ops2)


@pytest.mark.parametrize("name,inject,crash_phase", _inject_cases(), ids=[c[0] for c in _inject_cases()])
def test_crash_that_cannot_record_failed_leaves_last_phase_and_rerun_is_refused(
    env, monkeypatch, name, inject, crash_phase
):
    real = cmd_write.transition

    def flaky(state, phase, **kw):
        if phase == "failed":
            raise OSError("disk went away")
        return real(state, phase, **kw)

    monkeypatch.setattr(cmd_write, "transition", flaky)
    res, ops = env.run(script=env.script(**inject(env)))
    assert res.exit_code == 1
    r = statemod.load_state(env.state_dir)
    assert r.status == "ok"
    assert r.state.phase == crash_phase
    lock_is_free(env)
    efi_writes = [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]
    assert not efi_writes or name.startswith("arm")
    res2, ops2 = env.run()
    assert_clean_refusal(res2, ops2, "previous run is not finished", "Permitted recovery", RUN_ID)


def test_kill_after_table_write_before_table_written_leaves_table_writing(env, monkeypatch):
    real = cmd_write.transition

    def killing(state, phase, **kw):
        if phase in ("table-written", "failed"):
            raise OSError("killed")
        return real(state, phase, **kw)

    monkeypatch.setattr(cmd_write, "transition", killing)
    res, ops = env.run()
    assert res.exit_code == 1
    r = statemod.load_state(env.state_dir)
    assert r.status == "ok"
    assert r.state.phase == "table-writing"
    # The state was durable before the first mutating call ran.
    vectors = [c.vector for c in ops.calls]
    assert ["sfdisk", DEV] in vectors
    assert not [c for c in mutations(ops) if c.vector[0] == "dd"]
    lock_is_free(env)
    res2, ops2 = env.run()
    assert_clean_refusal(res2, ops2, "previous run is not finished", "restore-then-restart", RUN_ID)


def test_table_writing_is_recorded_before_the_sfdisk_write(env, monkeypatch):
    ops = RecordingOps(env.script())
    at = {}
    real = cmd_write.transition

    def spy(state, phase, **kw):
        if phase in ("table-writing", "table-written"):
            at[phase] = len(mutations(ops))
        return real(state, phase, **kw)

    monkeypatch.setattr(cmd_write, "transition", spy)
    res, _ = env.run(ops=ops)
    assert res.exit_code == 0, res.lines
    assert at["table-writing"] == 0  # no mutation had happened yet
    assert at["table-written"] == 1  # exactly the sfdisk write
    assert "sfdisk" == mutations(ops)[0].vector[0]


def test_staged_image_changed_after_plan_fails_the_run_at_that_image(env):
    calls = []

    def reverifier(path, scan):
        calls.append(path)
        if len(calls) == 4:
            raise ImageChanged(f"{path}: content hash changed since scan")

    res, ops = env.run(reverifier=reverifier)
    assert res.exit_code == 1
    assert current_phase(env) == "failed"
    assert "changed after the plan" in statemod.load_state(env.state_dir).state.data["error"]
    written = [c.vector[2][3:] for c in mutations(ops) if c.vector[0] == "dd"]
    assert written == [env.node(r) for r in ("boot", "boot_b", "dtb")]
    assert not [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]


@pytest.mark.parametrize(
    "bad",
    [boot_header("quiet"), boot_header(NVME_ARG + "y"), boot_header(NVME_ARG)[:40] + (3).to_bytes(4, "little") + boot_header(NVME_ARG)[44:],
     b"NOTANDRO" + boot_header(NVME_ARG)[8:]],
    ids=["noarg", "nearmiss", "hdrv3", "nomagic"],
)
def test_bad_staged_boot_image_refuses_with_zero_mutations(env, bad):
    res, ops = env.run(file_reader=lambda p: bad if p.endswith("boot.img") else boot_header())
    assert_clean_refusal(res, ops, "write refused: staged boot image boot.img")
    assert res.final_phase is None
    assert not (env.state_dir / RUN_ID).exists()
    assert not [c for c in ops.calls if c.kind == "exec" and c.vector[0] in ("sfdisk", "dd", "efibootmgr") and vector_mutates(c.vector)]


def test_good_staged_boot_image_lets_the_write_proceed(env):
    res, _ = env.run(file_reader=lambda p: boot_header())
    assert res.exit_code == 0


def test_arm_never_attempted_after_a_guard_failure(env):
    res, ops = env.run(script=env.script(**{env.guard_key("A_kernel"): boot_header("quiet")}))
    assert res.exit_code == 1
    assert "guard refused to arm" in statemod.load_state(env.state_dir).state.data["error"]
    assert not [c for c in ops.calls if c.vector[0] == "efibootmgr" and vector_mutates(c.vector)]
    assert ops.log.count("efibootmgr -v") == 2  # check and pre-flight only; the arm step never ran


def test_arm_failure_after_entry_creation_says_do_not_reboot_and_keeps_the_record(env):
    res, ops = env.run(script=env.script(**{"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, EFI_AFTER, EFI_AFTER]}))
    assert res.exit_code == 1
    err = statemod.load_state(env.state_dir).state.data["error"]
    assert "DO NOT REBOOT" in err
    assert ENTRY in err
    st = statemod.load_state(env.state_dir).state
    # The entry and the BootNext that were set are in the state, so restore undoes them.
    assert st.phase == "arming"
    assert st.data["armed"]["entry_number"] == ENTRY and st.data["armed"]["next_armed"] is True
    assert len([c for c in ops.calls if c.vector[:2] == ["efibootmgr", "-n"]]) == 1
    assert "the board WAS armed" in "\n".join(res.lines)


def test_keyboard_interrupt_is_recorded_then_propagates(env):
    ops = RecordingOps(env.script(**{env.dd_key("dtb"): KeyboardInterrupt()}))
    with pytest.raises(KeyboardInterrupt):
        env.run(ops)
    assert current_phase(env) == "failed"
    lock_is_free(env)


def test_unrecordable_evidence_does_not_change_the_outcome(env):
    def writer(*a):
        raise OSError("read-only fs")

    ops = RecordingOps(env.script())
    res = cmd_write.run_write(
        ops, env.profile, env.phash, staging_dir=STAGE, state_dir=env.state_dir, run_dir="/x",
        plan_loader=lambda: env.plan, record_writer=writer, assume_yes=True, efivars_dir=str(env.efivars),
        scanner=lambda p: env.scans[p.rsplit("/", 1)[-1]], reverifier=lambda p, s: None,
    )  # fmt: skip
    assert res.exit_code == 0
    assert "cannot write write.json" in "\n".join(res.lines)


# ---------------------------------------------------------------- 5.16


class _PhaseSpy(RecordingOps):
    """Records the durable phase seen at the moment each efibootmgr mutation is issued."""

    def __init__(self, script, state_dir):
        super().__init__(script)
        self.state_dir = state_dir
        self.seen = []

    def _peek(self, what):
        r = statemod.load_state(self.state_dir)
        st = r.state
        self.seen.append((what, st.phase, dict(st.data.get("armed") or {})))

    def efibootmgr_create(self, *a, **kw):
        self._peek("create")
        return super().efibootmgr_create(*a, **kw)

    def efibootmgr_next(self, *a, **kw):
        self._peek("next")
        return super().efibootmgr_next(*a, **kw)


def test_arming_is_durable_before_the_first_efibootmgr_mutation(env):
    spy = _PhaseSpy(env.script(), env.state_dir)
    res, ops = env.run(ops=spy)
    assert res.exit_code == 0, res.lines
    assert [w for w, _, _ in spy.seen] == ["create", "next"]
    assert spy.seen[0][1] == "arming"  # never "verified" while efibootmgr -C runs
    assert spy.seen[0][2]["label"] == LABEL and spy.seen[0][2]["entry_number"] == ""
    assert spy.seen[1][1] == "arming"
    assert spy.seen[1][2]["entry_number"] == ENTRY  # recorded as soon as it was known
    phases = [p["phase"] for p in statemod.load_state(env.state_dir).state.data["phases_done"]]
    assert phases[-3:] == ["arming", "armed", "complete"]


def _restore_for(env, ops, ack=RUN_ID):
    from avocado_flash_remote import cmd_restore

    removed = []
    res = cmd_restore.run_restore(
        ops, env.profile, state_dir=env.state_dir, staging_dir=STAGE, ack_run_id=ack,
        remove_tree=removed.append, out=lambda x: None,
    )  # fmt: skip
    return res, removed


def test_kill_between_create_and_armed_leaves_arming_and_restore_disarms_the_entry(env):
    # efibootmgr -C ran; the process dies on the very next read, before any state update
    script = env.script(**{"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, KeyboardInterrupt()]})
    with pytest.raises(KeyboardInterrupt):
        env.run(script=script)
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "arming"
    assert st.data["armed"]["entry_number"] == ""
    # restore treats arming as possibly armed and finds the entry by its label
    live = EFI_AFTER + f"BootNext: {ENTRY}\n"
    rops = RecordingOps({"efibootmgr -v": [live, live, live, EFI_PRE]})
    res, removed = _restore_for(env, rops)
    assert res.exit_code == 0, res.lines
    muts = [c.line for c in mutations(rops)]
    assert f"efibootmgr -B -b {ENTRY}" in muts and "efibootmgr -N" in muts
    assert statemod.load_state(env.state_dir).state.phase == "restored"


def test_restore_of_arming_without_ack_refuses(env):
    with pytest.raises(KeyboardInterrupt):
        env.run(script=env.script(**{"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, KeyboardInterrupt()]}))
    rops = RecordingOps({})
    res, removed = _restore_for(env, rops, ack=None)
    assert res.exit_code == 1 and removed == [] and rops.calls == []


def test_arm_error_with_no_entry_number_says_state_unknown_and_not_to_reboot(env):
    # the entry is created but efibootmgr lists none carrying the label
    res, ops = env.run(script=env.script(**{"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE, EFI_PRE]}))
    assert res.exit_code == 1
    text = "\n".join(res.lines)
    assert "UNKNOWN" in text and "DO NOT REBOOT" in text
    assert "the board was not armed" not in text
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "arming"
    assert "cannot find the new boot entry number" in st.data["error"]
    assert res.final_phase == "arming"


def test_arm_failure_before_any_efibootmgr_mutation_is_failed_and_not_armed(env):
    res, ops = env.run(script=env.script(**{"efibootmgr -v": [EFI_PRE, EFI_PRE, EFI_PRE.replace(ORDER, "0002,0001")]}))
    assert res.exit_code == 1
    assert not [c for c in ops.calls if c.vector[:2] in (["efibootmgr", "-C"], ["efibootmgr", "-n"])]
    assert statemod.load_state(env.state_dir).state.phase == "failed"
    assert "the board was not armed" in "\n".join(res.lines)


def test_replay_of_an_old_run_id_is_refused_and_its_state_is_untouched(env):
    res, _ = env.run()
    assert res.exit_code == 0
    first = (env.state_dir / RUN_ID / "state.json").read_bytes()
    env.plan = dict(env.plan, run_id="run-0002")
    res2, _ = env.run()
    assert res2.exit_code == 0 and statemod.load_state(env.state_dir).state.run_id == "run-0002"
    env.plan = dict(env.plan, run_id=RUN_ID)
    res3, ops3 = env.run()
    assert_clean_refusal(res3, ops3, RUN_ID, "state record")
    assert (env.state_dir / RUN_ID / "state.json").read_bytes() == first
    assert statemod.load_state(env.state_dir).state.run_id == "run-0002"


def test_existing_state_json_refuses_whatever_current_says(env):
    (env.state_dir / RUN_ID).mkdir(parents=True)
    (env.state_dir / RUN_ID / "state.json").write_text("{}")
    res, ops = env.run()
    assert_clean_refusal(res, ops, "state record")


# ---------------------------------------------------------------- 5.17

PINNED = "0x0badc0de"
SERIAL_PATH = "read_file /sys/block/mmcblk0/device/serial"


def _pinned_env(tmp_path):
    doc = json.loads(PROFILE_PATH.read_text())
    doc["target"]["identity"] = {"kind": "serial", "value": PINNED, "sysfs_attr": "serial"}
    e = Env(tmp_path, json.dumps(doc).encode())
    e.plan["board_identity"] = {"machine_id": MACHINE_ID, "device_serial": PINNED}
    return e


def test_pinned_serial_matches_and_the_write_proceeds(tmp_path):
    e = _pinned_env(tmp_path)
    res, ops = e.run(script=e.script(**{SERIAL_PATH: PINNED + "\n"}))
    assert res.exit_code == 0, res.lines


def test_different_serial_refuses_the_write_before_any_write_call(tmp_path):
    e = _pinned_env(tmp_path)
    res, ops = e.run(script=e.script(**{SERIAL_PATH: "0x00000001\n"}))
    assert_clean_refusal(res, ops, "identity mismatch")


def test_missing_serial_attribute_refuses_the_write_before_any_write_call(tmp_path):
    e = _pinned_env(tmp_path)
    res, ops = e.run(script=e.script(**{SERIAL_PATH: OpFailed(["cat"], 1, "No such file")}))
    assert_clean_refusal(res, ops, "cannot be verified")


# ---------------------------------------------------------------- 5.20


def test_acknowledged_recovery_refusal_does_not_promise_a_plan_the_profile_refuses(env):
    res, _ = env.run(script=env.script(**{env.dd_key("dtb"): OpFailed(["dd"], 1, "io error")}))
    st = statemod.load_state(env.state_dir).state
    st.data["phase"] = "image-writing"
    (st.run_dir / "state.json").write_text(json.dumps(st.data))
    env.plan = dict(env.plan, run_id="run-0002")
    res2, ops2 = env.run(ack_run_id=RUN_ID)
    text = "\n".join(res2.lines)
    assert "recovery only" in text
    assert "wipe" in text and "stage" in text


def test_armed_record_never_goes_back_in_sequence_number(env, monkeypatch):
    seen = []
    real = cmd_write.transition

    def spy(state, phase, **kw):
        new = real(state, phase, **kw)
        seen.append((phase, new.data["seq"]))
        return new

    monkeypatch.setattr(cmd_write, "transition", spy)
    res, _ = env.run()
    assert res.exit_code == 0, res.lines
    seqs = [q for _, q in seen]
    assert seqs == sorted(set(seqs)), seen  # strictly increasing: no repeat, no step back
    assert [ph for ph, _ in seen].count("arming") >= 3  # write-ahead plus the two progress writes
    final = statemod.load_state(env.state_dir).state
    assert final.data["seq"] == seqs[-1] == max(seqs)
    armed_seq = next(q for ph, q in seen if ph == "armed")
    assert armed_seq > max(q for ph, q in seen if ph == "arming")


class _CrashAroundCreate(RecordingOps):
    def __init__(self, script, *, after):
        super().__init__(script)
        self.after = after

    def efibootmgr_create(self, *a, **kw):
        if not self.after:
            raise KeyboardInterrupt  # dies after the arming record, before -C runs
        super().efibootmgr_create(*a, **kw)
        raise KeyboardInterrupt  # dies after -C ran, before anything was recorded about it


def test_crash_between_the_arming_write_and_efibootmgr_create_restores_cleanly(env):
    ops = _CrashAroundCreate(env.script(), after=False)
    with pytest.raises(KeyboardInterrupt):
        env.run(ops=ops)
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "arming" and st.data["armed"]["entry_number"] == ""
    assert not [c for c in mutations(ops) if c.vector[0] == "efibootmgr"]
    rops = RecordingOps({"efibootmgr -v": [EFI_PRE, EFI_PRE]})
    res, removed = _restore_for(env, rops)
    assert res.exit_code == 0, res.lines
    assert not [c for c in mutations(rops)], "nothing was created, so nothing may be deleted"
    assert "nothing removed" in "\n".join(res.lines)
    assert statemod.load_state(env.state_dir).state.phase == "restored"


def test_crash_right_after_efibootmgr_create_is_found_and_removed_by_label(env):
    ops = _CrashAroundCreate(env.script(), after=True)
    with pytest.raises(KeyboardInterrupt):
        env.run(ops=ops)
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "arming" and st.data["armed"]["entry_number"] == ""
    rops = RecordingOps({"efibootmgr -v": [EFI_AFTER, EFI_PRE]})
    res, removed = _restore_for(env, rops)
    assert res.exit_code == 0, res.lines
    assert [c.line for c in mutations(rops)] == [f"efibootmgr -B -b {ENTRY}"]
    assert statemod.load_state(env.state_dir).state.phase == "restored"


@pytest.mark.parametrize("fail_on", [1, 2], ids=["after-create", "after-next"])
def test_progress_write_failure_inside_the_arm_step_stays_arming_and_says_unknown(env, monkeypatch, fail_on):
    real = cmd_write.transition
    count = {"n": 0}

    def flaky(state, phase, **kw):
        if phase == "arming" and state.data["phase"] == "arming" and "error" not in kw:
            count["n"] += 1
            if count["n"] == fail_on:
                raise OSError("no space left on device")
        return real(state, phase, **kw)

    monkeypatch.setattr(cmd_write, "transition", flaky)
    res, ops = env.run()  # nothing may raise past the arm step
    assert res.exit_code == 1
    assert res.final_phase == "arming"
    text = "\n".join(res.lines)
    assert "UNKNOWN" in text and "DO NOT REBOOT" in text
    assert "the board was not armed" not in text
    st = statemod.load_state(env.state_dir).state
    assert st.phase == "arming"
    assert "no space left on device" in st.data["error"]
    lock_is_free(env)
