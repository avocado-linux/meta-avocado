"""Comparator for oracle-versus-engine call logs and output trees.

Call record shape consumed (one dict per stub invocation, written by the
stubs as one JSON object per line):

    tool                          str        stub name, e.g. "initrd-flash"
    argv                          list[str]  arguments after the tool name
    cwd                           str        working directory of the call
    PATH                          str        PATH seen by the call
    PYTHONWARNINGS                str        value seen by the call
    AVOCADO_KERNEL_CMDLINE_EXTRA  str        value seen by the call

Only environmental differences are normalized here: sandbox roots, the two
generated PARTUUIDs, and the cpp wrapper's temporary directory (the PATH element
before the staged `<sandbox>/.../tegraflash` directory, in every record). Each
run of consecutive lsusb calls collapses to one marker that keeps its position:
the engine and the oracle poll a different number of times (deviation
one-board-only), so only whether and where the bus was listed is compared.
The engine's recheck just before the flash is the other half of that deviation
and is removed by without_recheck, which also fails when it is absent. Nothing
else is masked.
"""

import hashlib
import os
import re
import stat
from pathlib import Path

RECORD_KEYS = ("tool", "argv", "cwd", "PATH", "PYTHONWARNINGS", "AVOCADO_KERNEL_CMDLINE_EXTRA")
WORKDIR_NAME = "tegraflash"

# Deviation one-board-only: the engine pins one board, so the number of USB
# listings is not compared, only their position.
USB_TOOL = "lsusb"
USB_MARKER = {k: None for k in RECORD_KEYS} | {"tool": USB_TOOL}
FLASH_TOOL = "initrd-flash"

_PARTUUID_RE = re.compile(r"avocado\.root_partuuid(_b)?=([0-9A-Fa-f-]+)")


def extract_partuuids(records):
    """Map each generated rootfs PARTUUID to a placeholder, from the cmdline."""
    mapping = {}
    for r in records:
        for m in _PARTUUID_RE.finditer(r.get("AVOCADO_KERNEL_CMDLINE_EXTRA") or ""):
            name = "<PARTUUID-B>" if m.group(1) else "<PARTUUID-A>"
            mapping.setdefault(m.group(2).upper(), name)
    return mapping


def _replace_all(text, mapping):
    for old, new in mapping.items():
        text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    return text


def _wrapper_dirs(path, roots):
    """The PATH element right before the staged work directory, if any.

    The work directory is `<sandbox root>/.../tegraflash`; the wrapper's
    mktemp directory is prepended just ahead of it, in every call. Only that
    one element is returned, so no other PATH element is ever masked.
    """
    found = set()
    parts = (path or "").split(":")
    for i in range(1, len(parts)):
        p = parts[i]
        if os.path.basename(p) == WORKDIR_NAME and any(p.startswith(r + "/") for r in roots):
            found.add(parts[i - 1])
    return found


def normalize_calls(records, sandbox_roots):
    """Return records with environmental differences replaced by placeholders."""
    uuids = extract_partuuids(records)
    roots = [str(r).rstrip("/") for r in sandbox_roots]
    wrapper_dirs = set()
    for r in records:
        wrapper_dirs.update(_wrapper_dirs(r.get("PATH"), roots))
    # Wrapper dir first: it may live under a sandbox root.
    subs = {d: "<WRAPPER_DIR>" for d in wrapper_dirs}
    for root in roots:
        subs[root] = "<SANDBOX>"

    def fix(value):
        if isinstance(value, list):
            return [fix(v) for v in value]
        if not isinstance(value, str):
            return value
        for old in sorted(subs, key=len, reverse=True):
            value = value.replace(old, subs[old])
        return _replace_all(value, uuids)

    out = []
    for r in records:
        if r["tool"] == USB_TOOL:
            if not out or out[-1]["tool"] != USB_TOOL:
                out.append(dict(USB_MARKER))
            continue
        out.append({k: fix(r.get(k)) for k in RECORD_KEYS})
    return out


def without_recheck(engine_calls):
    """Remove the engine's board recheck right before the flash call.

    Deviation one-board-only: the oracle never lists the bus again after the
    wait. The engine must list it directly before initrd-flash, so a missing
    recheck is reported. Returns (calls, problems).
    """
    flashes = [i for i, c in enumerate(engine_calls) if c["tool"] == FLASH_TOOL]
    if not flashes:
        return engine_calls, []
    i = flashes[0]
    if i == 0 or engine_calls[i - 1]["tool"] != USB_TOOL:
        return engine_calls, ["engine does not list the USB bus right before initrd-flash (one-board-only recheck)"]
    return engine_calls[: i - 1] + engine_calls[i:], []


def call_problems(oracle_records, engine_records, oracle_roots, engine_roots):
    """Every difference between the oracle's and the engine's call logs."""
    oracle = normalize_calls(oracle_records, oracle_roots)
    engine, problems = without_recheck(normalize_calls(engine_records, engine_roots))
    return problems + diff(oracle, engine)


def diff(left, right):
    """Human-readable differences between two normalized call logs."""
    out = []
    if len(left) != len(right):
        out.append(f"call count differs: {len(left)} vs {len(right)}")
    for i, (a, b) in enumerate(zip(left, right)):
        for key in RECORD_KEYS:
            if a.get(key) != b.get(key):
                name = a["tool"] if a["tool"] == b["tool"] else f"{a['tool']}/{b['tool']}"
                out.append(f"call {i} {name}: {key} differs: {a.get(key)!r} vs {b.get(key)!r}")
    return out


def snapshot(directory, mapping):
    """Relative path -> (type, mode, sha256) or ("symlink", target).

    File content is hashed after replacing every mapped PARTUUID, so two
    layouts that differ only in generated PARTUUIDs compare equal. Directories
    carry (type, mode, None).
    """
    base = Path(directory)
    result = {}
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            p = Path(dirpath) / name
            rel = str(p.relative_to(base))
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode):
                result[rel] = ("symlink", _replace_all(os.readlink(p), mapping))
            elif stat.S_ISDIR(st.st_mode):
                result[rel] = ("dir", stat.S_IMODE(st.st_mode), None)
            else:
                data = p.read_bytes()
                text = _replace_all(data.decode("latin-1"), mapping)
                digest = hashlib.sha256(text.encode("latin-1")).hexdigest()
                result[rel] = ("file", stat.S_IMODE(st.st_mode), digest)
    return result


def diff_snapshots(left, right):
    """Human-readable differences between two snapshots."""
    out = []
    for rel in sorted(set(left) | set(right)):
        if rel not in left:
            out.append(f"{rel}: only in right")
        elif rel not in right:
            out.append(f"{rel}: only in left")
        elif left[rel] != right[rel]:
            out.append(f"{rel}: differs: {left[rel]!r} vs {right[rel]!r}")
    return out
