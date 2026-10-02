"""Arm and guard strategies: one-shot UEFI boot entry and boot-image check.

Ports the bash kit's install.sh logic (efibootmgr snapshot parsing, the
BootOrder-unchanged check, the Android boot image header cmdline check).
Arm strategies only ever create one entry with ``-C`` and set the next boot
with ``-n``; they never write the boot order (no ``-o``, ``-O`` or ``-c``)
and never touch an entry other than the one they recorded. The boot-arg
guard only reads. Every board action goes through ``Ops``.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

RESTORE_HINT = "run `restore` to undo what this run changed"
_ANDROID_MAGIC = b"ANDROID!"
_HEADER_BYTES = 2048


class ArmError(Exception):
    """Arming failed or could not be verified; ``record`` names what exists."""

    def __init__(self, message, record=None):
        super().__init__(message)
        self.record = record


class GuardError(Exception):
    """A guard refused: the target does not satisfy the profile's requirement."""


@dataclass
class ArmRecord:
    entry_number: str = ""
    label: str = ""
    preexisting_boot_order: str = ""
    preexisting_next: str = ""
    next_armed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArmRecord":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


# ------------------------------------------------------------ efibootmgr text


def _field(text: str, name: str) -> str:
    m = re.search(rf"^{name}:[ \t]*(.*?)[ \t\r]*$", text, re.MULTILINE)
    return m.group(1) if m else ""


def boot_order_of(text: str) -> str:
    return _field(text, "BootOrder")


def boot_next_of(text: str) -> str:
    return _field(text, "BootNext")


def entries_with_label(text: str, label: str) -> list:
    """Upper-case entry numbers whose label is exactly ``label``.

    The label ends where the description ends: at the tab ``efibootmgr -v``
    prints before the device path, or at the end of the line (plus trailing
    blanks) in the plain listing (a CR before the newline is part of the line ending). A space does not end it, so ``label old`` is
    another entry's longer label and is never ours.
    """
    rx = re.compile(rf"^Boot([0-9A-Fa-f]{{4}})\*?[ \t]+{re.escape(label)}(\t|[ \t]*\r?$)", re.MULTILINE)
    return [m.group(1).upper() for m in rx.finditer(text)]


def bootable_entries(live: str, ours) -> dict:
    """Entries of ``ours`` the firmware may boot: in BootOrder, or the one just booted. Number -> reason."""
    order = {e.strip().upper() for e in boot_order_of(live).split(",") if e.strip()}
    current = _field(live, "BootCurrent").upper()
    why = {}
    for num in ours:
        if num in order:
            why[num] = "is in BootOrder"
        elif current and num == current:
            why[num] = "is BootCurrent (the board booted it)"
    return why


# ------------------------------------------------------------------------ arm


class NoneArm:
    """Arms nothing."""

    def prepare(self, ops, profile, state=None) -> ArmRecord:
        return ArmRecord()

    def arm(self, ops, profile, record) -> ArmRecord:
        return record

    def disarm(self, ops, record) -> list:
        return []


class Arm:
    """uefi-bootnext: one-shot entry plus ``efibootmgr -n``, BootOrder untouched."""

    def prepare(self, ops, profile, state=None) -> ArmRecord:
        label = profile.arm.params["label"]
        text = ops.efibootmgr_list()
        order = boot_order_of(text)
        if not order:
            raise ArmError("no BootOrder line in efibootmgr -v output; cannot verify it later")
        nxt = boot_next_of(text)
        if nxt:
            # Kit: refuse rather than replace someone else's one-shot.
            raise ArmError(f"BootNext is already set ({nxt}); refusing to replace another one-shot")
        if entries_with_label(text, label):
            raise ArmError(f"a boot entry labelled {label} already exists; {RESTORE_HINT}")
        return ArmRecord(
            label=label, preexisting_boot_order=order, preexisting_next=nxt
        )

    def arm(self, ops, profile, record) -> ArmRecord:
        params = profile.arm.params
        label = params["label"]
        order = record.preexisting_boot_order
        if not order:
            raise ArmError("record has no BootOrder to verify against", record)
        pre = ops.efibootmgr_list()
        if boot_order_of(pre) != order:
            raise ArmError(
                "BootOrder changed since it was recorded; stopping before any boot entry call",
                record,
            )
        nxt = boot_next_of(pre)
        if nxt:
            raise ArmError(
                f"BootNext is set ({nxt}) since the plan was prepared; refusing to replace "
                "another one-shot; no boot entry was created",
                record,
            )
        if entries_with_label(pre, label):
            raise ArmError(
                f"a boot entry labelled {label} already exists; no boot entry was created; "
                f"{RESTORE_HINT}",
                record,
            )
        out = ops.efibootmgr_create(
            profile.target.device,
            profile.images["esp"].partition,
            label,
            params["loader_path"],
            params.get("boot_args", ""),
        )
        after = ops.efibootmgr_list()
        found = entries_with_label(out.text, label) or entries_with_label(after, label)
        if not found:
            raise ArmError(
                f"cannot find the new boot entry number; DO NOT REBOOT. Inspect "
                f"`efibootmgr -v` by hand and {RESTORE_HINT}",
                record,
            )
        record.entry_number = found[0]
        if record.entry_number not in entries_with_label(after, label):
            raise ArmError(
                f"entry {record.entry_number} is not listed by efibootmgr -v; DO NOT REBOOT; "
                f"{RESTORE_HINT}",
                record,
            )
        if boot_order_of(after) != order:
            raise ArmError(
                f"BootOrder changed after creating entry {record.entry_number}; NOT arming "
                f"BootNext. DO NOT REBOOT; {RESTORE_HINT}",
                record,
            )
        ops.efibootmgr_next(record.entry_number)
        record.next_armed = True
        final = ops.efibootmgr_list()
        if boot_order_of(final) != order:
            raise ArmError(
                f"BootOrder differs from the recorded one after arming BootNext. DO NOT REBOOT; "
                f"{RESTORE_HINT}",
                record,
            )
        if boot_next_of(final).upper() != record.entry_number:
            raise ArmError(
                f"BootNext does not read back as {record.entry_number}. DO NOT REBOOT; "
                f"{RESTORE_HINT}",
                record,
            )
        return record

    def disarm(self, ops, record) -> list:
        """Clear our BootNext and delete only the entry we created; notes returned."""
        notes = []
        if not record.entry_number and not record.next_armed:
            return notes
        live = ops.efibootmgr_list()
        number = record.entry_number.upper()
        if number and number not in entries_with_label(live, record.label):
            notes.append(
                f"boot entry {record.entry_number} with label {record.label} not found; "
                "leaving the boot entries alone"
            )
            return notes
        bootable = bootable_entries(live, [number]) if number else {}
        if bootable:
            raise ArmError(
                f"refusing: boot entry {number} carries this tool's label but {bootable[number]}; no boot "
                "entry was changed; inspect `efibootmgr -v` and remove the entry by hand if it is really ours"
            )
        if record.next_armed and boot_next_of(live).upper() == number:
            ops.efibootmgr_delete_next()
            notes.append(f"cleared BootNext {record.entry_number}")
        if number:
            ops.efibootmgr_delete(record.entry_number)
            notes.append(f"deleted boot entry {record.entry_number}")
        return notes


_ARMS = {"uefi-bootnext": Arm, "none": NoneArm}


def get_arm(name):
    return _ARMS[name]()


# ---------------------------------------------------------------------- guard


class NoneGuard:
    def check(self, ops, profile, node_by_partition_name) -> None:
        return None

    def check_staged(self, profile, staging_dir, file_reader=None) -> None:
        return None


def read_staged_header(path):
    """Bounded read of the first header bytes of a staged image file."""
    with open(path, "rb") as fh:
        return fh.read(_HEADER_BYTES)


def parse_boot_header(hdr, where):
    """Return (cmdline, extra_cmdline) from Android boot image header bytes.

    The single place the header is validated and decoded; ``where`` names the
    source (a device node or a staged file) in the refusal text.
    """
    if len(hdr) < _HEADER_BYTES:
        raise GuardError(f"{where}: short read of the boot image header ({len(hdr)} bytes)")
    if hdr[:8] != _ANDROID_MAGIC:
        raise GuardError(f"{where} does not start with an Android boot image header (magic ANDROID!)")
    version = int.from_bytes(hdr[40:44], "little")
    if version not in (0, 1, 2):
        raise GuardError(f"{where}: boot image header_version {version} is not understood (0, 1, 2)")
    # The kernel reads each fixed-width field as a C string: it ends at the first NUL.
    a = hdr[64:576].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    b = hdr[608:1632].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return a, b


def read_boot_cmdline(ops, node):
    """Return (cmdline, extra_cmdline) from the Android boot image header at node."""
    return parse_boot_header(ops.dd_read(node, 2048, count=1), node)


def cmdline_has_arg(arg, a, b) -> bool:
    """Whole-token match over cmdline+extra, joined as the kit does (both ways)."""
    return f" {arg} " in f" {a}{b} " or f" {arg} " in f" {a} {b} "


class BootArgGuard:
    """boot-arg: refuse unless every guard partition's boot image carries the argument."""

    def check(self, ops, profile, node_by_partition_name) -> None:
        params = profile.guard.params
        arg = params["argument"]
        for name in params["partitions"]:
            node = node_by_partition_name.get(name)
            if node is None:
                raise GuardError(f"no device node known for guard partition {name}")
            a, b = read_boot_cmdline(ops, node)
            if not cmdline_has_arg(arg, a, b):
                raise GuardError(
                    f"{name} ({node}): boot image cmdline lacks required argument "
                    f"'{arg}'; refusing to arm"
                )

    def check_staged(self, profile, staging_dir, file_reader=None) -> None:
        """Same rules as ``check``, read from the staged files before any write."""
        reader = file_reader or read_staged_header
        params = profile.guard.params
        arg = params["argument"]
        number_of = {p["name"]: p["number"] for p in profile.layout.params["table"]}
        for name in params["partitions"]:
            img = next(
                (i for i in profile.images.values() if i.partition == number_of.get(name)), None
            )
            if img is None:
                raise GuardError(f"no image is mapped to guard partition {name}; fix the profile")
            try:
                hdr = reader(f"{staging_dir}/{img.file}")
            except OSError as exc:
                raise GuardError(f"staged boot image {img.file} cannot be read: {exc}") from None
            try:
                a, b = parse_boot_header(hdr, f"staged boot image {img.file}")
            except GuardError as exc:
                raise GuardError(f"{exc} (guard boot-arg)") from None
            if not cmdline_has_arg(arg, a, b):
                raise GuardError(
                    f"staged boot image {img.file} lacks the required argument {arg} (guard boot-arg)"
                )


_GUARDS = {"boot-arg": BootArgGuard, "none": NoneGuard}


def get_guard(name):
    return _GUARDS[name]()


__all__ = [
    "Arm", "ArmError", "ArmRecord", "BootArgGuard", "GuardError", "NoneArm", "NoneGuard",
    "cmdline_has_arg", "get_arm", "get_guard", "parse_boot_header", "read_boot_cmdline",
    "read_staged_header",
]  # fmt: skip
