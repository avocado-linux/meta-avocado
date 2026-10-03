"""Tests for the readback and status subcommands (recording stubs only)."""

from __future__ import annotations

import ast
import pathlib

import pytest

from avocado_flash_remote import profile as prof
from avocado_flash_remote import state as st
from avocado_flash_remote.cmd_readback import (
    NO_JOURNAL_LINE,
    ReadbackError,
    make_guarded_copier,
    resolve_data_partition,
    run_readback,
)
from avocado_flash_remote.cmd_status import run_status
from avocado_flash_remote.ops import OpFailed, OpResult, RecordingOps, vector_mutates

SCRIPTS = pathlib.Path(__file__).resolve().parents[2]
JETSON = SCRIPTS / "avocado_flash_remote" / "profiles" / "jetson-agx-orin-j5012.json"
DISK = "/dev/mmcblk0"
PART = "/dev/mmcblk0p16"
ORDER = "0001,0002,0003"
EFI = f"BootCurrent: 0001\nBootOrder: {ORDER}\nBoot0001* UEFI\n"


@pytest.fixture
def profile():
    return prof.load_profile_bytes(JETSON.read_bytes())


@pytest.fixture
def dirs(tmp_path):
    # The output directory exists: readback asks what it lands on before creating anything.
    (tmp_path / "out").mkdir()
    return tmp_path / "mnt", tmp_path / "out"


def script(dirs, *, journal=True, efi=EFI, outfs="tmpfs\n", mount=None):
    mnt, out = dirs
    s = {
        "efibootmgr -v": efi,
        "lsblk -dn -o NAME": "mmcblk0\nnvme0n1\n",
        f"lsblk {DISK}": "NAME SIZE\nmmcblk0 58G\n",
        f"lsblk -rn -o NAME,PARTLABEL {DISK}": "mmcblk0 \nmmcblk0p15 esp\nmmcblk0p16 DATAPART_EXPAND\n",
        f"findmnt -no FSTYPE -T {out}": outfs,
        f"ls -la {mnt}": "total 0\n",
        f"ls -laR {mnt}/log/journal": "ok\n" if journal else OpResult(rc=2, stderr="ls: cannot access: No such file or directory"),
    }
    if mount is not None:
        s[f"mount -o ro,nosuid,nodev,noexec -t btrfs {PART} {mnt}"] = mount
    return s


def run(profile, dirs, ops, **kw):
    mnt, out = dirs
    copies = []
    lines = []
    res = run_readback(
        ops,
        profile,
        mount_dir=str(mnt),
        out_dir=str(out),
        reference_boot_order=kw.pop("reference", ORDER),
        copier=lambda s, d: copies.append((s, d)),
        list_logs=kw.pop("list_logs", lambda m: [f"{m}/log/boot.log", f"{m}/emmc-test.log"]),
        out=lines.append,
        **kw,
    )
    return res, copies, lines


# ------------------------------------------------------------------ readback


def test_golden_sequence_and_ro_mount(profile, dirs):
    mnt, out = dirs
    ops = RecordingOps(script(dirs))
    res, copies, _ = run(profile, dirs, ops)
    assert res.exit_code == 0 and res.found_journal
    assert ops.log == [
        "efibootmgr -v",
        "lsblk -dn -o NAME",
        f"lsblk {DISK}",
        f"lsblk -rn -o NAME,PARTLABEL {DISK}",
        f"findmnt -no FSTYPE -T {out}",
        f"mount -o ro,nosuid,nodev,noexec -t btrfs {PART} {mnt}",
        f"ls -la {mnt}",
        f"ls -laR {mnt}/log/journal",
        f"umount {mnt}",
    ]
    assert (f"{mnt}/log/journal", f"{out}/journal") in copies
    assert (f"{mnt}/emmc-test.log", f"{out}/emmc-test.log") in copies


def test_every_mount_is_read_only_and_only_mount_umount_mutate(profile, dirs):
    ops = RecordingOps(script(dirs))
    run(profile, dirs, ops)
    for call in ops.calls:
        if call.vector[0] == "mount":
            assert call.vector[1] == "-o" and call.vector[2].split(",")[0] == "ro"
        elif vector_mutates(call.vector):
            assert call.vector[0] == "umount"
    assert not ops.written


def test_missing_journal_is_a_recorded_result(profile, dirs):
    ops = RecordingOps(script(dirs, journal=False))
    res, copies, lines = run(profile, dirs, ops)
    assert res.exit_code == 0 and not res.found_journal
    assert NO_JOURNAL_LINE in "\n".join(lines)
    assert all(not d.endswith("/journal") for _, d in copies)


def test_boot_order_mismatch_exits_1(profile, dirs):
    ops = RecordingOps(script(dirs, efi="BootOrder: 0009\n"))
    res, _, lines = run(profile, dirs, ops)
    assert res.exit_code == 1
    assert "BootOrder DIFFERS" in "\n".join(lines)
    assert ops.log[-1].startswith("umount")


def test_cleanup_commands_printed_not_run(profile, dirs):
    mnt, _ = dirs
    ops = RecordingOps(script(dirs))
    _, _, lines = run(profile, dirs, ops)
    text = "\n".join(lines)
    assert f"umount {mnt}" in text and f"rmdir {mnt}" in text
    assert [x for x in ops.log if x.startswith("umount")] == [f"umount {mnt}"]
    assert not any(x.startswith(("rmdir", "efibootmgr -B", "efibootmgr -N")) for x in ops.log)


def test_out_dir_not_tmpfs_refuses_before_mount(profile, dirs):
    ops = RecordingOps(script(dirs, outfs="btrfs\n"))
    res, _, _ = run(profile, dirs, ops)
    assert res.exit_code == 1
    assert not any(x.startswith("mount") for x in ops.log)


def test_mount_failure_exits_1_without_umount(profile, dirs):
    mnt, _ = dirs
    ops = RecordingOps(script(dirs, mount=OpFailed(["mount"], 32, "bad")))
    res, _, _ = run(profile, dirs, ops)
    assert res.exit_code == 1
    assert not any(x.startswith("umount") for x in ops.log)


def test_ambiguous_partition_label_does_not_mount(profile, dirs):
    s = script(dirs)
    s[f"lsblk -rn -o NAME,PARTLABEL {DISK}"] = "mmcblk0p1 DATAPART_EXPAND\nmmcblk0p2 DATAPART_EXPAND\n"
    ops = RecordingOps(s)
    res, _, _ = run(profile, dirs, ops)
    assert res.exit_code == 1
    assert not any(x.startswith("mount") for x in ops.log)


def test_lookup_rule(profile):
    assert resolve_data_partition(profile) == "DATAPART_EXPAND"
    assert resolve_data_partition(profile, "OTHER") == "OTHER"


def test_lookup_without_var_role_needs_argument(profile):
    class P:
        images = {}
        layout = profile.layout

    with pytest.raises(ReadbackError):
        resolve_data_partition(P())


def test_default_copier_stays_under_out_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    src = tmp_path / "a.log"
    src.write_text("x")
    copy = make_guarded_copier(out)
    copy(str(src), str(out / "a.log"))
    assert (out / "a.log").read_text() == "x"
    with pytest.raises(ReadbackError):
        copy(str(src), str(tmp_path / "escape.log"))


# -------------------------------------------------------------------- status


def mk_state(state_dir):
    return st.create_run(
        state_dir, run_id="r1", profile_hash="p", plan_hash="q",
        board_identity={}, image_roles=[], arm=True,
    )  # fmt: skip


def test_status_absent(tmp_path):
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert res.exit_code == 0 and lines == ["status: no run recorded"]


def test_status_after_a_failed_run_shows_the_failed_recovery_text(tmp_path):
    s = st.transition(mk_state(tmp_path), "table-writing")
    st.transition(s, "failed", error="sfdisk exploded")
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert res.phase == "failed"
    assert "no recovery needed" not in lines[0]
    assert "sfdisk exploded" in lines[0] and "partition table" in lines[0]


def test_status_reports_phase_run_and_recovery(tmp_path):
    s = mk_state(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert (res.exit_code, res.phase, res.run_id) == (0, "planned", "r1")
    assert lines == [f"status: planned run=r1 recovery={st.describe_recovery(s)}"]
    assert res.recovery == st.describe_recovery(s)


def _two_runs(tmp_path):
    a = st.create_run(tmp_path, run_id="rA", profile_hash="p", plan_hash="q", board_identity={}, image_roles=[], arm=True)
    st.transition(a, "failed", error="run A ended")
    b = st.create_run(tmp_path, run_id="rB", profile_hash="p", plan_hash="q", board_identity={}, image_roles=[], arm=True)
    return a, b


def test_status_without_a_run_id_reports_the_current_run_only(tmp_path):
    _two_runs(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert (res.phase, res.run_id) == ("planned", "rB")


def test_status_with_a_run_id_reads_that_runs_own_state_even_when_current_moved_on(tmp_path):
    _two_runs(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append, run_id="rA")
    assert (res.exit_code, res.phase, res.run_id) == (0, "failed", "rA")
    assert lines[0].startswith("status: failed run=rA recovery=")


def test_status_with_a_run_id_that_has_no_state_says_no_run_recorded(tmp_path):
    _two_runs(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append, run_id="rZ")
    assert res.exit_code == 0 and res.phase is None
    assert "no run recorded" in lines[0] and "rZ" in lines[0]


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", ".", ""])
def test_status_with_a_hostile_run_id_is_unreadable_not_a_path_walk(tmp_path, bad):
    mk_state(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append, run_id=bad)
    assert res.exit_code == 1 and "unreadable" in lines[0]


def test_status_with_a_corrupt_run_state_is_unreadable(tmp_path):
    _two_runs(tmp_path)
    (tmp_path / "rA" / "state.json").write_text("{not json")
    lines = []
    res = run_status(tmp_path, out=lines.append, run_id="rA")
    assert res.exit_code == 1 and "unreadable" in lines[0] and "rA" in lines[0]


def test_status_unparseable_exits_1(tmp_path):
    (tmp_path / "current").write_text("r1\n")
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert res.exit_code == 1 and "r1" in lines[0] and "missing" in lines[0]


def _snapshot(root):
    return sorted((str(p), p.stat().st_mtime_ns) for p in [root, *root.rglob("*")])


def test_status_writes_nothing_on_read_only_dir(tmp_path):
    mk_state(tmp_path)
    before = _snapshot(tmp_path)
    modes = {}
    for p in [tmp_path, *tmp_path.rglob("*")]:
        modes[p] = p.stat().st_mode
        p.chmod(modes[p] & ~0o222)
    try:
        res = run_status(tmp_path, out=lambda _l: None)
        assert res.exit_code == 0
    finally:
        for p, m in modes.items():
            p.chmod(m)
    assert _snapshot(tmp_path) == before


def test_status_takes_no_ops_object():
    import inspect

    # run_id was added (keyword, default None): a host asking after its own run no longer depends on
    # which run the `current` pointer names at that moment. Still no ops object.
    assert list(inspect.signature(run_status).parameters) == ["state_dir", "out", "run_id"]


FORBIDDEN_MODULES = {"subprocess", "shutil", "tempfile"}
FORBIDDEN_OS = {
    "system", "popen", "remove", "unlink", "rename", "replace", "mkdir", "makedirs",
    "rmdir", "removedirs", "write", "open", "truncate", "chmod", "chown", "symlink",
    "link", "kill", "killpg", "fork", "utime",
}  # fmt: skip


def test_cmd_status_has_no_mutating_imports():
    tree = ast.parse((SCRIPTS / "avocado_flash_remote" / "cmd_status.py").read_text())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] in FORBIDDEN_MODULES | {"os"}]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FORBIDDEN_MODULES | {"os"}:
                bad.append(node.module)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr in FORBIDDEN_OS:
                bad.append(f"os.{node.attr}")
    assert bad == []



def test_missing_lsblk_is_not_examined_exit_2(profile, dirs):
    ops = RecordingOps(
        {**script(dirs), "lsblk -dn -o NAME": OpFailed(["lsblk", "-dn", "-o", "NAME"], None, "tool 'lsblk' not found")}
    )
    res, copies, lines = run(profile, dirs, ops)
    assert res.exit_code == 2
    assert any(ln.startswith("TARGET NOT EXAMINED: ") and "lsblk" in ln for ln in lines), lines
    assert not any(vector_mutates(c.vector) for c in ops.calls if c.kind == "exec")
    assert copies == []
    assert not any(c.startswith("mount ") for c in ops.log)
