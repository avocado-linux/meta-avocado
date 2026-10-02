"""Closed, versioned board profile (schema version 1).

A profile is a JSON document describing one board's flash target. Every
object is closed: an unknown key anywhere is an error naming its dotted
path. Numbers must be plain integers (no floats, NaN, Infinity, or bools
standing in for ints), and duplicate JSON keys are rejected at any depth.

``load_profile_bytes`` is the single entry point and takes the exact bytes,
so the host and the on-board runner validate (and ``profile_hash``) the same
bytes. Strategy names and parameters are checked against the closed registry
in ``strategies``; nothing in a profile is ever imported or executed.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Tuple

from . import strategies

SCHEMA_VERSION = 1
IDENTITY_KINDS = ("by-path", "serial", "sysfs-name")
_BOARD_RE = re.compile(r"[a-z0-9][a-z0-9-]*")  # used with fullmatch: no leading dash, no trailing newline
_FORBIDDEN_ROOTS = ("/dev", "/sys", "/proc")
_SYSFS_ATTR_RE = re.compile(r"[A-Za-z0-9_]+")


class ProfileError(ValueError):
    """A profile failed validation; ``path`` is the dotted location."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class Identity:
    kind: str
    value: str
    sysfs_attr: str | None


@dataclass(frozen=True)
class Target:
    device: str
    sector_size: int
    sectors: int
    require_empty: bool
    identity: Identity


@dataclass(frozen=True)
class Strategy:
    strategy: str
    # Normalized parameters from the registry. Treat as read-only.
    params: Any


@dataclass(frozen=True)
class Image:
    role: str
    partition: int
    max_bytes: int
    must_be_populated: bool
    file: str


@dataclass(frozen=True)
class Staging:
    dir: str
    min_free_kib: int


@dataclass(frozen=True)
class Profile:
    schema_version: int
    board: str
    description: str | None
    target: Target
    layout: Strategy
    images: Any  # mapping role -> Image (read-only view)
    checks: Tuple[str, ...]
    arm: Strategy
    guard: Strategy
    staging: Staging
    state_dir: str


def profile_hash(data: bytes) -> str:
    """sha256 hex of the exact profile bytes."""
    return hashlib.sha256(data).hexdigest()


# --- parsing ----------------------------------------------------------------


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProfileError("$", f"duplicate key '{key}'")
        out[key] = value
    return out


def _bad_number(text):
    raise ProfileError("$", f"non-canonical number {text!r}: only integers are allowed")


def _parse(data: bytes):
    if not isinstance(data, (bytes, bytearray)):
        raise ProfileError("$", "profile must be given as bytes")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileError("$", f"not valid UTF-8: {exc}") from None
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_bad_number,
            parse_constant=_bad_number,
        )
    except ProfileError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ProfileError("$", f"invalid JSON: {exc}") from None


# --- field checkers ---------------------------------------------------------


def _join(path, key):
    return f"{path}.{key}" if path else key


def _obj(path, value, required, optional=()):
    if not isinstance(value, dict):
        raise ProfileError(path or "$", f"expected object, got {type(value).__name__}")
    for key in value:
        if key not in required and key not in optional:
            raise ProfileError(_join(path, key), "unknown field")
    for key in required:
        if key not in value:
            raise ProfileError(_join(path, key), "missing required field")
    return value


def _str(path, value, nonempty=True):
    if not isinstance(value, str):
        raise ProfileError(path, f"expected string, got {type(value).__name__}")
    if nonempty and not value:
        raise ProfileError(path, "must not be empty")
    return value


def _int(path, value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileError(
            path, f"non-canonical number: expected integer, got {type(value).__name__}"
        )
    if minimum is not None and value < minimum:
        raise ProfileError(path, f"must be >= {minimum}")
    return value


def _bool(path, value):
    if not isinstance(value, bool):
        raise ProfileError(path, f"expected boolean, got {type(value).__name__}")
    return value


def _abs_path(path, value):
    _str(path, value)
    if not value.startswith("/"):
        raise ProfileError(path, "must be an absolute path")
    parts = value.split("/")
    if ".." in parts:
        raise ProfileError(path, "must not contain '..'")
    if not [c for c in parts if c not in ("", ".")]:
        raise ProfileError(path, "must not be the filesystem root")
    # posixpath keeps a leading "//" and "/." forms would slip past a plain prefix test.
    norm = "/" + posixpath.normpath(value).lstrip("/")
    for root in _FORBIDDEN_ROOTS:
        if norm == root or norm.startswith(root + "/"):
            raise ProfileError(path, f"must not be under {root}")
    return value


def _strategy(path, kind, value):
    _obj(path, value, ("strategy", "params"))
    name = _str(_join(path, "strategy"), value["strategy"])
    params = value["params"]
    if not isinstance(params, dict):
        raise ProfileError(_join(path, "params"), "expected object")
    try:
        norm = strategies.validate(kind, name, params)
    except strategies.StrategyError as exc:
        raise ProfileError(path, str(exc)) from None
    return Strategy(name, norm)


class _ReadOnlyMap(dict):
    def _ro(self, *a, **k):
        raise TypeError("profile mappings are read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _ro


def _target(value):
    path = "target"
    _obj(path, value, ("device", "sector_size", "sectors", "require_empty", "identity"))
    ident = _obj(
        "target.identity", value["identity"], ("kind", "value"), ("sysfs_attr",)
    )
    kind = _str("target.identity.kind", ident["kind"])
    if kind not in IDENTITY_KINDS:
        raise ProfileError(
            "target.identity.kind",
            f"unknown kind '{kind}' (allowed: {', '.join(IDENTITY_KINDS)})",
        )
    attr = None
    if "sysfs_attr" in ident:
        attr = _str("target.identity.sysfs_attr", ident["sysfs_attr"])
        if not _SYSFS_ATTR_RE.fullmatch(attr):
            raise ProfileError(
                "target.identity.sysfs_attr", "must be a bare attribute name (letters, digits, underscore)"
            )
    identity = Identity(kind, _str("target.identity.value", ident["value"]), attr)
    return Target(
        device=_str("target.device", value["device"]),
        sector_size=_int("target.sector_size", value["sector_size"], 1),
        sectors=_int("target.sectors", value["sectors"], 1),
        require_empty=_bool("target.require_empty", value["require_empty"]),
        identity=identity,
    )


def _images(value):
    if not isinstance(value, dict):
        raise ProfileError("images", f"expected object, got {type(value).__name__}")
    out = {}
    for role, raw in value.items():
        path = f"images.{role}"
        if not role:
            raise ProfileError("images", "role name must not be empty")
        _obj(path, raw, ("partition", "max_bytes", "must_be_populated", "file"))
        fname = _str(f"{path}.file", raw["file"])
        if "/" in fname or "\\" in fname or fname.startswith("-") or fname in (".", ".."):
            raise ProfileError(
                f"{path}.file", "must be a plain file name (no separators, no leading dash)"
            )
        out[role] = Image(
            role=role,
            partition=_int(f"{path}.partition", raw["partition"], 1),
            max_bytes=_int(f"{path}.max_bytes", raw["max_bytes"], 1),
            must_be_populated=_bool(f"{path}.must_be_populated", raw["must_be_populated"]),
            file=fname,
        )
    return _ReadOnlyMap(out)


def _checks(value):
    if not isinstance(value, list):
        raise ProfileError("checks", f"expected list, got {type(value).__name__}")
    seen = set()
    for i, name in enumerate(value):
        _str(f"checks[{i}]", name)
        if name in seen:
            raise ProfileError("checks", f"duplicate assertion name '{name}'")
        seen.add(name)
    return tuple(value)


# --- entry point ------------------------------------------------------------


def load_profile_bytes(data: bytes) -> Profile:
    doc = _parse(data)
    top = _obj(
        "",
        doc,
        (
            "schema_version", "board", "target", "layout", "images", "checks",
            "arm", "guard", "staging", "state_dir",
        ),
        ("description",),
    )
    version = top["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != SCHEMA_VERSION:
        raise ProfileError(
            "schema_version", f"unsupported version {version!r} (supported: {SCHEMA_VERSION})"
        )
    board = _str("board", top["board"])
    if not _BOARD_RE.fullmatch(board):
        raise ProfileError("board", "must be kebab-case [a-z0-9-]+ without a leading dash")
    description = None
    if "description" in top:
        description = _str("description", top["description"], nonempty=False)

    target = _target(top["target"])
    layout = _strategy("layout", "layout", top["layout"])
    images = _images(top["images"])
    checks = _checks(top["checks"])
    arm = _strategy("arm", "arm", top["arm"])
    guard = _strategy("guard", "guard", top["guard"])
    stg = _obj("staging", top["staging"], ("dir", "min_free_kib"))
    staging = Staging(
        dir=_abs_path("staging.dir", stg["dir"]),
        min_free_kib=_int("staging.min_free_kib", stg["min_free_kib"], 1),
    )
    state_dir = _abs_path("state_dir", top["state_dir"])

    # Cross-checks.
    if layout.strategy == "explicit-table":
        lp = layout.params
        if target.sectors != lp["device_sectors"]:
            raise ProfileError(
                "target.sectors",
                f"{target.sectors} must equal layout device_sectors {lp['device_sectors']}",
            )
        if target.sector_size != lp["sector_size"]:
            raise ProfileError(
                "target.sector_size",
                f"{target.sector_size} must equal layout sector_size {lp['sector_size']}",
            )
        numbers = {p["number"] for p in lp["table"]}
        names = {p["name"] for p in lp["table"]}
        owner = {}
        for role, img in images.items():
            if img.partition in owner:
                raise ProfileError(
                    f"images.{role}.partition",
                    f"roles {owner[img.partition]} and {role} both target partition {img.partition}",
                )
            owner[img.partition] = role
            if img.partition not in numbers:
                raise ProfileError(
                    f"images.{role}.partition",
                    f"partition {img.partition} is not in the layout table",
                )
        if guard.strategy == "boot-arg":
            for name in guard.params["partitions"]:
                if name not in names:
                    raise ProfileError(
                        "guard.params.partitions",
                        f"guard partition '{name}' is not in the layout table",
                    )

    return Profile(
        schema_version=SCHEMA_VERSION,
        board=board,
        description=description,
        target=target,
        layout=layout,
        images=images,
        checks=checks,
        arm=arm,
        guard=guard,
        staging=staging,
        state_dir=state_dir,
    )
