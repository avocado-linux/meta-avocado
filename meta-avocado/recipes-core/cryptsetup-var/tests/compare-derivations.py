#!/usr/bin/env python3
"""Compare what each var-key provider derives at two git refs.

A provider change that alters the derived key locks a device out of its own
`/var`: the volume was formatted with the old key and the Argon2id keyslot is
the recovery path, so there is nothing behind it. The golden vectors in each
vendor suite make such a change LOUD, but they do not say which inputs moved or
whether any of them can occur on real hardware. That is this tool's job, and it
is the check to run before re-pinning a vector.

Method, and why it is not simply "run both providers":

  A provider from before the build-time check was added takes no first
  argument, so it cannot be pointed at a fixture. Both sides are therefore
  driven the same way - every declared path is rewritten into a fresh fixture
  directory and the copy is run with NO argument. That also matches how a
  device invokes it, so neither side can branch on being under test.

  Each row gets its own fixture. An earlier shell version of this comparison
  reused one directory because its counter incremented inside a command
  substitution, so each row inherited the previous row's files and reported
  two different inputs deriving one key. Read a "same key from different
  inputs" result as a bug in the harness first.

Both sides are read with `git show <ref>:<path>`, so this compares COMMITTED
refs and an uncommitted working-tree change is invisible to it. A fix made but
not yet committed shows as `same` on every row, because both sides are then the
same pre-fix file - which reads exactly like "this change is safe". Commit
first, then measure.

Usage:
    python3 compare-derivations.py BASE_REF [--provider LAYER]

BASE_REF is required. Exits non-zero when any row is a lockout, so it can gate
a re-pin.
"""

import argparse
import binascii
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAYERS = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))

REL = os.path.join("recipes-core", "cryptsetup-var", "files", "var-key.sh")

SOC = "/sys/devices/soc0/serial_number"
DT = "/sys/firmware/devicetree/base/serial-number"
UUID = "/sys/class/dmi/id/product_uuid"
SERIAL = "/sys/class/dmi/id/product_serial"

IDENTITY_MARKER = "# avocado-var-key-identity:"


def declared_paths(text):
    """The identity paths a provider declares, in declaration order.

    Read from the provider rather than from a table beside it. The hardcoded
    2-tuple this replaces was the third instance of one failure shape in this
    file: a path the provider reads but the table does not name is never
    rewritten, so BOTH refs read the host's real /sys, both refuse or both
    agree, and the row reports `same`. Reproduced before this change - adding a
    third declared path to the x86-64 provider produced 19 of 19 rows `same`
    and exit 0 over a derivation change that really did move the key.

    Per-ref, not once: a ref whose declared set differs from HEAD's is exactly
    the change most worth seeing, and reading one ref's declarations for both
    would hide it.
    """
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(IDENTITY_MARKER):
            continue
        value = stripped[len(IDENTITY_MARKER):].strip()
        if value and len(value.split()) == 1:
            found.append(value)
    return found


# One table per provider: the values worth comparing, keyed by the ROLE a path
# plays rather than by its literal path - primary is the first declared, and so
# on. A real value, an absent one, and every degenerate form the provider's own
# refusal logic mentions - those are where a derivation change hides, because a
# value that was accepted for the wrong reason before is the one that now
# resolves differently.
TABLES = {
    "meta-avocado-nxp": (
        (SOC, DT),
        [
            ("0a1b2c3d4e5f6071", "DT-UNIQUE-1"),
            ("0a1b2c3d4e5f6071", None),
            (None, "DT-UNIQUE-1"),
            ("   ", "DT-UNIQUE-1"),
            ("\t", "DT-UNIQUE-1"),
            ("   ", None),
            ("   ", "   "),
            ("0000000000000000", "DT-UNIQUE-1"),
            ("0000000000000000", None),
            ("0000000000000000", "0000-0000"),
            (None, None),
        ],
    ),
    "meta-avocado-nvidia": (
        (DT, SOC),
        [
            ("JETSON-SERIAL-1", None),
            ("JETSON-SERIAL-1", "0a1b2c3d"),
            (None, "0a1b2c3d"),
            ("   ", "0a1b2c3d"),
            ("\t", "0a1b2c3d"),
            ("   ", None),
            ("0000000000000000", "0a1b2c3d"),
            ("0000000000000000", None),
            (None, None),
        ],
    ),
    "meta-avocado-x86-64": (
        (UUID, SERIAL),
        [
            ("4C4C4544-0059-UNIQUE-BOARD01", "SN-UNIQUE-1"),
            ("Default string", "SN-UNIQUE-1"),
            ("default string", "SN-UNIQUE-1"),
            ("DEFAULT STRING", "SN-UNIQUE-1"),
            ("Default string ", "SN-UNIQUE-1"),
            ("Default  string", "SN-UNIQUE-1"),
            ("To  be  filled  by O.E.M.", "SN-UNIQUE-1"),
            ("To be filled by O.E.M.", "SN-UNIQUE-1"),
            ("Unknown", "SN-UNIQUE-1"),
            ("null", "SN-UNIQUE-1"),
            ("123456789", "SN-UNIQUE-1"),
            ("Chassis Serial Number", "SN-UNIQUE-1"),
            ("Product Name", "SN-UNIQUE-1"),
            ("0", "SN-UNIQUE-1"),
            ("00000000-0000-0000-0000-000000000000", "SN-UNIQUE-1"),
            (None, "SN-UNIQUE-1"),
            ("Default string", "Default string"),
            ("unknown", "unknown"),
            (None, None),
        ],
    ),
}


def at_ref(ref, path):
    """The file's contents at REF, or None when it did not exist there."""
    result = subprocess.run(
        ["git", "-C", LAYERS, "show", "%s:%s" % (ref, path)],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else None


def derive(text, paths, values):
    """Rewrite PATHS into a fresh fixture, run with no argument, return a key.

    ONE pass over the original text, not a str.replace per path. Sequential
    replacement re-scans text it has already rewritten, so a declared path that
    is a prefix of another gets the fixture root spliced in twice and the copy
    reads a path that does not exist. Both refs then hit the same broken
    rewrite, both REFUSE, `before == after`, and the row reports `same` - a
    false clean in the tool gating a golden-vector re-pin.
    
    Ordering longest-first does NOT fix it, because the rewritten target still
    contains the shorter path as a substring; only a single alternation pass
    does. The recipe's no_argv_copy carries the same fix for the same reason.
    Latent while the path list came from a hardcoded 2-tuple, and reachable the
    moment that list started coming from the provider's own declarations.
    """
    root = tempfile.mkdtemp(prefix="var-key-compare-")
    for path in paths:
        target = os.path.join(root, path.lstrip("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if values.get(path) is not None:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(values[path])
    order = sorted(paths, key=len, reverse=True)
    target_of = {q: os.path.join(root, q.lstrip("/")) for q in paths}
    body = re.compile("|".join(re.escape(q) for q in order)).sub(
        lambda m: target_of[m.group(0)], text
    )
    script = os.path.join(root, "provider.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(body)
    try:
        result = subprocess.run(["sh", script], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    finally:
        # Every other suite here cleans up after itself. This one left roughly
        # two fixture directories per row behind - about 114 on a full run -
        # and TMPDIR is tmpfs on the machines it runs on.
        shutil.rmtree(root, ignore_errors=True)
    if result.returncode != 0:
        return "REFUSE"
    if len(result.stdout) != 64:
        return "WRONG-LENGTH(%d)" % len(result.stdout)
    # The WHOLE key. Returning a truncated prefix made this tool report `same`
    # for any change that preserved the first eight bytes and altered the other
    # 56 - a false clean in the one tool whose job is to catch a changed
    # derivation. Truncation is a display concern and happens at the print.
    return binascii.hexlify(result.stdout).decode()


def shown(value):
    """A key abbreviated for the table; a status word left intact."""
    return value[:16] if len(value) == 128 else value


def require_argon2id():
    """Refuse to run without the KDF, rather than reporting every row `same`.

    derive() collapses any non-zero exit to "REFUSE", and main() checks
    `before == after` first - so on a host with no openssl, or one older than
    3.2, BOTH refs refuse, every row reads `same`, and the tool exits 0. That
    is a false clean in the one tool whose stated job is to catch a changed
    derivation before a golden vector is re-pinned.

    The three bash suites and the tier harness all probe for this and print
    SKIP. This tool must not SKIP: a skipped lockout check reads like a passed
    one to whoever is deciding whether to re-pin.
    """
    if not shutil.which("openssl"):
        sys.exit("FAIL - openssl not on PATH; every row would report `same`")
    probe = subprocess.run(
        [
            "openssl", "kdf", "-binary", "-keylen", "8",
            "-kdfopt", "pass:x", "-kdfopt", "salt:0123456789abcdef",
            "-kdfopt", "iter:3", "-kdfopt", "memcost:65536",
            "-kdfopt", "lanes:1", "ARGON2ID",
        ],
        capture_output=True,
    )
    if probe.returncode != 0:
        sys.exit(
            "FAIL - this openssl has no ARGON2ID (needs 3.2+); every row "
            "would report `same`"
        )


def main():
    require_argon2id()
    parser = argparse.ArgumentParser(
        description="Compare what each var-key provider derives at two refs.",
        epilog="BASE_REF is required and deliberately has no default. There is "
               "nothing safe to guess: a merge-base against the remote's "
               "default branch does not resolve on a branch with an unrelated "
               "history, and a base ref picked wrongly produces a full table "
               "of meaningless rows rather than an error. Find the right one "
               "with `git log --oneline -- "
               "'*/recipes-core/cryptsetup-var/files/var-key.sh'` and take the "
               "commit before the change under review.",
    )
    parser.add_argument("base", metavar="BASE_REF")
    parser.add_argument("--provider", action="append", dest="providers")
    args = parser.parse_args()

    base = args.base
    resolved = subprocess.run(
        ["git", "-C", LAYERS, "rev-parse", "--verify", "%s^{commit}" % base],
        capture_output=True, text=True,
    )
    if resolved.returncode != 0:
        sys.exit("FAIL - %r does not resolve to a commit" % base)

    wanted = args.providers or sorted(TABLES)
    changed_total = 0

    for layer in wanted:
        if layer not in TABLES:
            sys.exit("FAIL - no table for %s" % layer)
        _table_paths, rows = TABLES[layer]
        path = os.path.join(layer, REL)
        old = at_ref(base, path)
        new = at_ref("HEAD", path)
        print("=== %s (%s -> HEAD) ===" % (layer, base[:8]))
        if new is None:
            print("  provider absent at HEAD - skipped\n")
            continue
        if old is None:
            print("  provider did not exist at the base ref - nothing to "
                  "compare, so no device can hold an older key\n")
            continue

        # Each ref's OWN declarations, so a path added or removed between the
        # two is visible rather than silently unrewritten on one side.
        old_paths = declared_paths(old)
        new_paths = declared_paths(new)
        if not new_paths:
            sys.exit(
                "FAIL - %s declares no identity path at HEAD; every read would "
                "resolve against this host and every row would report `same`"
                % layer
            )
        if not old_paths:
            # The base predates the identity-declaration contract, which this
            # change introduced - so "declares nothing" is not "reads nothing".
            # Use HEAD's paths for both sides, but only after confirming the
            # base provider contains each one LITERALLY: that is the same
            # property tier 2's require_literal_paths enforces, and it is what
            # makes the rewrite reach the base provider's reads too. Without
            # the check this branch would reintroduce the exact false `same`
            # the declaration reader exists to remove.
            missing = [q for q in new_paths if q not in old]
            if missing:
                sys.exit(
                    "FAIL - %s at the base ref declares no identity path and "
                    "does not contain %s literally, so the rewrite cannot "
                    "reach its reads and every row would report `same`."
                    % (layer, ", ".join(missing))
                )
            print("  base predates the identity declarations; it contains "
                  "each of HEAD's paths literally, so both sides are "
                  "rewritten on HEAD's set")
            old_paths = new_paths

        if old_paths != new_paths:
            print("  DECLARED PATHS CHANGED - the two refs do not read the "
                  "same sources, so a row comparing them compares two "
                  "different questions:")
            print("    base: %s" % (", ".join(old_paths) or "<none>"))
            print("    head: %s" % ", ".join(new_paths))
            print("  Re-run per ref, or migrate the key, before re-pinning.\n")
            changed_total += 1
            continue
        if len(new_paths) != len(_table_paths):
            sys.exit(
                "FAIL - %s declares %d identity path(s) (%s) but its value "
                "table supplies %d per row. Update TABLES so every declared "
                "path is populated; an unpopulated one is read from this host "
                "and reports `same`."
                % (layer, len(new_paths), ", ".join(new_paths),
                   len(_table_paths))
            )
        paths = new_paths

        print("  %-38s %-16s %-18s %-18s %s"
              % (paths[0].rsplit("/", 1)[-1], paths[1].rsplit("/", 1)[-1],
                 "BASE", "HEAD", "verdict"))
        changed = 0
        for first, second in rows:
            values = {paths[0]: first, paths[1]: second}
            before = derive(old, list(paths), values)
            after = derive(new, list(paths), values)
            if before == after:
                verdict = "same"
            elif before == "REFUSE":
                verdict = "was refused, now derives"
            elif after == "REFUSE":
                verdict = "LOCKOUT: was a key, now refused"
                changed += 1
            else:
                verdict = "LOCKOUT: key changed"
                changed += 1
            print("  %-38s %-16s %-18s %-18s %s"
                  % (repr(first), repr(second),
                     shown(before), shown(after), verdict))
        print("  lockout rows: %d of %d\n" % (changed, len(rows)))
        changed_total += changed

    if changed_total:
        print("%d row(s) would lock a device out of its own /var." % changed_total)
        print("A row only matters if a device can BOTH produce that input and "
              "already hold a volume formatted under the base ref. Check the "
              "machine's AVOCADO_SECURITY_CAPABILITIES for encrypted-var "
              "before concluding either way.")
    return 1 if changed_total else 0


if __name__ == "__main__":
    sys.exit(main())
