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

Usage:
    python3 compare-derivations.py BASE_REF [--provider LAYER]

BASE_REF is required. Exits non-zero when any row is a lockout, so it can gate
a re-pin.
"""

import argparse
import binascii
import os
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

# One table per provider: the values worth comparing. A real value, an absent
# one, and every degenerate form the provider's own refusal logic mentions -
# those are where a derivation change hides, because a value that was accepted
# for the wrong reason before is the one that now resolves differently.
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
    """Rewrite PATHS into a fresh fixture, run with no argument, return a key."""
    root = tempfile.mkdtemp(prefix="var-key-compare-")
    body = text
    for path in paths:
        target = os.path.join(root, path.lstrip("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if values.get(path) is not None:
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(values[path])
        body = body.replace(path, target)
    script = os.path.join(root, "provider.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(body)
    try:
        result = subprocess.run(["sh", script], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    if result.returncode != 0:
        return "REFUSE"
    if len(result.stdout) != 64:
        return "WRONG-LENGTH(%d)" % len(result.stdout)
    return binascii.hexlify(result.stdout).decode()[:16]


def main():
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
        paths, rows = TABLES[layer]
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
                  % (repr(first), repr(second), before, after, verdict))
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
