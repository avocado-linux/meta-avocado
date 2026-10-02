"""Arm and guard strategies: one-shot UEFI boot entry and boot-image check.

Ports the bash kit's install.sh logic (efibootmgr snapshot parsing, the
BootOrder-unchanged check, the Android boot image header cmdline check).
The arm strategy selects the firmware's own storage entry with ``-n`` and
clears BootNext with ``-N``; it never creates, deletes or reorders a boot
entry (no ``-C``, ``-B``, ``-b``, ``-o``, ``-O`` or ``-c``). The boot-arg
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


# ------------------------------------------------------------------------ arm


class NoneArm:
    """Arms nothing."""

    def prepare(self, ops, profile, state=None) -> ArmRecord:
        return ArmRecord()

    def arm(self, ops, profile, record) -> ArmRecord:
        return record

    def disarm(self, ops, record) -> list:
        return []


def _count_phrase(n: int) -> str:
    return f"{n} boot {'entry' if n == 1 else 'entries'}"


def _single_entry(text: str, label: str, where: str, record=None) -> str:
    """The one entry number carrying ``label``; any other count refuses, naming count and label."""
    found = entries_with_label(text, label)
    if len(found) != 1:
        raise ArmError(
            f"{where}: found {_count_phrase(len(found))} labelled {label!r}, expected exactly one; "
            "no boot variable was changed",
            record,
        )
    return found[0]


class Arm:
    """uefi-bootnext: select the firmware's own storage entry with ``efibootmgr -n``.

    No boot entry is ever created, deleted or reordered: the firmware lists a
    storage entry with a full device path, and only that entry is honoured by
    BootNext (a short-form entry made by ``-C`` is ignored by the target firmware).
    """

    def prepare(self, ops, profile, state=None) -> ArmRecord:
        label = profile.arm.params["entry_label"]
        text = ops.efibootmgr_list()
        order = boot_order_of(text)
        if not order:
            raise ArmError("no BootOrder line in efibootmgr -v output; cannot verify it later")
        nxt = boot_next_of(text)
        if nxt:
            # Kit: refuse rather than replace someone else's one-shot.
            raise ArmError(f"BootNext is already set ({nxt}); refusing to replace another one-shot")
        entry = _single_entry(text, label, "prepare")
        return ArmRecord(
            entry_number=entry, label=label, preexisting_boot_order=order, preexisting_next=nxt
        )

    def arm(self, ops, profile, record) -> ArmRecord:
        label = profile.arm.params["entry_label"]
        order = record.preexisting_boot_order
        if not order:
            raise ArmError("record has no BootOrder to verify against", record)
        pre = ops.efibootmgr_list()
        if boot_order_of(pre) != order:
            raise ArmError(
                "BootOrder changed since it was recorded; stopping before any boot variable call",
                record,
            )
        nxt = boot_next_of(pre)
        if nxt:
            raise ArmError(
                f"BootNext is set ({nxt}) since the plan was prepared; refusing to replace "
                "another one-shot; no boot variable was changed",
                record,
            )
        entry = _single_entry(pre, label, "arm", record)
        if record.entry_number and record.entry_number.upper() != entry:
            raise ArmError(
                f"the entry labelled {label!r} is Boot{entry} now but was Boot{record.entry_number} when "
                "it was recorded; no boot variable was changed",
                record,
            )
        record.entry_number = entry
        record.label = label
        ops.efibootmgr_next(entry)
        record.next_armed = True
        final = ops.efibootmgr_list()
        if boot_order_of(final) != order:
            raise ArmError(
                f"BootOrder differs from the recorded one after arming BootNext. DO NOT REBOOT; "
                f"{RESTORE_HINT}",
                record,
            )
        if boot_next_of(final).upper() != entry:
            raise ArmError(
                f"BootNext does not read back as {entry}. DO NOT REBOOT; {RESTORE_HINT}",
                record,
            )
        return record

    def disarm(self, ops, record) -> list:
        """Clear BootNext when it names the recorded entry; delete nothing. Notes returned."""
        notes = []
        if not record.entry_number and not record.next_armed:
            return notes
        live = ops.efibootmgr_list()
        number = record.entry_number.upper()
        if not number:
            # The arm step began but the record never learned the number: use the label only when
            # it still identifies exactly one entry.
            ours = entries_with_label(live, record.label)
            if len(ours) != 1:
                notes.append(
                    f"found {_count_phrase(len(ours))} labelled {record.label!r} and no recorded number; "
                    "leaving the boot entries and BootNext alone"
                )
                return notes
            number = ours[0]
        if number not in entries_with_label(live, record.label):
            notes.append(
                f"boot entry {record.entry_number} no longer carries the label {record.label!r}; "
                "leaving the boot entries and BootNext alone"
            )
            return notes
        nxt = boot_next_of(live).upper()
        if nxt == number:
            ops.efibootmgr_delete_next()
            notes.append(f"cleared BootNext {number}")
        elif not nxt:
            notes.append("BootNext is already consumed by a boot (or cleared); nothing to clear")
        else:
            notes.append(f"BootNext names {nxt}, not {number}; leaving it alone")
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
