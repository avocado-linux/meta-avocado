"""Closed registry of arm, guard and layout strategies.

A board profile names a strategy per kind and supplies declarative
parameters. This module only defines which names exist and checks that the
parameters have the right shape. Behaviour is implemented elsewhere and
selected by the validated name; nothing here (or in a profile) is ever
imported, evaluated or executed by name, so a profile can only choose among
the entries below.

Parameters are plain JSON values: str, int, bool, list, dict.
Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import copy

from .layout import GPT_MIN_FIRST_LBA, GPT_SECONDARY_SECTORS, GUID_RE as _GUID_RE, PART_NAME_RE


class StrategyError(ValueError):
    """A profile named an unknown strategy or gave invalid parameters."""


def _type_name(value):
    return type(value).__name__


def _check_type(where, kind_spec, value):
    """Check value against 'str', 'int', 'bool' or ('list', item_type)."""
    if isinstance(kind_spec, tuple):
        _, item = kind_spec
        if not isinstance(value, list):
            raise StrategyError(f"{where}: expected list, got {_type_name(value)}")
        for i, v in enumerate(value):
            _check_type(f"{where}[{i}]", item, v)
        return
    if kind_spec == "str":
        ok = isinstance(value, str)
    elif kind_spec == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind_spec == "bool":
        ok = isinstance(value, bool)
    elif kind_spec == "dict":
        ok = isinstance(value, dict)
    else:  # pragma: no cover - schema typo guard
        raise StrategyError(f"{where}: internal schema type {kind_spec!r}")
    if not ok:
        raise StrategyError(f"{where}: expected {kind_spec}, got {_type_name(value)}")


def _check_fields(where, schema, params):
    """schema: {name: (type, required, default)}. Returns a filled copy."""
    if not isinstance(params, dict):
        raise StrategyError(f"{where}: parameters must be a mapping, got {_type_name(params)}")
    for key in params:
        if not isinstance(key, str):
            raise StrategyError(f"{where}: parameter name {key!r} is not a string")
        if key not in schema:
            allowed = ", ".join(sorted(schema)) or "(none)"
            raise StrategyError(f"{where}: unknown parameter '{key}' (allowed: {allowed})")
    out = {}
    for key, (typ, required, default) in schema.items():
        if key in params:
            _check_type(f"{where}: parameter '{key}'", typ, params[key])
            out[key] = copy.deepcopy(params[key])
        elif required:
            raise StrategyError(f"{where}: missing required parameter '{key}'")
        elif default is not None:
            out[key] = default
    return out


# --- layout: explicit-table -------------------------------------------------

_PART_SCHEMA = {
    "number": ("int", True, None),
    "name": ("str", True, None),
    "start": ("int", True, None),
    "size": ("int", True, None),
    "type_guid": ("str", True, None),
    "uuid": ("str", False, None),
}

_LAYOUT_SCHEMA = {
    "sector_size": ("int", False, 512),
    "first_lba": ("int", True, None),
    "last_lba": ("int", True, None),
    "device_sectors": ("int", True, None),
    "table": (("list", "dict"), True, None),
}


def _validate_explicit_table(where, params):
    out = _check_fields(where, _LAYOUT_SCHEMA, params)

    if out["sector_size"] <= 0:
        raise StrategyError(f"{where}: sector_size must be positive")
    if out["first_lba"] < GPT_MIN_FIRST_LBA:
        raise StrategyError(f"{where}: first_lba {out['first_lba']} must be at least {GPT_MIN_FIRST_LBA} (GPT header)")
    expected_last = out["device_sectors"] - GPT_SECONDARY_SECTORS
    if out["last_lba"] != expected_last:
        raise StrategyError(
            f"{where}: last_lba {out['last_lba']} must equal device_sectors - "
            f"{GPT_SECONDARY_SECTORS} (the GPT secondary table) = {expected_last}"
        )
    if out["first_lba"] >= out["last_lba"]:
        raise StrategyError(f"{where}: last_lba must be greater than first_lba")

    table = out["table"]
    if not table:
        raise StrategyError(f"{where}: table must contain at least one partition")

    parts = []
    numbers = set()
    names = set()
    uuids = set()
    for i, raw in enumerate(table):
        pw = f"{where}: table[{i}]"
        if not isinstance(raw, dict):
            raise StrategyError(f"{pw}: expected a mapping, got {_type_name(raw)}")
        part = _check_fields(pw, _PART_SCHEMA, raw)
        if part["number"] <= 0:
            raise StrategyError(f"{pw}: number must be positive")
        if part["number"] in numbers:
            raise StrategyError(f"{pw}: duplicate partition number {part['number']}")
        numbers.add(part["number"])
        if not PART_NAME_RE.fullmatch(part["name"]):
            raise StrategyError(f"{pw}: name {part['name']!r} must be 1-36 of letters, digits, _ . + -")
        if part["name"] in names:
            raise StrategyError(f"{pw}: duplicate partition name '{part['name']}'")
        names.add(part["name"])
        if part["size"] <= 0:
            raise StrategyError(f"{pw}: size must be positive")
        if not _GUID_RE.fullmatch(part["type_guid"]):
            raise StrategyError(
                f"{pw}: type_guid '{part['type_guid']}' is not an 8-4-4-4-12 hex GUID"
            )
        if "uuid" in part:
            if not _GUID_RE.fullmatch(part["uuid"]):
                raise StrategyError(
                    f"{pw}: uuid '{part['uuid']}' is not an 8-4-4-4-12 hex GUID"
                )
            folded = part["uuid"].lower()
            if folded in uuids:
                raise StrategyError(f"{pw}: duplicate uuid '{part['uuid']}'")
            uuids.add(folded)
        end = part["start"] + part["size"] - 1
        if part["start"] < out["first_lba"]:
            raise StrategyError(
                f"{pw}: start {part['start']} is before first_lba {out['first_lba']}"
            )
        if end > out["last_lba"]:
            raise StrategyError(f"{pw}: ends at {end}, after last_lba {out['last_lba']}")
        parts.append((part["start"], end, part["number"]))

    parts.sort()
    for (s1, e1, n1), (s2, _e2, n2) in zip(parts, parts[1:]):
        if s2 <= e1:
            raise StrategyError(
                f"{where}: partitions {n1} and {n2} overlap ({s1}-{e1} vs start {s2})"
            )
    return out


# --- guard: boot-arg ---------------------------------------------------------


def _validate_boot_arg(where, params):
    out = _check_fields(
        where,
        {
            "argument": ("str", True, None),
            "partitions": (_STR_LIST, True, None),
        },
        params,
    )
    arg = out["argument"]
    # An empty or multi-token argument makes the guard vacuous or unmatchable
    # (it is compared against whole command-line tokens).
    if not arg or any(c.isspace() for c in arg):
        raise StrategyError(
            f"{where}: parameter 'argument' must be exactly one non-empty kernel command-line token"
        )
    parts = out["partitions"]
    if not parts:
        raise StrategyError(f"{where}: parameter 'partitions' must name at least one partition")
    if any(not n for n in parts):
        raise StrategyError(f"{where}: parameter 'partitions' must not contain an empty name")
    if len(set(parts)) != len(parts):
        raise StrategyError(f"{where}: parameter 'partitions' must not repeat a name")
    return out


# --- arm: uefi-bootnext -----------------------------------------------------


def _validate_bootnext(where, params):
    """``entry_label`` is the firmware's own description of the storage entry to arm."""
    out = _check_fields(where, {"entry_label": ("str", True, None)}, params)
    if not out["entry_label"].strip():
        raise StrategyError(f"{where}: parameter 'entry_label' must not be empty")
    return out


# --- registry ---------------------------------------------------------------

_STR_LIST = ("list", "str")

# (kind, name) -> validator(where, params) -> params
_REGISTRY = {
    ("arm", "uefi-bootnext"): lambda w, p: _validate_bootnext(w, p),
    ("arm", "none"): lambda w, p: _check_fields(w, {}, p),
    ("guard", "boot-arg"): lambda w, p: _validate_boot_arg(w, p),
    ("guard", "none"): lambda w, p: _check_fields(w, {}, p),
    ("layout", "explicit-table"): _validate_explicit_table,
}

KINDS = ("arm", "guard", "layout")


def names(kind):
    """Sorted strategy names registered for kind."""
    if kind not in KINDS:
        raise StrategyError(f"unknown strategy kind '{kind}' (allowed: {', '.join(KINDS)})")
    return sorted(n for (k, n) in _REGISTRY if k == kind)


def validate(kind, name, params):
    """Validate a profile's strategy choice; return a normalized parameter copy.

    The name is only ever used as a dictionary key, never imported or run.
    """
    allowed = names(kind)
    entry = _REGISTRY.get((kind, name)) if isinstance(name, str) else None
    if entry is None:
        raise StrategyError(
            f"unknown {kind} strategy '{name}' (allowed: {', '.join(allowed)})"
        )
    return entry(f"{kind} strategy '{name}'", params)
