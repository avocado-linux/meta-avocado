"""The ``plan`` subcommand: look, decide, write one plan record, change nothing.

Everything the plan learns about the board goes through the injected ops
object, which the caller wraps in ``ReadOnlyOps``; this module never imports
subprocess and never touches the filesystem itself. The only write is the plan
record, handed to an injected ``record_writer`` (default: the evidence
module's atomic writer into the run directory).

Output keeps the section structure and wording of the bash kit's dry run
(``tests/remote/golden/real-board-dry-run.txt``). Lines this tool adds sit in
a header block that ends at ``BODY_MARKER``; everything after the marker is
the kit-comparable body.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable

from . import arm as armmod
from . import evidence, images, layout
from .ops import Ops, OpsError

SCHEMA_VERSION = 1
RECORD_NAME = "plan.json"
BODY_MARKER = "== plan =="
DONE_LINE = "dry run complete: no mutating tool was called"
UNAVAILABLE = "unavailable"
# The sha256sum-format file the host stages (the bash kit calls it MANIFEST).
# Same value as cmd_check.MANIFEST; kept local so plan does not import check.
MANIFEST_NAME = "MANIFEST.hashes"
# Kit install.sh prints this in the section title; it names the design doc
# the layout was validated against.
_LAYOUT_REF = "boot-design.md section 1"

_DEVICE_RE = re.compile(r"^/dev/(?:mmcblk[0-9]+|sd[a-z]+|vd[a-z]+)$")
_PARENT_RES = (
    re.compile(r"^(/dev/(?:mmcblk[0-9]+|nvme[0-9]+n[0-9]+|loop[0-9]+))p[0-9]+$"),
    re.compile(r"^(/dev/(?:sd|vd|hd)[a-z]+)[0-9]+$"),
)
_SUM_RE = re.compile(r"^([0-9a-fA-F]{64})[ \t][ *](.+)$")
_NO_TABLE_RE = re.compile(r"recognized partition table|no partition table", re.I)
_SAFE_RE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


class _Refusal(Exception):
    pass


@dataclass
class PlanResult:
    exit_code: int
    plan_record: dict | None
    lines: list = field(default_factory=list)


def _q(arg: str) -> str:
    """Quote like bash printf %q, which the kit's dry run uses."""
    if arg and _SAFE_RE.match(arg):
        return arg
    return "".join(c if _SAFE_RE.match(c) else "\\" + c for c in arg)


def _parent_disk(source: str) -> str:
    for rx in _PARENT_RES:
        m = rx.match(source)
        if m:
            return m.group(1)
    return source


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(ops: Ops, path: str) -> str | None:
    try:
        return ops.read_file(path).decode("utf-8", errors="replace").strip()
    except (OSError, OpsError):
        return None


# ------------------------------------------------------------------ checks


def _check_device(device: str) -> None:
    if "nvme" in device:
        raise _Refusal(f"refusing {device}: this tool never touches an NVMe device")
    if not _DEVICE_RE.match(device):
        raise _Refusal(f"refusing {device}: not a whole eMMC/SD/virtio disk node")


def _check_sectors(ops: Ops, profile) -> None:
    dev = profile.target.device
    got = ops.blockdev_getsz(dev)
    if got != profile.target.sectors:
        raise _Refusal(f"{dev} has {got} sectors, expected {profile.target.sectors}")


def _check_not_in_use(ops: Ops, profile, staging_dir: str) -> None:
    dev = profile.target.device
    for what, path in (
        ("running root", "/"),
        ("staging directory", staging_dir),
        ("SSH path", "/etc/ssh"),
    ):
        res = ops.run_read(["findmnt", "-no", "SOURCE", "-T", path], check=False)
        if res.rc != 0:
            continue
        source = res.text.strip()
        if source and _parent_disk(source) == dev:
            raise _Refusal(f"{dev} backs the {what} ({path} is on {source}); refusing")
    for source in ops.findmnt_source():
        if _parent_disk(source.strip()) == dev:
            raise _Refusal(f"{dev} or one of its partitions is mounted ({source.strip()})")


def _check_empty(ops: Ops, profile) -> None:
    dev = profile.target.device
    name = posixpath.basename(dev)
    out = ops.lsblk(dev, "NAME,TYPE", check=True).text
    parts = [ln for ln in out.splitlines() if len(ln.split()) >= 2 and ln.split()[1] == "part"]
    if parts:
        raise _Refusal(f"lsblk shows {len(parts)} partition(s) on {dev}; refusing a disk that is not empty")
    res = ops.sfdisk_dump(dev, check=False)
    if res.rc != 0:
        if _NO_TABLE_RE.search(res.stderr):
            return
        raise _Refusal(f"sfdisk --dump {dev} failed (rc={res.rc}): {res.stderr.strip()[:200]}")
    if any(ln.startswith(("label:", "label-id:")) or ln.startswith(dev) for ln in res.text.splitlines()):
        raise _Refusal(f"{dev} already carries a partition table; refusing ({name})")


def _resolve_identity(ops: Ops, profile) -> tuple[str, str]:
    """Apply the profile identity constraint; return (verified value, device serial)."""
    dev = profile.target.device
    name = posixpath.basename(dev)
    ident = profile.target.identity
    serial_path = f"/sys/block/{name}/device/serial"
    serial = _read_text(ops, serial_path) or UNAVAILABLE
    if ident.kind == "sysfs-name":
        if name != ident.value:
            raise _Refusal(f"device identity mismatch: {dev} is sysfs name {name}, profile expects {ident.value}")
        return name, serial
    if ident.kind == "serial":
        attr = ident.sysfs_attr or "serial"
        got = _read_text(ops, f"/sys/block/{name}/device/{attr}")
        if got is None:
            raise _Refusal(f"device identity cannot be verified: /sys/block/{name}/device/{attr} is unreadable")
        if got != ident.value:
            raise _Refusal(f"device identity mismatch: serial {got!r}, profile expects {ident.value!r}")
        return got, got
    # by-path: no portable read-only probe; say so rather than claim a match.
    return "unverified", serial


def _parse_manifest(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = _SUM_RE.match(line.rstrip("\r"))
        if m:
            path = m.group(2)
            out[path[2:] if path.startswith("./") else path] = m.group(1).lower()
    return out


def _check_images(ops: Ops, profile, staging_dir: str, scanner) -> tuple[dict, int]:
    manifest_path = f"{staging_dir}/{MANIFEST_NAME}"
    try:
        raw = ops.read_file(manifest_path)
    except (OSError, OpsError) as exc:
        raise _Refusal(f"manifest not found: {manifest_path} ({exc})") from exc
    manifest = _parse_manifest(raw.decode("utf-8", errors="replace"))
    if not manifest:
        raise _Refusal(f"manifest {manifest_path} lists no sha256 checksums")
    scans: dict = {}
    for role, img in profile.images.items():
        if img.file not in manifest:
            raise _Refusal(f"{role} image '{img.file}' has no checksum in {manifest_path}")
    for role, img in profile.images.items():
        if img.file in scans:
            continue
        try:
            scans[img.file] = scanner(f"{staging_dir}/{img.file}")
        except OSError:
            raise _Refusal(f"staged image {role} {img.file} not found in {staging_dir}") from None
        if scans[img.file].sha256 != manifest[img.file]:
            raise _Refusal(f"checksum verification failed for {img.file} ({role}); nothing was written")
    parts = {p["number"]: p for p in profile.layout.params["table"]}
    sector = profile.layout.params.get("sector_size", 512)
    for role, img in profile.images.items():
        scan = scans[img.file]
        if scan.size > img.max_bytes:
            raise _Refusal(f"image {role} {img.file} is {scan.size} bytes, limit {img.max_bytes}")
        if img.must_be_populated and scan.all_zero:
            raise _Refusal(f"image {role} {img.file} is all zero ({scan.size} bytes) but must be populated")
        cap = parts[img.partition]["size"] * sector
        if scan.size > cap:
            raise _Refusal(
                f"image {role} {img.file} is {scan.size} bytes, larger than partition "
                f"{parts[img.partition]['name']} ({cap} bytes)"
            )
    return scans, len(manifest)


# -------------------------------------------------------------- rendering


def _body(profile, staging_dir: str, sfdisk_text: str, n_manifest: int) -> list:
    dev = profile.target.device
    params = profile.layout.params
    ordered = sorted(params["table"], key=lambda p: (p["start"], p["number"]))
    name_of = {p["number"]: p["name"] for p in params["table"]}
    node_of_name = {p["name"]: layout.partition_node(dev, p["number"]) for p in params["table"]}
    lines = [
        f"verifying checksums from {staging_dir}/{MANIFEST_NAME}",
        f"checksums OK ({n_manifest} file(s))",
        f"== partitions to create on {dev} ({_LAYOUT_REF}) ==",
    ]
    for p in ordered:
        node = layout.partition_node(dev, p["number"])
        lines.append(
            f"  {node:<16} {p['name']:<20} start={p['start']:<8} size={p['size']:<10} type={p['type_guid']}"
        )
    lines.append("== images to write ==")
    writes = []
    for img in profile.images.values():
        node = layout.partition_node(dev, img.partition)
        writes.append((img, node))
        lines.append(f"  {img.file} -> {node} ({name_of[img.partition]})")

    arm_params = profile.arm.params
    esp = profile.images.get("esp")
    arming = profile.arm.strategy == "uefi-bootnext" and esp is not None
    if arming:
        lines += [
            "== boot entry (BootNext only, BootOrder untouched) ==",
            f"  create : efibootmgr -C -d {dev} -p {esp.partition} -L {arm_params['label']} "
            f"-l '{arm_params['loader_path']}' -u '{arm_params.get('boot_args', '')}'",
            "  arm    : efibootmgr -n <new entry number>",
        ]
    lines += ["== dry run ==", "  would create the table from this sfdisk input:"]
    lines += ["    " + ln for ln in sfdisk_text.splitlines()]
    lines.append("DRY-RUN would run: " + " ".join(_q(a) for a in Ops.vec_sfdisk_write(dev)))
    for img, node in writes:
        vec = Ops.vec_dd_write(f"{staging_dir}/{img.file}", node)
        lines.append("DRY-RUN would run: " + " ".join(_q(a) for a in vec))
    if profile.guard.strategy == "boot-arg":
        nodes = [node_of_name[n] for n in profile.guard.params["partitions"]]
        lines.append(
            f"DRY-RUN would read back the boot image header from {' and '.join(nodes)} "
            "and refuse BootNext unless the NVMe-hiding argument is present"
        )
    if arming:
        vec = Ops.vec_efibootmgr_create(
            dev, esp.partition, arm_params["label"], arm_params["loader_path"], arm_params.get("boot_args", "")
        )
        lines.append("DRY-RUN would run: " + " ".join(_q(a) for a in vec))
        lines.append("DRY-RUN would run: efibootmgr -n NNNN")
    lines.append(DONE_LINE)
    return lines


# -------------------------------------------------------------------- run


def run_plan(
    ops: Ops,
    profile,
    profile_hash: str,
    *,
    staging_dir: str,
    run_dir: str,
    record_writer: Callable | None = None,
    board_identity: dict | None = None,
    run_id: str,
    out: Callable = print,
    scanner: Callable = images.scan,
    now: Callable = _utc_now,
    file_reader: Callable | None = None,
) -> PlanResult:
    """Verify, decide and write the plan record. Mutates nothing on the board."""
    writer = record_writer or evidence.write_record
    try:
        _check_device(profile.target.device)
        _check_sectors(ops, profile)
        _check_not_in_use(ops, profile, staging_dir)
        _, serial = _resolve_identity(ops, profile)
        if profile.target.require_empty:
            _check_empty(ops, profile)
        try:
            layout.check_fits(profile.layout.params, profile.target.sectors)
            sfdisk_text = layout.sfdisk_input(profile.layout.params, profile.target.device)
        except layout.LayoutError as exc:
            raise _Refusal(f"layout does not fit the target: {exc}") from exc
        scans, n_manifest = _check_images(ops, profile, staging_dir, scanner)
        try:
            armmod.get_guard(profile.guard.strategy).check_staged(profile, staging_dir, file_reader)
        except armmod.GuardError as exc:
            raise _Refusal(str(exc)) from exc
        try:
            record = armmod.get_arm(profile.arm.strategy).prepare(ops, profile)
        except armmod.ArmError as exc:
            raise _Refusal(f"arm pre-flight refused: {exc}") from exc

        if board_identity is None:
            board_identity = {
                "machine_id": _read_text(ops, "/etc/machine-id") or UNAVAILABLE,
                "device_serial": serial,
            }
        arm_summary = dict(record.to_dict(), strategy=profile.arm.strategy)
        plan_record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "profile_hash": profile_hash,
            "board_identity": board_identity,
            "device": profile.target.device,
            "image_hashes": {r: scans[i.file].sha256 for r, i in profile.images.items()},
            "image_sizes": {r: scans[i.file].size for r, i in profile.images.items()},
            "table_hash": hashlib.sha256(sfdisk_text.encode()).hexdigest(),
            "arm": arm_summary,
            "created_utc": now(),  # evidence only; never compared or branched on
        }
        try:
            writer(run_dir, RECORD_NAME, plan_record)
        except OSError as exc:
            raise _Refusal(f"cannot write the plan record: {exc}") from exc
    except _Refusal as exc:
        lines = [f"plan refused: {exc}"]
        for ln in lines:
            out(ln)
        return PlanResult(1, None, lines)

    ident = profile.target.identity
    header = [
        "== plan header (added by this tool) ==",
        f"profile: {profile.board} sha256={profile_hash}",
        f"device identity: {profile.target.device} kind={ident.kind} value={ident.value} "
        f"serial={board_identity.get('device_serial', UNAVAILABLE)}",
        f"board identity: machine-id={board_identity.get('machine_id', UNAVAILABLE)}",
        f"run id: {run_id}",
        f"plan record: {run_dir}/{RECORD_NAME}",
        BODY_MARKER,
    ]
    lines = header + _body(profile, staging_dir, sfdisk_text, n_manifest)
    for ln in lines:
        out(ln)
    return PlanResult(0, plan_record, lines)
