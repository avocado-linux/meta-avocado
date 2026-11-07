"""Carrier-BSP overlay (oracle lines 160-247)."""

import os
import re
from typing import Callable

from . import EngineError
from .files import merge_tree, read_text_preserving, write_text_replacing_link

_FV = "CARRIER_FV_"
_ENV = "CARRIER_ENV_"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_UNSAFE = '"$`\\\n'


def _strip_quotes(val: str, quotes: tuple[str, ...] = ('"', "'")) -> str:
    """Strip a leading and trailing double quote, then single quote, as the oracle does."""
    for quote in quotes:
        if val.startswith(quote):
            val = val[1:]
        if val.endswith(quote):
            val = val[:-1]
    return val


def _require_shell_safe(key: str, name: str, val: str, target: str) -> None:
    """Deviation carrier-value-shell-safe: both targets are sourced by bash as root.

    The value lands between double quotes, where a quote, `$`, a backtick or a
    backslash lets it run commands or end the string early.
    """
    if not _NAME.fullmatch(name):
        raise EngineError(f"carrier key {key} is not a shell variable name; refusing to write it into {target}")
    bad = next((c for c in val if c in _UNSAFE), None)
    if bad is not None:
        raise EngineError(
            f"carrier value of {key} contains {bad!r}, which the shell would act on; "
            f"refusing to write it into {target}"
        )


def _rewrite(path: str, name: str, val: str) -> bool:
    """Replace every `<name>=` line with `<name>="<val>"`; False when nothing matches.

    Plain string operations only: the oracle's sed template made `&` and
    backslash sequences in a value special, which is the listed deviation.
    """
    if not os.path.isfile(path):
        return False
    lines = read_text_preserving(path).split("\n")
    prefix = name + "="
    hit = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f'{name}="{val}"'
            hit = True
    if hit:
        write_text_replacing_link(path, "\n".join(lines), encoding="utf-8", errors="surrogateescape", newline="")
    return hit


def apply_carrier(
    data_dir: str,
    carrier_name: str,
    work_dir: str,
    log: Callable[[str], None] = print,
) -> None:
    source = f"{data_dir}/{carrier_name}"
    if not os.path.isdir(source):
        log(f"Carrier-BSP source not found: {source} (skipping overlay)")
        return
    count = sum(
        1
        for entry in os.scandir(source)
        if entry.is_file(follow_symlinks=False) and entry.name != ".placeholder"
    )
    if count == 0:
        log("Carrier-BSP slot empty (no overrides; using MACHINE-baked defaults)")
        return
    log(f"Carrier-BSP overlay: {source} ({count} file(s))")
    merge_tree(source, work_dir)

    carrier_env = os.path.join(work_dir, "carrier.env")
    if not os.path.isfile(carrier_env):
        return
    with open(carrier_env, encoding="utf-8", errors="surrogateescape") as fh:
        env_lines = fh.read().split("\n")

    for line in env_lines:
        if line.startswith("CARRIER_LABEL="):
            label = _strip_quotes(line[len("CARRIER_LABEL=") :], ('"',))
            if label:
                log(f"  Carrier: {label}")
            break

    for line in env_lines:
        if line.startswith(_FV):
            target = "flashvars"
        elif line.startswith(_ENV):
            target = ".env.initrd-flash"
        else:
            continue
        key, sep, rest = line.partition("=")
        val = _strip_quotes(rest if sep else line)
        name = key[len(_FV if target == "flashvars" else _ENV) :]
        _require_shell_safe(key, name, val, target)
        if _rewrite(os.path.join(work_dir, target), name, val):
            log(f"  {target}: {name}={val}")
        else:
            log(f"  WARNING: {key} target not found in {target}; skipped")
