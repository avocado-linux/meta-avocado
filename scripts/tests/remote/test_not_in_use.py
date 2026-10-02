"""The "target backs the running system" guard resolves stacked devices and fails closed.

Every case runs plan against RecordingOps with a described device graph
(devgraph), so the sysfs walk is exercised without a board. The target is the
shipped Jetson profile's /dev/mmcblk0.
"""

from __future__ import annotations

import pytest
import test_cmd_plan as tcp
from devgraph import SYS, standard

from avocado_flash_remote import cmd_plan
from avocado_flash_remote.ops import MutationRefused, OpResult, ReadOnlyOps, RecordingOps


def run(graph=None, *, root=None, stage=None, ssh=None, mounted=None, over=None):
    profile, phash = tcp.load()
    scans = tcp.scans_for(profile)
    script = tcp.script_for(profile, scans, root=root or "/dev/nvme0n1p2", stage_src=stage or "tmpfs",
                            mounted=mounted)  # fmt: skip
    if ssh is not None:
        script["findmnt -no SOURCE -T /etc/ssh"] = ssh + "\n"
    if graph is not None:
        script.update(graph.script())
    script.update(over or {})
    return tcp.plan(profile, phash, script=script, scans=scans)


def refused(res, ops, rec, *needles):
    tcp.assert_clean_refusal(res, ops, rec, *needles)


def test_dev_root_symlink_to_target_partition_refuses():
    g = standard().link("/dev/root", "mmcblk0p1")
    res, ops, rec = run(g, root="/dev/root")
    refused(res, ops, rec, "/dev/mmcblk0", "running root")


def test_by_uuid_symlink_to_target_refuses():
    g = standard().link("/dev/disk/by-uuid/1234-ABCD", "mmcblk0p2")
    res, ops, rec = run(g, stage="/dev/disk/by-uuid/1234-ABCD")
    refused(res, ops, rec, "/dev/mmcblk0", "staging directory")


def test_by_path_symlink_to_the_whole_target_refuses():
    g = standard().link("/dev/disk/by-path/platform-3460000.mmc", "mmcblk0")
    res, ops, rec = run(g, ssh="/dev/disk/by-path/platform-3460000.mmc")
    refused(res, ops, rec, "SSH path")


def test_dm_crypt_whose_slave_is_a_target_partition_refuses():
    g = standard().disk("dm-0", slaves=["mmcblk0p3"]).link("/dev/mapper/cryptroot", "dm-0")
    res, ops, rec = run(g, root="/dev/mapper/cryptroot")
    refused(res, ops, rec, "/dev/mmcblk0", "running root")


def test_lvm_two_levels_deep_refuses():
    g = (
        standard()
        .disk("dm-0", slaves=["dm-1"])
        .disk("dm-1", slaves=["mmcblk0p4"])
        .link("/dev/mapper/vg-root", "dm-0")
    )
    res, ops, rec = run(g, root="/dev/mapper/vg-root")
    refused(res, ops, rec, "/dev/mmcblk0")


def test_md_raid_member_on_target_refuses():
    g = standard().disk("md0", slaves=["nvme0n1p1", "mmcblk0p5"])
    res, ops, rec = run(g, root="/dev/md0")
    refused(res, ops, rec, "/dev/mmcblk0")


def test_mounted_stacked_device_over_target_refuses():
    g = standard().disk("dm-3", slaves=["mmcblk0p9"])
    res, ops, rec = run(g, mounted="/dev/nvme0n1p2\n/dev/dm-3\ntmpfs\n")
    refused(res, ops, rec, "mounted")


@pytest.mark.parametrize("which", ["root", "stage", "ssh"])
def test_failed_findmnt_probe_refuses_and_names_the_probe(which):
    key = {"root": "findmnt -no SOURCE -T /", "stage": f"findmnt -no SOURCE -T {tcp.STAGE}",
           "ssh": "findmnt -no SOURCE -T /etc/ssh"}[which]
    res, ops, rec = run(standard(), over={key: OpResult(rc=1, stderr="findmnt: no such target")})
    refused(res, ops, rec, {"root": "running root", "stage": "staging directory", "ssh": "SSH path"}[which], "probe")


@pytest.mark.parametrize("which", ["root", "stage", "ssh"])
@pytest.mark.parametrize("junk", ["", "\n", "/dev/nvme0n1p2\n/dev/mmcblk0p1\n"])
def test_empty_or_unparseable_findmnt_output_refuses(which, junk):
    key = {"root": "findmnt -no SOURCE -T /", "stage": f"findmnt -no SOURCE -T {tcp.STAGE}",
           "ssh": "findmnt -no SOURCE -T /etc/ssh"}[which]
    res, ops, rec = run(standard(), over={key: junk})
    refused(res, ops, rec, "probe")


def test_unresolvable_source_refuses():
    res, ops, rec = run(standard(), root="/dev/ghost", over={"realpath /dev/ghost": FileNotFoundError("gone")})
    refused(res, ops, rec, "cannot resolve", "/dev/ghost")


def test_source_with_no_sysfs_entry_refuses():
    g = standard().link("/dev/mystery", "mystery0")
    res, ops, rec = run(g, root="/dev/mystery", over={f"realpath {SYS}/mystery0": FileNotFoundError("gone")})
    refused(res, ops, rec, "cannot resolve", "mystery0")


def test_unreadable_slaves_directory_refuses():
    g = standard().disk("dm-0", slaves=[]).link("/dev/mapper/x", "dm-0")
    res, ops, rec = run(g, root="/dev/mapper/x", over={f"listdir {SYS}/dm-0/slaves": PermissionError("no")})
    refused(res, ops, rec, "cannot resolve")


def test_depth_bound_refuses():
    g = standard()
    for i in range(cmd_plan.MAX_STACK_DEPTH + 2):
        g.disk(f"dm-{i}", slaves=[f"dm-{i + 1}"])
    g.disk(f"dm-{cmd_plan.MAX_STACK_DEPTH + 2}", slaves=[])
    res, ops, rec = run(g, root="/dev/dm-0")
    refused(res, ops, rec, "deeper than")


def test_slave_cycle_terminates_and_passes_when_unrelated():
    g = standard().disk("dm-0", slaves=["dm-1"]).disk("dm-1", slaves=["dm-0", "nvme0n1p1"])
    res, ops, rec = run(g, root="/dev/dm-0")
    assert res.exit_code == 0, res.lines


def test_unrelated_stacked_disk_passes():
    g = standard().disk("dm-0", slaves=["nvme0n1p2"]).link("/dev/mapper/cryptroot", "dm-0")
    res, ops, rec = run(g, root="/dev/mapper/cryptroot")
    assert res.exit_code == 0, res.lines


def test_tmpfs_and_other_pseudo_sources_pass():
    res, ops, rec = run(standard(), root="tmpfs", ssh="devtmpfs")
    assert res.exit_code == 0, res.lines


def test_ram_backed_sources_cost_no_extra_probe():
    res, ops, rec = run(standard(), root="tmpfs", stage="tmpfs", ssh="tmpfs")
    assert res.exit_code == 0, res.lines
    assert not [c for c in ops.log if c.startswith(("findmnt -no FSTYPE", "findmnt -no OPTIONS"))]


# ------------------------------------------------------------------ overlay

ROOT_OPTS = "findmnt -no OPTIONS -T /"
ROOT_FST = "findmnt -no FSTYPE -T /"


def overlay(path, options, fstype="overlay"):
    return {f"findmnt -no FSTYPE -T {path}": fstype + "\n", f"findmnt -no OPTIONS -T {path}": options + "\n"}


def src(path, source):
    return {f"findmnt -no SOURCE -T {path}": source + "\n"}


def run_overlay_root(options, dirs, graph=None):
    over = {}
    over.update(overlay("/", options))
    for path, source in dirs.items():
        over.update(src(path, source))
    return run(graph or standard(), root="overlay", ssh="tmpfs", over=over)


OPTS = "rw,relatime,lowerdir=/lower,upperdir=/upper,workdir=/work"
SAFE = {"/lower": "/dev/nvme0n1p2", "/upper": "/dev/nvme0n1p2", "/work": "/dev/nvme0n1p2"}


def test_overlay_on_an_unrelated_disk_passes():
    res, ops, rec = run_overlay_root(OPTS, SAFE)
    assert res.exit_code == 0, res.lines


@pytest.mark.parametrize("which", ["/lower", "/upper", "/work"])
def test_overlay_directory_on_the_target_refuses(which):
    res, ops, rec = run_overlay_root(OPTS, {**SAFE, which: "/dev/mmcblk0p3"})
    refused(res, ops, rec, "/dev/mmcblk0", "running root")


def test_multi_entry_lowerdir_with_only_the_last_on_the_target_refuses():
    res, ops, rec = run_overlay_root(
        "rw,lowerdir=/l1:/l2:/l3,upperdir=/upper,workdir=/work",
        {**SAFE, "/l1": "/dev/nvme0n1p2", "/l2": "/dev/nvme0n1p1", "/l3": "/dev/mmcblk0p1"},
    )
    refused(res, ops, rec, "/dev/mmcblk0")


def test_read_only_overlay_with_lowerdir_only_is_walked():
    res, ops, rec = run_overlay_root("ro,lowerdir=/l1:/l2", {"/l1": "/dev/nvme0n1p2", "/l2": "/dev/mmcblk0p2"})
    refused(res, ops, rec, "/dev/mmcblk0")
    res, ops, rec = run_overlay_root("ro,lowerdir=/l1:/l2", {"/l1": "/dev/nvme0n1p2", "/l2": "/dev/nvme0n1p1"})
    assert res.exit_code == 0, res.lines


def test_overlay_directory_probe_failure_refuses():
    over = dict(overlay("/", OPTS), **src("/lower", "/dev/nvme0n1p2"), **src("/work", "/dev/nvme0n1p2"))
    over["findmnt -no SOURCE -T /upper"] = OpResult(rc=1, stderr="no")
    res, ops, rec = run(standard(), root="overlay", ssh="tmpfs", over=over)
    refused(res, ops, rec, "probe")


def test_overlay_directory_that_does_not_resolve_refuses():
    res, ops, rec = run_overlay_root(OPTS, {**SAFE, "/lower": "/dev/ghost"},
                                     graph=None)
    refused(res, ops, rec, "cannot resolve")


@pytest.mark.parametrize(
    "options",
    [
        "rw,relatime",  # no lowerdir
        "rw,lowerdir=,upperdir=/upper,workdir=/work",  # empty lowerdir
        "rw,lowerdir=/l1::/l2,upperdir=/upper,workdir=/work",  # empty entry
        "rw,lowerdir=/lower,upperdir=/upper",  # upperdir without workdir
        "rw,lowerdir=/lower,workdir=/work",  # workdir without upperdir
        "rw,lowerdir=/lower,upperdir=,workdir=/work",  # empty upperdir
        "",
    ],
)
def test_overlay_with_missing_or_unparseable_options_refuses(options):
    res, ops, rec = run_overlay_root(options, {**SAFE, "/l1": "/dev/nvme0n1p2", "/l2": "/dev/nvme0n1p2"})
    refused(res, ops, rec, "cannot tell what backs")


def test_overlay_options_probe_failure_refuses():
    over = dict(src("/lower", "/dev/nvme0n1p2"))
    over[ROOT_FST] = "overlay\n"
    over[ROOT_OPTS] = OpResult(rc=1, stderr="no")
    res, ops, rec = run(standard(), root="overlay", ssh="tmpfs", over=over)
    refused(res, ops, rec, "probe")


def test_fstype_probe_failure_on_an_unknown_non_block_source_refuses():
    res, ops, rec = run(standard(), root="mystery", ssh="tmpfs", over={ROOT_FST: OpResult(rc=1, stderr="no")})
    refused(res, ops, rec, "probe")


def test_unknown_non_block_source_that_is_not_overlay_still_passes():
    res, ops, rec = run(standard(), root="host:/export", ssh="tmpfs", over={ROOT_FST: "nfs4\n"})
    assert res.exit_code == 0, res.lines


def test_overlay_named_anything_is_found_by_its_fstype():
    over = overlay("/", OPTS) | src("/lower", "/dev/mmcblk0p1") | SAFE_SRC
    res, ops, rec = run(standard(), root="none", ssh="tmpfs", over=over)
    refused(res, ops, rec, "/dev/mmcblk0")


SAFE_SRC = src("/upper", "/dev/nvme0n1p2") | src("/work", "/dev/nvme0n1p2")


def test_nested_overlay_resolves_to_the_target():
    over = overlay("/", OPTS) | overlay("/lower", "ro,lowerdir=/inner") | src("/inner", "/dev/mmcblk0p2")
    over |= src("/lower", "overlay") | SAFE_SRC
    res, ops, rec = run(standard(), root="overlay", ssh="tmpfs", over=over)
    refused(res, ops, rec, "/dev/mmcblk0")


def test_overlay_over_itself_hits_the_depth_bound():
    over = overlay("/", "rw,lowerdir=/", ) | src("/", "overlay")
    res, ops, rec = run(standard(), root="overlay", ssh="tmpfs", over=over)
    refused(res, ops, rec, "deeper than")


def test_overlay_reads_add_only_findmnt_and_no_other_command():
    res, ops, rec = run_overlay_root(OPTS, SAFE)
    assert res.exit_code == 0, res.lines
    assert {c.vector[0] for c in ops.calls if c.kind == "exec"} <= tcp_reads()


def test_btrfs_subvolume_suffix_is_stripped():
    res, ops, rec = run(standard(), root="/dev/nvme0n1p2[/@]")
    assert res.exit_code == 0, res.lines
    res, ops, rec = run(standard(), root="/dev/mmcblk0p1[/@]")
    assert res.exit_code == 1


def test_target_that_does_not_resolve_refuses():
    res, ops, rec = run(standard(), over={"realpath /dev/mmcblk0": FileNotFoundError("gone")})
    refused(res, ops, rec, "cannot resolve", "/dev/mmcblk0")


def test_walk_reads_go_through_the_read_only_seam_and_add_no_command():
    g = standard().disk("dm-0", slaves=["nvme0n1p2"]).link("/dev/mapper/cryptroot", "dm-0")
    res, ops, rec = run(g, root="/dev/mapper/cryptroot")
    assert res.exit_code == 0, res.lines
    fs = {c.vector[0] for c in ops.calls if c.kind == "fs"}
    assert fs == {"read_file", "realpath", "listdir"}
    assert not [c for c in ops.calls if c.kind == "exec" and c.vector[0] not in tcp_reads()]


def tcp_reads():
    return {"blockdev", "lsblk", "sfdisk", "findmnt", "efibootmgr", "read_file"}


def test_read_only_wrapper_allows_the_new_reads_and_still_refuses_writes():
    ro = ReadOnlyOps(RecordingOps(standard().script()))
    assert ro.realpath("/dev/mmcblk0") == "/dev/mmcblk0"
    assert ro.listdir(f"{SYS}/mmcblk0/slaves") == []
    with pytest.raises(MutationRefused):
        ro._fs("write_file", "/x", b"")
