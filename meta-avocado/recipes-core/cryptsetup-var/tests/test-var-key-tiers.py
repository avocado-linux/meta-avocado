#!/usr/bin/env python3
"""Regression test for the two deliverability tiers in cryptsetup-var.bb.

The tiers are BitBake Python - a `python __anonymous()` parse-time check and a
`do_install[postfuncs]` execution check - so neither runs outside a build. Their
rejection branches were each verified once, by hand-mutating a provider and
watching the refusal, and a regression in any of them would have merged with
nothing to say so.

This runs them for real, against synthetic providers built per case.

It does NOT copy the tier bodies. It slices them out of cryptsetup-var.bb at run
time and execs them with `bb` and `d` stubbed. A copy would be edited alongside
the recipe and stay green, which is exactly the failure the file exists to
catch; the slicing anchors below fail loudly if the recipe's shape changes.

Two cases are marked GAP: they record a hole that is open today and name the
change that closes it. A gap behaving as recorded is not a failure - it is the
regression test for the fix, and its expectation flips to `fatal` when that fix
lands.

Run: python3 test-var-key-tiers.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE = os.path.normpath(os.path.join(HERE, "..", "cryptsetup-var.bb"))

TIER1 = "__anonymous"
TIER2 = "avocado_var_key_check_deliverability"


# --------------------------------------------------------------------------
# Slicing the recipe
# --------------------------------------------------------------------------
# Each helper below raises rather than returning a default. A slice that
# silently came back empty would exec cleanly, every case would read the
# absence of a refusal as a pass, and the suite would be green over a tier it
# never loaded.


def read_recipe():
    try:
        with open(RECIPE, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise SystemExit("FAIL - cannot read %s: %s" % (RECIPE, exc))


def slice_helpers(source):
    """The module-level `def avocado_var_key_*` block, as plain Python."""
    lines = source.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("def avocado_var_key_"):
            start = index
            break
    if start is None:
        raise SystemExit(
            "FAIL - no top-level `def avocado_var_key_*` in %s. The helpers "
            "moved; update this anchor." % RECIPE
        )
    for index in range(start, len(lines)):
        if lines[index].startswith("python "):
            return "\n".join(lines[start:index]) + "\n"
    raise SystemExit(
        "FAIL - no `python ...() {` block after the helpers in %s." % RECIPE
    )


def slice_task(source, name):
    """A `python NAME() { ... }` block, rewritten as a real `def NAME():`."""
    lines = source.splitlines()
    opener = "python %s() {" % name
    start = None
    for index, line in enumerate(lines):
        if line.startswith(opener):
            start = index
            break
    if start is None:
        raise SystemExit("FAIL - no `%s` in %s" % (opener, RECIPE))
    body = None
    for index in range(start + 1, len(lines)):
        if lines[index] == "}":
            body = lines[start + 1:index]
            break
    if body is None:
        raise SystemExit(
            "FAIL - `%s` is not closed by a `}` at column 0 in %s"
            % (opener, RECIPE)
        )
    if not any(line.strip() for line in body):
        raise SystemExit("FAIL - `%s` sliced to an empty body" % opener)
    return "def %s():\n" % name + "\n".join(body) + "\n"


def marker_value(source, name):
    """A `NAME = "value"` assignment at column 0, so markers are not hardcoded."""
    for line in source.splitlines():
        if line.startswith(name + " = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("FAIL - no `%s = ...` in %s" % (name, RECIPE))


# --------------------------------------------------------------------------
# The bb / d stubs
# --------------------------------------------------------------------------


class Fatal(Exception):
    """What `bb.fatal` raises. Real bb.fatal raises BBHandledException."""


class BBUtils:
    @staticmethod
    def contains(variable, checkvalues, truevalue, falsevalue, d):
        value = d.getVar(variable)
        if value is None:
            return falsevalue
        have = set(value.split())
        if isinstance(checkvalues, str):
            want = set(checkvalues.split())
        else:
            want = set(checkvalues)
        return truevalue if want and want.issubset(have) else falsevalue

    @staticmethod
    def which(path, item):
        for entry in (path or "").split(":"):
            if not entry:
                continue
            candidate = os.path.join(entry, item)
            if os.path.exists(candidate):
                return candidate
        return ""

    @staticmethod
    def mkdirhier(path):
        os.makedirs(path, exist_ok=True)


class BB:
    def __init__(self):
        self.utils = BBUtils()
        self.warnings = []

    def fatal(self, message):
        raise Fatal(message)

    def warn(self, message):
        self.warnings.append(message)

    def note(self, message):
        pass

    def plain(self, message):
        pass

    def debug(self, level, message=None):
        pass


class Datastore:
    def __init__(self, values):
        self._values = dict(values)

    def getVar(self, name, expand=True):
        return self._values.get(name)

    def setVar(self, name, value):
        self._values[name] = value


# --------------------------------------------------------------------------
# Synthetic providers
# --------------------------------------------------------------------------
# Each is a whole provider rather than a patch over a real one. A case built by
# sed-ing a shipped provider would break when that provider is edited, and the
# breakage would read as a tier regression.

PRIMARY = "/sys/fixture/primary"
SECONDARY = "/sys/fixture/secondary"

# A path that exists and is world-readable on the build HOST, with stable
# contents. Needed for the one case that reproduces what the two-identity
# differential is actually for: an identity read missing its ROOT prefix
# resolves against the build host instead of the fixture, so the provider
# returns the same key for every fixture and every device.
#
# PRIMARY cannot serve that case. It resolves nowhere on the host, so an
# unprefixed read of it finds nothing and the provider REFUSES - caught by the
# returncode branch, several guards earlier than the differential. Asserting
# only "the tier refused" hid that for a while; the `match` note on CASES has
# the measurement.
HOST_PATH = "/proc/sys/kernel/ostype"
HOST_PATH_USABLE = os.access(HOST_PATH, os.R_OK)

DERIVE = """\
SALT=$(printf '%s' "$ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)
openssl kdf -binary -keylen 64 -kdfopt pass:"$ID" -kdfopt salt:"$SALT" \\
    -kdfopt iter:3 -kdfopt memcost:65536 -kdfopt lanes:1 ARGON2ID
"""

# Exactly 64 bytes, identical on every run and every machine. What a provider
# emits once it has stopped deriving from anything.
CONSTANT = """\
openssl kdf -binary -keylen 64 -kdfopt pass:FLEET-WIDE-CONSTANT \\
    -kdfopt salt:00112233445566778899aabbccddeeff \\
    -kdfopt iter:3 -kdfopt memcost:65536 -kdfopt lanes:1 ARGON2ID
"""

REFUSE = '[ -n "$ID" ] || { echo "refusing: no identity readable" >&2; exit 1; }\n'


def provider(status, identities, body):
    head = "#!/bin/sh\n# avocado-var-key-provider: %s\n" % status
    for path in identities:
        head += "# avocado-var-key-identity: %s\n" % path
    return head + 'set -eu\nROOT="${1:-}"\nID=""\n' + body


def read_primary(prefixed=True):
    path = '"$ROOT%s"' % PRIMARY if prefixed else '"%s"' % PRIMARY
    return 'if [ -r %s ]; then\n    ID=$(cat %s)\nfi\n' % (path, path)


def read_secondary(prefixed=True):
    path = '"$ROOT%s"' % SECONDARY if prefixed else '"%s"' % SECONDARY
    return 'if [ -z "$ID" ] && [ -r %s ]; then\n    ID=$(cat %s)\nfi\n' % (path, path)


PROVIDERS = {
    # Correct: one declared path, prefixed, refuses when it is absent.
    "good": provider("usable", [PRIMARY], read_primary() + REFUSE + DERIVE),
    # Correct: two declared paths, both prefixed.
    "good_two_path": provider(
        "usable",
        [PRIMARY, SECONDARY],
        read_primary() + read_secondary() + REFUSE + DERIVE,
    ),
    # Emits a fixed key. Passes a length check; fails the differential.
    "constant": provider("usable", [PRIMARY], CONSTANT),
    # Reads its declared path without the ROOT prefix. The path resolves
    # nowhere on the build host, so this one finds no identity and refuses.
    "unprefixed_absent": provider(
        "usable", [PRIMARY], read_primary(prefixed=False) + REFUSE + DERIVE
    ),
    # The same mistake on a path that DOES resolve on the build host. This is
    # the shape the differential exists for: the provider reads the host's file
    # for every fixture, derives one key regardless of the identity it was
    # given, and every device in the fleet would unlock with it.
    "unprefixed_host": provider(
        "usable",
        [HOST_PATH],
        'if [ -r "%s" ]; then\n    ID=$(cat "%s")\nfi\n' % (HOST_PATH, HOST_PATH)
        + REFUSE
        + DERIVE,
    ),
    # Primary prefixed, SECONDARY not. The primary short-circuits under a
    # fixture that populates every declared path at once, so the broken read is
    # never walked. This is C4.
    "unprefixed_secondary": provider(
        "usable",
        [PRIMARY, SECONDARY],
        read_primary() + read_secondary(prefixed=False) + REFUSE + DERIVE,
    ),
    # The same unprefixed-secondary mistake on a path that DOES resolve on the
    # build host. Caught by the per-path differential rather than by a refusal,
    # and it is the case that rules out the weaker cross-path form: with one
    # value per path, primary-only yields key(fixture) and secondary-only
    # yields key(host), which differ - so a cross-path comparison passes while
    # the broken read never touched the fixture.
    "unprefixed_secondary_host": provider(
        "usable",
        [PRIMARY, HOST_PATH],
        read_primary()
        + 'if [ -z "$ID" ] && [ -r "%s" ]; then\n    ID=$(cat "%s")\nfi\n'
        % (HOST_PATH, HOST_PATH)
        + REFUSE
        + DERIVE,
    ),
    # Declares a path it assembles at run time rather than writing literally,
    # so the no-argument copy cannot rewrite it and the read cannot be shown to
    # reach the fixture instead of the host.
    "computed_path": provider(
        "usable",
        [PRIMARY],
        'BASE="/sys/fixture"\n'
        + 'if [ -r "$ROOT$BASE/primary" ]; then\n'
        + '    ID=$(cat "$ROOT$BASE/primary")\nfi\n'
        + REFUSE
        + DERIVE,
    ),
    # Derives properly whenever it is handed a fixture root, and emits a
    # constant when it is not - which is the device's own invocation. Every
    # tier-2 run passes a root, so the constant branch is never measured.
    "argv_evader": provider(
        "usable",
        [PRIMARY],
        'if [ -z "$ROOT" ]; then\n'
        + CONSTANT
        + "    exit 0\nfi\n"
        + read_primary()
        + REFUSE
        + DERIVE,
    ),
    # Mixes in a fresh salt, so two runs of the SAME identity differ. Satisfies
    # the differential for the wrong reason; on a device /var never reopens.
    "nonreproducible": provider(
        "usable",
        [PRIMARY],
        read_primary()
        + REFUSE
        + "SALT=$(openssl rand -hex 16)\n"
        + 'openssl kdf -binary -keylen 64 -kdfopt pass:"$ID" '
        '-kdfopt salt:"$SALT" -kdfopt iter:3 -kdfopt memcost:65536 '
        "-kdfopt lanes:1 ARGON2ID\n",
    ),
    # Derives from a real identity but substitutes a constant when none is
    # readable. The differential cannot see it; only the empty fixture can.
    "constant_fallback": provider(
        "usable",
        [PRIMARY],
        read_primary()
        + 'if [ -z "$ID" ]; then\n'
        + CONSTANT
        + "    exit 0\nfi\n"
        + DERIVE,
    ),
    # A declared path that escapes the fixture root once its leading slash is
    # stripped.
    "escape_path": provider(
        "usable", ["/../../escaped-identity"], read_primary() + REFUSE + DERIVE
    ),
    # Derives from its declared identity, but emits half a key. Nothing else
    # here produces a wrong LENGTH: the constant provider emits a full 64 bytes,
    # so without this case the 64-byte assertion has no test.
    "short_key": provider(
        "usable",
        [PRIMARY],
        read_primary()
        + REFUSE
        + 'SALT=$(printf \'%s\' "$ID" | openssl dgst -sha256 '
        "| sed 's/.*= *//' | cut -c1-32)\n"
        + 'openssl kdf -binary -keylen 32 -kdfopt pass:"$ID" '
        '-kdfopt salt:"$SALT" -kdfopt iter:3 -kdfopt memcost:65536 '
        "-kdfopt lanes:1 ARGON2ID\n",
    ),
    # Exits non-zero even with its declared identity populated. Covers the
    # returncode branch, which the refusal cases reach only via an EMPTY
    # fixture and so never exercise on a populated one.
    "always_fails": provider(
        "usable", [PRIMARY], 'echo "broken" >&2\nexit 1\n'
    ),
    "unusable": provider("unusable", [PRIMARY], read_primary() + REFUSE + DERIVE),
    # What the qemu provider is: no unique identity to read, so it substitutes
    # one rather than refusing.
    "test_only": provider(
        "test-only",
        [PRIMARY],
        read_primary() + 'if [ -z "$ID" ]; then\n    ID=no-serial\nfi\n' + DERIVE,
    ),
}

# The REAL shipped providers, loaded from their vendor layers.
#
# The synthetic providers above cover the tier's rejection branches; these cover
# the other direction, which is the one that breaks a build. Every time this
# tier gets stricter it can start refusing an artifact that was fine - the
# per-path fixture requires each declared read to work on its own, and the
# no-argument run requires each declared path to appear as a literal - and
# neither requirement is visible from reading a provider.
LAYERS = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))

for _layer, _key in (
    ("meta-avocado-nxp", "real_nxp"),
    ("meta-avocado-nvidia", "real_nvidia"),
    ("meta-avocado-x86-64", "real_x86_64"),
    ("meta-avocado-qemu", "real_qemu"),
    ("meta-avocado", "real_shared"),
):
    _path = os.path.join(
        LAYERS, _layer, "recipes-core", "cryptsetup-var", "files", "var-key.sh"
    )
    try:
        with open(_path, encoding="utf-8") as _handle:
            PROVIDERS[_key] = _handle.read()
    except OSError:
        # Absent rather than fatal: a layer can legitimately not be checked out.
        # The cases naming it skip themselves.
        pass


# Declaration-shape variants, built by rewriting a correct provider's comment
# header so the body stays identical and only the declaration under test moves.
PROVIDERS["identity_prose"] = PROVIDERS["good"].replace(
    "# avocado-var-key-identity: %s\n" % PRIMARY,
    "# avocado-var-key-identity: %s\n"
    "# avocado-var-key-identity: %s was previously required\n" % (PRIMARY, SECONDARY),
)
PROVIDERS["two_statuses"] = PROVIDERS["good"].replace(
    "# avocado-var-key-provider: usable\n",
    "# avocado-var-key-provider: usable\n# avocado-var-key-provider: unusable\n",
)
PROVIDERS["no_status"] = PROVIDERS["good"].replace(
    "# avocado-var-key-provider: usable\n", ""
)
PROVIDERS["no_identity"] = PROVIDERS["good"].replace(
    "# avocado-var-key-identity: %s\n" % PRIMARY, ""
)
# A second status carrying square brackets. `[unusable]` is a single bare token,
# so the parser accepts it as a declaration - and bakar streams bitbake's log
# through a Rich handler that reads a bracketed span as a style tag and drops
# it, so an unflattened interpolation reaches the terminal with the offending
# value missing. The one value an author needs in order to fix the file.
PROVIDERS["bracketed_statuses"] = PROVIDERS["good"].replace(
    "# avocado-var-key-provider: usable\n",
    "# avocado-var-key-provider: usable\n"
    "# avocado-var-key-provider: [unusable]\n",
)


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

SOURCE = read_recipe()
NAMESPACE = {}
exec(slice_helpers(SOURCE), NAMESPACE)
exec(slice_task(SOURCE, TIER1), NAMESPACE)
exec(slice_task(SOURCE, TIER2), NAMESPACE)

STATUS_MARKER = marker_value(SOURCE, "AVOCADO_VAR_KEY_MARKER")
IDENTITY_MARKER = marker_value(SOURCE, "AVOCADO_VAR_KEY_IDENTITY_MARKER")
LIBEXECDIR = "/usr/libexec"


def invoke(tier, installed_text, source_text, machine, capabilities):
    """Run one tier against a synthetic ${D} and FILESPATH -> (verdict, detail).

    `installed_text` is what lands in ${D} (what ships). `source_text` is what
    resolves on FILESPATH (what the parse tier judged). They are separate
    because the whole point of the execution tier is that they can differ; pass
    None for either to leave that copy absent.
    """
    root = tempfile.mkdtemp(prefix="var-key-tiers-")
    try:
        image = os.path.join(root, "image")
        files = os.path.join(root, "files")
        workdir = os.path.join(root, "work")
        installed = os.path.join(image + LIBEXECDIR, "cryptsetup-var", "var-key.sh")
        os.makedirs(os.path.dirname(installed))
        os.makedirs(files)
        os.makedirs(workdir)

        if installed_text is not None:
            with open(installed, "w", encoding="utf-8") as handle:
                handle.write(installed_text)
            os.chmod(installed, 0o755)
        if source_text is not None:
            path = os.path.join(files, "var-key.sh")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source_text)

        bb = BB()
        NAMESPACE["bb"] = bb
        NAMESPACE["d"] = Datastore(
            {
                "AVOCADO_SECURITY_CAPABILITIES": capabilities,
                "AVOCADO_VAR_KEY_MARKER": STATUS_MARKER,
                "AVOCADO_VAR_KEY_IDENTITY_MARKER": IDENTITY_MARKER,
                "MACHINE": machine,
                "D": image,
                "libexecdir": LIBEXECDIR,
                "FILESPATH": files,
                "WORKDIR": workdir,
            }
        )
        try:
            NAMESPACE[tier]()
        except Fatal as exc:
            return "fatal", str(exc)
        return "pass", "; ".join(bb.warnings) or "(no warnings)"
    finally:
        shutil.rmtree(root, ignore_errors=True)


HARDWARE = "avocado-imx93-frdm"
PERMITTED = "avocado-qemux86-64"
ARMED = "encrypted-var"

def case(tier, description, installed=None, source=None, machine=HARDWARE,
         caps=ARMED, expect="fatal", match=None, gap=None,
         skip_unless=True, skip_why=""):
    return {
        "tier": tier,
        "description": description,
        "installed": installed,
        "source": source,
        "machine": machine,
        "caps": caps,
        "expect": expect,
        "match": match,
        "gap": gap,
        "skip_unless": skip_unless,
        "skip_why": skip_why,
    }


# `match` is not decoration, and leaving it off is the defect that made this
# whole file worth writing carefully. Asserting only the VERDICT covers the
# tier, not the branch: the guards are layered, so disabling one lets a
# downstream guard refuse the same synthetic provider and the case stays green.
# Measured before `match` existed, 6 of 13 recipe mutations survived that way -
# tier 1's `unusable` fatal fell through to its unrecognised-status check, the
# differential fell through to the negative control, the escape guard and the
# returncode check both fell through to the 64-byte check. Each `match` is a
# substring unique to its branch's message, so the branch is pinned rather than
# the outcome.
CASES = [
    case(TIER1, "parse: a correct provider passes",
         installed="good", source="good", expect="pass"),
    case(TIER1, "parse: unusable is refused",
         installed="unusable", source="unusable",
         match="declares itself unusable"),
    case(TIER1, "parse: test-only on a hardware machine is refused",
         installed="test_only", source="test_only",
         match="is not for a vendor layer to extend"),
    case(TIER1, "parse: test-only on a permitted qemu machine is allowed",
         installed="test_only", source="test_only", machine=PERMITTED,
         expect="pass"),
    case(TIER1, "parse: two status lines are refused",
         installed="two_statuses", source="two_statuses",
         match="cannot be decided"),
    # Matching on the FLATTENED spelling is the assertion. Drop the flat() call
    # around the joined declarations and the message carries `[unusable]`
    # instead, so this match fails - which is the only way to notice, since the
    # value goes missing in the log rather than looking wrong.
    case(TIER1, "parse: a bracketed status is reported flattened",
         installed="bracketed_statuses", source="bracketed_statuses",
         match="usable, (unusable)"),
    case(TIER1, "parse: no status line is refused",
         installed="no_status", source="no_status",
         match="cannot be shown to derive a key"),
    case(TIER1, "parse: no provider on FILESPATH is refused",
         installed="good", source=None,
         match="no var-key.sh resolves on FILESPATH at all"),

    case(TIER2, "exec: a correct single-path provider passes",
         installed="good", source="good", expect="pass"),
    case(TIER2, "exec: a correct two-path provider passes",
         installed="good_two_path", source="good_two_path", expect="pass"),
    case(TIER2, "exec: a constant key is refused",
         installed="constant", source="constant",
         match="derived the SAME key"),
    case(TIER2, "exec: an unprefixed read of an absent path is refused",
         installed="unprefixed_absent", source="unprefixed_absent",
         match="cannot derive a key from its own declared"),
    case(TIER2, "exec: an unprefixed read resolving on the build host is refused",
         installed="unprefixed_host", source="unprefixed_host",
         match="derived the SAME key",
         skip_unless=HOST_PATH_USABLE,
         skip_why="%s is not readable on this host" % HOST_PATH),
    case(TIER2, "exec: a non-reproducible derivation is refused",
         installed="nonreproducible", source="nonreproducible",
         match="derived two DIFFERENT keys"),
    case(TIER2, "exec: a constant fallback on an empty identity is refused",
         installed="constant_fallback", source="constant_fallback",
         match="derived a key from an EMPTY"),
    case(TIER2, "exec: an escaping declared path is refused",
         installed="escape_path", source="escape_path",
         match="escapes the fixture root"),
    case(TIER2, "exec: a multi-token identity line is refused",
         installed="identity_prose", source="identity_prose",
         match="whose value is not a single path"),
    case(TIER2, "exec: no declared identity is refused",
         installed="no_identity", source="no_identity",
         match="the paths to populate"),
    case(TIER2, "exec: a key of the wrong length is refused",
         installed="short_key", source="short_key",
         match="64 raw key bytes"),
    case(TIER2, "exec: a provider that exits non-zero is refused",
         installed="always_fails", source="always_fails",
         match="cannot derive a key from its own declared"),
    case(TIER2, "exec: no provider installed is refused",
         installed=None, source="good",
         match="no var-key.sh was installed at"),
    case(TIER2, "exec: two status lines in the installed copy are refused",
         installed="two_statuses", source="good",
         match="exactly one is required"),
    case(TIER2, "exec: unusable installed under a usable source is refused",
         installed="unusable", source="good",
         match="the parse-time check would have refused"),
    case(TIER2, "exec: installed test-only under a usable source is refused",
         installed="test_only", source="good", machine=PERMITTED,
         match="the provider on FILESPATH"),
    case(TIER2, "exec: installed constant under a test-only source is refused",
         installed="constant", source="test_only", machine=PERMITTED,
         match="derived the SAME key"),

    # C5, recorded as a case rather than prose. Both tiers read the capability
    # from cryptsetup-var.bb's own datastore, while the artifact the device
    # reads is written from the image recipe - so a one-line bbappend clearing
    # it here disarms both tiers and still ships `encrypted-var` on the device.
    case(TIER1, "parse: a cleared capability skips the tier",
         installed="unusable", source="unusable", caps="", expect="pass",
         gap='C5: `AVOCADO_SECURITY_CAPABILITIES = ""` in a '
             "cryptsetup-var.bbappend disarms this tier while the image still "
             "ships encrypted-var. Expect `fatal` once the gate reads the "
             "image-level declaration instead."),
    case(TIER2, "exec: a cleared capability skips the tier",
         installed="unusable", source="unusable", caps="", expect="pass",
         gap="C5: same bypass on the execution tier - the UNUSABLE provider "
             "this whole check exists to stop reaches a device on a green "
             "build."),

    # C4. Both halves, because they are caught by different branches and only
    # the second one shows why the fixture compares two values at ONE path
    # rather than one value across two paths.
    case(TIER2, "exec: an unprefixed secondary read of an absent path is refused",
         installed="unprefixed_secondary", source="unprefixed_secondary",
         match="cannot derive a key from its own declared"),
    case(TIER2, "exec: an unprefixed secondary resolving on the build host is refused",
         installed="unprefixed_secondary_host",
         source="unprefixed_secondary_host",
         match="at its declared path",
         skip_unless=HOST_PATH_USABLE,
         skip_why="%s is not readable on this host" % HOST_PATH),
    # Q1.
    case(TIER2, "exec: a provider that derives only when handed a root is refused",
         installed="argv_evader", source="argv_evader",
         match="invoked with no argument"),
    case(TIER2, "exec: a declared path absent as a literal is refused",
         installed="computed_path", source="computed_path",
         match="does not appear literally"),

    # The real shipped providers must still pass.
    case(TIER2, "exec: the real nxp provider passes",
         installed="real_nxp", source="real_nxp", expect="pass",
         skip_unless="real_nxp" in PROVIDERS, skip_why="layer not checked out"),
    case(TIER2, "exec: the real nvidia provider passes",
         installed="real_nvidia", source="real_nvidia", expect="pass",
         skip_unless="real_nvidia" in PROVIDERS,
         skip_why="layer not checked out"),
    case(TIER2, "exec: the real x86-64 provider passes",
         installed="real_x86_64", source="real_x86_64", expect="pass",
         skip_unless="real_x86_64" in PROVIDERS,
         skip_why="layer not checked out"),
    case(TIER2, "exec: the real qemu provider passes on a permitted machine",
         installed="real_qemu", source="real_qemu", machine=PERMITTED,
         expect="pass",
         skip_unless="real_qemu" in PROVIDERS,
         skip_why="layer not checked out"),
    case(TIER1, "parse: the real shared placeholder provider is refused",
         installed="real_shared", source="real_shared",
         match="declares itself unusable",
         skip_unless="real_shared" in PROVIDERS,
         skip_why="layer not checked out"),
]


def main():
    if not shutil.which("openssl"):
        print("SKIP: host missing openssl")
        return 0
    probe = subprocess.call(
        [
            "openssl", "kdf", "-binary", "-keylen", "8",
            "-kdfopt", "pass:x", "-kdfopt", "salt:0123456789abcdef",
            "-kdfopt", "iter:3", "-kdfopt", "memcost:65536",
            "-kdfopt", "lanes:1", "ARGON2ID",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe != 0:
        print("SKIP: host openssl has no ARGON2ID")
        return 0

    passed = failed = gaps = skipped = 0
    for spec in CASES:
        description = spec["description"]
        expect = spec["expect"]
        want = spec["match"]
        if not spec["skip_unless"]:
            print("  skip - %s" % description)
            print("         %s" % spec["skip_why"])
            skipped += 1
            continue
        verdict, detail = invoke(
            spec["tier"],
            PROVIDERS[spec["installed"]] if spec["installed"] else None,
            PROVIDERS[spec["source"]] if spec["source"] else None,
            spec["machine"],
            spec["caps"],
        )
        first = detail.splitlines()[0] if detail else ""
        if verdict != expect:
            print("  FAIL - %s" % description)
            print("         expected %s, got %s: %s" % (expect, verdict, first))
            failed += 1
        elif want and want not in detail:
            # The tier refused, but through a different branch than the one
            # this case exists to cover. Reported as a failure rather than a
            # pass, because the branch under test is now unguarded.
            print("  FAIL - %s" % description)
            print("         refused, but not by the branch under test")
            print("         wanted: %s" % want)
            print("         got:    %s" % first)
            failed += 1
        elif spec["gap"]:
            print("  gap  - %s" % description)
            print("         %s" % spec["gap"])
            gaps += 1
        else:
            print("  ok   - %s" % description)
            passed += 1

    print()
    print("passed: %d  failed: %d  open gaps: %d  skipped: %d"
          % (passed, failed, gaps, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
