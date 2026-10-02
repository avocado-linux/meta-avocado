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
import stat
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
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    _fsync_dir(path.parent)


def _bad_name(name: Any) -> bool:
    """True for anything but a bare file name: no separator, no NUL, not empty, not a dot entry."""
    return (
        not isinstance(name, str)
        or name in ("", ".", "..")
        or "/" in name
        or "\x00" in name
        or os.path.isabs(name)
    )


def write_record(run_dir, name: str, data: bytes | dict | list) -> str:
    """Atomically write a record file; return its sha256."""
    if _bad_name(name):
        raise ValueError(f"bad record name: {name!r}")
    payload = _encode(data)
    _atomic_write(Path(run_dir) / name, payload)
    return _sha256(payload)


def _parse_utc(text: str) -> _dt.datetime:
    """Parse an ISO timestamp; one without a zone is read as UTC."""
    parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _clock_text(value: Any) -> str:
    """The clock as recorded: a non-empty string, or "unavailable". Never a guess at the time."""
    return value if isinstance(value, str) and value else "unavailable"


def _skew_or_none(host_utc: Any, board_utc: Any) -> float | None:
    """Clocks are evidence only: a malformed or missing one yields no skew, never a failure."""
    try:
        return clock_skew_seconds(host_utc, board_utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


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
                "host_utc": _clock_text(self.host_utc),
                "board_utc": _clock_text(self.board_utc),
                "skew_seconds": _skew_or_none(self.host_utc, self.board_utc),
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


_STR_FIELDS = ("host_tool_version", "runner_version", "profile_hash")


def _manifest_problems(manifest: Any) -> list[str]:
    """Type and presence problems in the manifest's own fields, before any artifact is touched."""
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    out: list[str] = []
    for k in _STR_FIELDS:
        v = manifest.get(k)
        if not isinstance(v, str) or not v:
            out.append(f"manifest field {k} is missing or not a non-empty string")
    hashes = manifest.get("image_hashes")
    if not isinstance(hashes, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in hashes.items()):
        out.append("manifest field image_hashes is missing or not a mapping of role to hash")
    if not isinstance(manifest.get("board_identity"), dict):
        out.append("manifest field board_identity is missing or not an object")
    if not isinstance(manifest.get("transition_log"), list):
        out.append("manifest field transition_log is missing or not a list")
    clocks = manifest.get("clocks")
    if not isinstance(clocks, dict):
        out.append("manifest field clocks is missing or not an object")
    else:
        for k in ("host_utc", "board_utc"):
            if not isinstance(clocks.get(k), str) or not clocks[k]:
                out.append(f"manifest clocks.{k} is missing or not a non-empty string")
        skew = clocks.get("skew_seconds")
        if skew is not None and (isinstance(skew, bool) or not isinstance(skew, (int, float))):
            out.append("manifest clocks.skew_seconds is not a number or null")
    if manifest.get("run_status") not in STATUSES:
        out.append(f"manifest run_status {manifest.get('run_status')!r} is not one of {STATUSES}")
    return out


def verify_record_set(run_dir) -> VerifyResult:
    run_dir = Path(run_dir)
    problems: list[str] = []
    try:
        manifest = json.loads((run_dir / MANIFEST).read_bytes())
    except (OSError, ValueError) as exc:
        return VerifyResult(False, [f"manifest unreadable: {exc}"])
    problems.extend(_manifest_problems(manifest))
    if not isinstance(manifest, dict):
        return VerifyResult(False, problems)
    arts = manifest.get("artifacts")
    if not isinstance(arts, list) or not all(isinstance(a, dict) for a in arts):
        return VerifyResult(False, problems + ["manifest field artifacts is missing or not a list of objects"])
    listed: dict[str, dict] = {}
    for a in arts:
        name = a.get("name")
        if _bad_name(name):
            problems.append(f"bad artifact name: {name!r}")
        elif name in listed:
            problems.append(f"duplicate artifact: {name}")
        else:
            listed[name] = a
    for name, a in listed.items():
        path = run_dir / name
        try:
            st = os.lstat(str(path))
        except FileNotFoundError:
            problems.append(f"missing: {name}")
            continue
        except OSError as exc:
            problems.append(f"unreadable: {name}: {exc}")
            continue
        if not stat.S_ISREG(st.st_mode):
            problems.append(f"not a regular file: {name}")
            continue
        if st.st_size != a.get("size"):
            problems.append(f"size mismatch: {name}")
        try:
            digest = _file_sha256(path)
        except OSError as exc:
            problems.append(f"unreadable: {name}: {exc}")
            continue
        if digest != a.get("sha256"):
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
    if not isinstance(plan_record, dict) or not isinstance(current, dict):
        return False
    # Two records that both lack a key, or both carry it empty, are equal by dict.get and prove nothing.
    if not all(plan_record.get(k) and current.get(k) for k in keys):
        return False
    return all(plan_record[k] == current[k] for k in keys)
