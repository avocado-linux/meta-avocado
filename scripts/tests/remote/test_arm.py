"""Tests for the arm (uefi-bootnext, none) and guard (boot-arg, none) strategies."""

import struct
from types import SimpleNamespace as NS

import pytest

from avocado_flash_remote import arm as armmod
from avocado_flash_remote.arm import (
    ArmError,
    ArmRecord,
    GuardError,
    entries_with_label,
    get_arm,
    get_guard,
)
from avocado_flash_remote.ops import MutationRefused, OpResult, ReadOnlyOps, RecordingOps

LABEL = "avocado-emmc-oneshot"
LOADER = "\\EFI\\BOOT\\BOOTAA64.EFI"
ARG = "module_blacklist=nvme,nvme_core,pcie_tegra194"
LIST = "efibootmgr -v"


def efi(order="0001,0002,0003", nxt=None, extra=()):
    lines = []
    if nxt:
        lines.append(f"BootNext: {nxt}")
    lines += ["BootCurrent: 0001", "Timeout: 5 seconds", f"BootOrder: {order}"]
    lines += ["Boot0001* UEFI NVMe", "Boot0002* UEFI eMMC"]
    lines += list(extra)
    return "\n".join(lines) + "\n"


NEW = f"Boot0005* {LABEL}\tHD(11,GPT,1,0x0,0x0)/File({LOADER})"


def profile(arm_name="uefi-bootnext"):
    return NS(
        target=NS(device="/dev/mmcblk0"),
        images={"esp": NS(partition=11)},
        arm=NS(
            strategy=arm_name,
            params={"label": LABEL, "loader_path": LOADER, "boot_args": "bootmode=bootimg"},
        ),
        guard=NS(
            strategy="boot-arg",
            params={"argument": ARG, "partitions": ["A_kernel", "B_kernel"]},
        ),
    )


def calls(ops):
    return ops.log


def assert_no_order_edits(ops):
    for line in ops.log:
        parts = line.split()
        if parts and parts[0] == "efibootmgr":
            assert "-o" not in parts and "-O" not in parts and "-c" not in parts, line


def happy_ops(after_order="0001,0002,0003", **kw):
    return RecordingOps(
        {
            LIST: [
                efi(),
                efi(),
                efi(extra=[NEW], order=after_order),
                efi(extra=[NEW], order=after_order, nxt="0005"),
            ],
            f"efibootmgr -C -d /dev/mmcblk0 -p 11 -L {LABEL} -l {LOADER} -u bootmode=bootimg": efi(
                extra=[NEW]
            ),
        }
    )


# ------------------------------------------------------------------- arm


def test_prepare_records_boot_order_and_next():
    ops = RecordingOps({LIST: efi()})
    rec = get_arm("uefi-bootnext").prepare(ops, profile(), None)
    assert rec.preexisting_boot_order == "0001,0002,0003"
    assert rec.preexisting_next == ""
    assert rec.label == LABEL
    assert rec.entry_number == ""
    assert ops.log == [LIST]


def test_prepare_refuses_stale_entry_with_label():
    ops = RecordingOps({LIST: efi(extra=[NEW])})
    with pytest.raises(ArmError, match="already exists"):
        get_arm("uefi-bootnext").prepare(ops, profile(), None)


def test_prepare_refuses_existing_bootnext_like_the_kit():
    ops = RecordingOps({LIST: efi(nxt="0002")})
    with pytest.raises(ArmError, match="BootNext is already set"):
        get_arm("uefi-bootnext").prepare(ops, profile(), None)


def test_prepare_refuses_missing_boot_order():
    ops = RecordingOps({LIST: "BootCurrent: 0001\n"})
    with pytest.raises(ArmError, match="BootOrder"):
        get_arm("uefi-bootnext").prepare(ops, profile(), None)


def test_arm_happy_path_exact_vectors_next_only():
    ops = happy_ops()
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    rec = a.arm(ops, profile(), rec)
    assert rec.entry_number == "0005"
    assert rec.next_armed is True
    assert ops.log == [
        LIST,
        LIST,
        f"efibootmgr -C -d /dev/mmcblk0 -p 11 -L {LABEL} -l {LOADER} -u bootmode=bootimg",
        LIST,
        "efibootmgr -n 0005",
        LIST,
    ]
    assert_no_order_edits(ops)


def test_arm_entry_number_falls_back_to_relisting():
    ops = happy_ops()
    key = f"efibootmgr -C -d /dev/mmcblk0 -p 11 -L {LABEL} -l {LOADER} -u bootmode=bootimg"
    ops.script[key] = ""
    a = get_arm("uefi-bootnext")
    rec = a.arm(ops, profile(), a.prepare(ops, profile(), None))
    assert rec.entry_number == "0005"


def test_firmware_rewriting_boot_order_after_create_fails_do_not_reboot():
    ops = happy_ops(after_order="0005,0001,0002,0003")
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError) as ei:
        a.arm(ops, profile(), rec)
    msg = str(ei.value)
    assert "DO NOT REBOOT" in msg and "restore" in msg
    assert ei.value.record.entry_number == "0005"
    assert "efibootmgr -n 0005" not in ops.log  # never armed
    assert_no_order_edits(ops)


def test_firmware_rewriting_boot_order_after_next_fails():
    ops = RecordingOps(
        {
            LIST: [
                efi(),
                efi(),
                efi(extra=[NEW]),
                efi(extra=[NEW], order="0005,0001,0002,0003", nxt="0005"),
            ],
        }
    )
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError, match="DO NOT REBOOT") as ei:
        a.arm(ops, profile(), rec)
    assert ei.value.record.next_armed is True
    assert_no_order_edits(ops)


def test_boot_order_changed_before_create_stops_before_any_mutation():
    ops = RecordingOps({LIST: [efi(), efi(order="0002,0001")]})
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError, match="changed"):
        a.arm(ops, profile(), rec)
    assert not any("-C" in line.split() for line in ops.log)


def test_bootnext_not_reading_back_fails():
    ops = RecordingOps(
        {LIST: [efi(), efi(), efi(extra=[NEW]), efi(extra=[NEW])]},
    )
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError, match="DO NOT REBOOT"):
        a.arm(ops, profile(), rec)


def test_disarm_clears_next_and_deletes_only_recorded_entry():
    ops = RecordingOps({LIST: efi(extra=[NEW], nxt="0005")})
    rec = ArmRecord(
        entry_number="0005",
        label=LABEL,
        preexisting_boot_order="0001,0002,0003",
        preexisting_next="",
        next_armed=True,
    )
    get_arm("uefi-bootnext").disarm(ops, rec)
    assert ops.log == [LIST, "efibootmgr -N", "efibootmgr -B -b 0005"]
    assert_no_order_edits(ops)


def test_disarm_refuses_entry_with_different_label():
    other = "Boot0005* something-else\tHD(1,GPT)"
    ops = RecordingOps({LIST: efi(extra=[other])})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", False)
    notes = get_arm("uefi-bootnext").disarm(ops, rec)
    assert not any("-B" in line.split() for line in ops.log)
    assert any("leaving" in n for n in notes)


def test_disarm_leaves_foreign_bootnext_alone():
    ops = RecordingOps({LIST: efi(extra=[NEW], nxt="0002")})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", True)
    get_arm("uefi-bootnext").disarm(ops, rec)
    assert "efibootmgr -N" not in ops.log
    assert "efibootmgr -B -b 0005" in ops.log


def test_disarm_without_entry_does_nothing():
    ops = RecordingOps()
    get_arm("uefi-bootnext").disarm(ops, ArmRecord("", LABEL, "0001", "", False))
    assert ops.log == []


def test_none_arm_does_nothing():
    ops = RecordingOps()
    a = get_arm("none")
    rec = a.prepare(ops, profile("none"), None)
    rec = a.arm(ops, profile("none"), rec)
    a.disarm(ops, rec)
    assert ops.log == []
    assert rec.entry_number == "" and rec.next_armed is False


def test_unknown_names():
    with pytest.raises(KeyError):
        get_arm("evil")
    with pytest.raises(KeyError):
        get_guard("evil")


def test_record_round_trips():
    rec = ArmRecord("0005", LABEL, "0001,0002", "", True)
    assert ArmRecord.from_dict(rec.to_dict()) == rec


# ----------------------------------------------------------------- guard


def header(cmdline=ARG, extra="", magic=b"ANDROID!", version=0):
    h = bytearray(2048)
    h[0:8] = magic
    h[40:44] = struct.pack("<I", version)
    c = cmdline.encode()
    h[64 : 64 + len(c)] = c
    e = extra.encode()
    h[608 : 608 + len(e)] = e
    return bytes(h)


NODES = {"A_kernel": "/dev/mmcblk0p3", "B_kernel": "/dev/mmcblk0p6"}


def dd_key(node):
    return f"dd if={node} bs=2048 count=1 status=none"


def guard_ops(a, b):
    return RecordingOps({dd_key("/dev/mmcblk0p3"): a, dd_key("/dev/mmcblk0p6"): b})


def test_guard_passes_when_argument_present_on_both():
    ops = guard_ops(header("root=/dev/x " + ARG + " quiet"), header(ARG))
    get_guard("boot-arg").check(ops, profile(), NODES)
    assert ops.log == [dd_key("/dev/mmcblk0p3"), dd_key("/dev/mmcblk0p6")]
    assert not any("of=" in line for line in ops.log)


def test_guard_refuses_missing_argument():
    ops = guard_ops(header("root=/dev/x"), header(ARG))
    with pytest.raises(GuardError, match="A_kernel"):
        get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_token_match_is_exact():
    ops = guard_ops(header(ARG + "y"), header(ARG))
    with pytest.raises(GuardError):
        get_guard("boot-arg").check(ops, profile(), NODES)
    ops = guard_ops(header("x" + ARG), header(ARG))
    with pytest.raises(GuardError):
        get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_counts_argument_in_extra_cmdline_like_the_kit():
    ops = guard_ops(header("root=/dev/x", extra=ARG), header("a", extra="b " + ARG))
    get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_kit_concatenation_quirk_is_preserved():
    # kit: cmdline_has_arg tests BC_A+BC_B joined with and without a space.
    ops = guard_ops(header("quiet module_blacklist=nvme,", extra="nvme_core,pcie_tegra194"), header(ARG))
    get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_rejects_bad_magic_and_version_and_short_read():
    for bad in (header(magic=b"NOTANDRO"), header(version=7), b"ANDROID!"):
        ops = guard_ops(bad, header(ARG))
        with pytest.raises(GuardError):
            get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_unknown_partition_node():
    ops = guard_ops(header(), header())
    with pytest.raises(GuardError, match="B_kernel"):
        get_guard("boot-arg").check(ops, profile(), {"A_kernel": "/dev/mmcblk0p3"})


def test_guard_safe_under_read_only_ops():
    inner = guard_ops(header(), header())
    ro = ReadOnlyOps(inner)
    get_guard("boot-arg").check(ro, profile(), NODES)
    with pytest.raises(MutationRefused):
        ro.efibootmgr_next("0005")
    assert not any(line.startswith("efibootmgr") for line in inner.log)


def test_guard_none_does_nothing():
    ops = RecordingOps()
    get_guard("none").check(ops, profile(), NODES)
    assert ops.log == []


def test_no_unbind_or_detach_in_source():
    import pathlib

    src = pathlib.Path(armmod.__file__).read_text()
    for word in ("unbind", "detach", "sysfs_write"):
        assert word not in src


# ------------------------------------------------------ staged image check


STAGE = "/run/stage"


def staged_profile():
    p = profile()
    p.layout = NS(params={"table": [
        {"number": 3, "name": "A_kernel"}, {"number": 6, "name": "B_kernel"},
    ]})
    p.images = {
        "kernel_a": NS(partition=3, file="boot.img"),
        "kernel_b": NS(partition=6, file="boot-b.img"),
        "esp": NS(partition=11, file="esp.img"),
    }
    return p


def reader(files):
    seen = []

    def read(path):
        seen.append(path)
        return files[path]

    read.seen = seen
    return read


def test_staged_check_passes_and_reads_each_mapped_file():
    rd = reader({f"{STAGE}/boot.img": header("a " + ARG), f"{STAGE}/boot-b.img": header(ARG)})
    get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)
    assert rd.seen == [f"{STAGE}/boot.img", f"{STAGE}/boot-b.img"]


def test_staged_check_refuses_missing_argument_with_kit_wording():
    rd = reader({f"{STAGE}/boot.img": header("root=/dev/x"), f"{STAGE}/boot-b.img": header(ARG)})
    with pytest.raises(GuardError) as ei:
        get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)
    assert str(ei.value) == f"staged boot image boot.img lacks the required argument {ARG} (guard boot-arg)"


def test_staged_check_near_miss_wrong_version_and_missing_magic_refused():
    for bad in (header(ARG + "y"), header("x" + ARG), header(version=3), header(magic=b"NOTANDRO"), b"ANDROID!"):
        rd = reader({f"{STAGE}/boot.img": header(ARG), f"{STAGE}/boot-b.img": bad})
        with pytest.raises(GuardError, match="boot-b.img"):
            get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)


def test_staged_check_accepts_extra_cmdline():
    rd = reader({f"{STAGE}/boot.img": header("a", extra=ARG), f"{STAGE}/boot-b.img": header(ARG)})
    get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)


def test_staged_check_unmapped_guard_partition_is_a_profile_error():
    p = staged_profile()
    del p.images["kernel_b"]
    rd = reader({f"{STAGE}/boot.img": header(ARG)})
    with pytest.raises(GuardError, match="B_kernel"):
        get_guard("boot-arg").check_staged(p, STAGE, rd)


def test_staged_check_unreadable_file_refused():
    def rd(path):
        raise FileNotFoundError(path)

    with pytest.raises(GuardError, match="boot.img"):
        get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)


def test_staged_check_none_guard_reads_nothing():
    rd = reader({})
    get_guard("none").check_staged(staged_profile(), STAGE, rd)
    assert rd.seen == []


def test_read_staged_header_is_bounded(tmp_path):
    f = tmp_path / "x.img"
    f.write_bytes(b"A" * 10000)
    assert len(armmod.read_staged_header(str(f))) == 2048


# --- 5.21: the label match is anchored to the end of the description ----------


@pytest.mark.parametrize(
    "line",
    [
        f"Boot0007* {LABEL} old\tHD(1,GPT)",  # a longer label that starts with ours
        f"Boot0007* {LABEL} old",  # same, without -v's device path
        f"Boot0007* {LABEL}-old\tHD(1,GPT)",
        f"Boot0007* {LABEL}x\tHD(1,GPT)",  # ours as a prefix of another word
        f"Boot0007* {LABEL}_2",
        f"Boot0007* {LABEL}.efi\tHD(1,GPT)",
    ],
)
def test_entries_with_label_does_not_match_a_longer_label(line):
    assert entries_with_label(efi(extra=[line]), LABEL) == []


@pytest.mark.parametrize(
    "line",
    [
        f"Boot0007* {LABEL}\tHD(1,GPT)/File(x)",  # -v: label, tab, device path
        f"Boot0007* {LABEL}",  # no -v: end of line
        f"Boot0007* {LABEL}  ",  # trailing blanks at the end of the line
        f"Boot0007  {LABEL}\tHD(1,GPT)",  # inactive entry (no asterisk)
        f"Boot0007* {LABEL}\r",  # CR line ending
        f"Boot0007* {LABEL}  \r",  # trailing blanks then CR
        f"Boot0007* {LABEL}\tHD(1,GPT)\r",
    ],
)
def test_entries_with_label_matches_the_exact_label(line):
    assert entries_with_label(efi(extra=[line]), LABEL) == ["0007"]


def test_entries_with_label_still_refuses_a_longer_label_with_a_cr_ending():
    assert entries_with_label(efi(extra=[f"Boot0007* {LABEL} old\r"]), LABEL) == []


def test_entries_with_label_is_found_in_the_middle_of_a_listing():
    text = efi(extra=[f"Boot0007* {LABEL} old\tx", NEW, "Boot0009* UEFI Shell"])
    assert entries_with_label(text, LABEL) == ["0005"]


def test_disarm_does_not_delete_a_longer_labelled_entry_with_the_recorded_number():
    longer = f"Boot0005* {LABEL} old\tHD(1,GPT)"
    ops = RecordingOps({LIST: efi(extra=[longer])})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", False)
    notes = get_arm("uefi-bootnext").disarm(ops, rec)
    assert not any("-B" in line.split() for line in ops.log)
    assert any("leaving" in n for n in notes)


def test_disarm_with_a_foreign_label_under_the_recorded_number_makes_no_efi_change_even_with_bootnext():
    foreign = "Boot0005* something-else\tHD(1,GPT)"
    ops = RecordingOps({LIST: efi(extra=[foreign], nxt="0005")})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", True)
    notes = get_arm("uefi-bootnext").disarm(ops, rec)
    assert ops.log == [LIST]
    assert any("leaving" in n for n in notes)


def test_disarm_refuses_a_recorded_entry_that_is_in_boot_order():
    ops = RecordingOps({LIST: efi(order="0001,0005,0002", extra=[NEW], nxt="0005")})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", True)
    with pytest.raises(ArmError, match="BootOrder"):
        get_arm("uefi-bootnext").disarm(ops, rec)
    assert ops.log == [LIST]


def test_disarm_refuses_a_recorded_entry_that_is_boot_current():
    live = efi(extra=[NEW], nxt="0005").replace("BootCurrent: 0001", "BootCurrent: 0005")
    ops = RecordingOps({LIST: live})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", True)
    with pytest.raises(ArmError, match="BootCurrent"):
        get_arm("uefi-bootnext").disarm(ops, rec)
    assert ops.log == [LIST]


# ---- 5.33: each command-line field ends at its first NUL, like the kernel's ----


def _after_nul(field_after):
    return header("root=/dev/x \0 " + field_after)


def test_parse_boot_header_stops_each_field_at_its_first_nul():
    a, b = armmod.parse_boot_header(header("one\0two", extra="three\0four"), "n")
    assert (a, b) == ("one", "three")


def test_guard_refuses_an_argument_that_only_appears_after_a_nul():
    ops = guard_ops(_after_nul(ARG), header(ARG))
    with pytest.raises(GuardError, match="A_kernel"):
        get_guard("boot-arg").check(ops, profile(), NODES)


def test_guard_refuses_an_argument_after_a_nul_in_the_extra_field():
    ops = guard_ops(header("root=/dev/x", extra="a \0 " + ARG), header(ARG))
    with pytest.raises(GuardError):
        get_guard("boot-arg").check(ops, profile(), NODES)


def test_staged_guard_refuses_an_argument_that_only_appears_after_a_nul():
    rd = reader({f"{STAGE}/boot.img": _after_nul(ARG), f"{STAGE}/boot-b.img": header(ARG)})
    with pytest.raises(GuardError, match="boot.img"):
        get_guard("boot-arg").check_staged(staged_profile(), STAGE, rd)


# ------------------------------------------------- CRLF and re-check before create


def _crlf(text):
    return text.replace("\n", "\r\n")


def test_boot_order_and_next_strip_a_trailing_carriage_return():
    text = _crlf(efi(nxt="0005"))
    assert armmod.boot_order_of(text) == "0001,0002,0003"
    assert armmod.boot_next_of(text) == "0005"


def test_disarm_clears_bootnext_when_efibootmgr_output_is_crlf():
    ops = RecordingOps({LIST: _crlf(efi(extra=[NEW], nxt="0005"))})
    rec = ArmRecord("0005", LABEL, "0001,0002,0003", "", True)
    get_arm("uefi-bootnext").disarm(ops, rec)
    assert ops.log == [LIST, "efibootmgr -N", "efibootmgr -B -b 0005"]


def test_arm_refuses_a_bootnext_set_after_prepare_before_any_mutation():
    ops = RecordingOps({LIST: [efi(), efi(nxt="0002")]})
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError, match="BootNext"):
        a.arm(ops, profile(), rec)
    assert ops.log == [LIST, LIST]


def test_arm_refuses_a_labelled_entry_that_appeared_after_prepare_before_any_mutation():
    ops = RecordingOps({LIST: [efi(), efi(extra=[NEW])]})
    a = get_arm("uefi-bootnext")
    rec = a.prepare(ops, profile(), None)
    with pytest.raises(ArmError, match="already exists"):
        a.arm(ops, profile(), rec)
    assert ops.log == [LIST, LIST]
