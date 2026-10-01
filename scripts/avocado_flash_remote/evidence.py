"""Evidence records for a flash run (task 3.4).

Each run owns a unique directory. Every record file is written atomically
and listed, with size and sha256, in MANIFEST.json (written last). Clocks
are recorded as evidence only; authorise() takes no time input.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST = "MANIFEST.json"
STATUSES = ("runner-complete", "host-verified", "not-verified", "incomplete")


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_run_dir(root) -> Path:
    """Create a unique run directory; exclusive mkdir, retry on EEXIST."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    while True:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = root / f"run-{stamp}-{secrets.token_hex(4)}"
        try:
            os.mkdir(str(path), 0o700)
        except FileExistsError:
            continue
        _fsync_dir(root)
        return path


def _encode(data: bytes | dict | list) -> bytes:
    if isinstance(data, bytes):
        return data
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def _atomic_write(path: Path, payload: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(str(tmp), str(path))
    _fsync_dir(path.parent)


def write_record(run_dir, name: str, data: bytes | dict | list) -> str:
    """Atomically write a record file; return its sha256."""
    if "/" in name or name in ("", ".", ".."):
        raise ValueError(f"bad record name: {name!r}")
    payload = _encode(data)
    _atomic_write(Path(run_dir) / name, payload)
    return _sha256(payload)


def _parse_utc(text: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def clock_skew_seconds(host_utc: str, board_utc: str) -> float:
    return (_parse_utc(board_utc) - _parse_utc(host_utc)).total_seconds()


@dataclass
class RecordSet:
    run_dir: Path
    host_tool_version: str
    runner_version: str
    profile_hash: str
    image_hashes: dict[str, str]
    board_identity: dict[str, Any]
    transition_log: list[Any]
    host_utc: str
    board_utc: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)

    def add(self, name: str, data: bytes | dict | list) -> str:
        digest = write_record(self.run_dir, name, data)
        size = (self.run_dir / name).stat().st_size
        self.artifacts = [a for a in self.artifacts if a["name"] != name]
        self.artifacts.append({"name": name, "size": size, "sha256": digest})
        return digest

    def manifest(self, run_status: str) -> dict[str, Any]:
        if run_status not in STATUSES:
            raise ValueError(f"bad run_status: {run_status!r}")
        return {
            "host_tool_version": self.host_tool_version,
            "runner_version": self.runner_version,
            "profile_hash": self.profile_hash,
            "image_hashes": dict(self.image_hashes),
            "board_identity": self.board_identity,
            "transition_log": list(self.transition_log),
            # Evidence only: nothing reads these to authorise anything.
            "clocks": {
                "host_utc": self.host_utc,
                "board_utc": self.board_utc,
                "skew_seconds": clock_skew_seconds(self.host_utc, self.board_utc),
            },
            "run_status": run_status,
            "artifacts": sorted(self.artifacts, key=lambda a: a["name"]),
        }

    def finalize(self, run_status: str) -> Path:
        """Write MANIFEST.json atomically, last."""
        write_record(self.run_dir, MANIFEST, self.manifest(run_status))
        return self.run_dir / MANIFEST


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


def verify_record_set(run_dir) -> VerifyResult:
    run_dir = Path(run_dir)
    problems: list[str] = []
    try:
        manifest = json.loads((run_dir / MANIFEST).read_bytes())
        arts = manifest["artifacts"]
        listed = {a["name"]: a for a in arts}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return VerifyResult(False, [f"manifest unreadable: {exc}"])
    for name, a in listed.items():
        path = run_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
            continue
        if path.stat().st_size != a.get("size"):
            problems.append(f"size mismatch: {name}")
        if _file_sha256(path) != a.get("sha256"):
            problems.append(f"hash mismatch: {name}")
    for p in run_dir.iterdir():
        if p.name != MANIFEST and p.name not in listed:
            problems.append(f"unlisted file: {p.name}")
    return VerifyResult(not problems, problems)


def final_status(runner_reported_phase: str, verify: VerifyResult) -> str:
    """'complete' only if the runner reported complete AND verification passed."""
    if runner_reported_phase != "complete":
        return "incomplete"
    return "complete" if verify.ok else "not-verified"


def authorise(plan_record: dict[str, Any], current: dict[str, Any]) -> bool:
    """Compare hashes and ids only. No time input: clock skew is irrelevant."""
    keys = ("image_hashes", "profile_hash", "board_identity", "run_id")
    return all(plan_record.get(k) == current.get(k) for k in keys)
