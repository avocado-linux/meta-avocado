# Fails a build, loudly, when it requests a security feature the selected
# machine cannot deliver.
#
# The request side (DISTRO_FEATURES: ahab, ftpm, tpm2, verified-boot) has no
# machine restriction - a kas feature overlay composes with any machine.yml.
# The delivery side is a set of per-machine facts (a MACHINE_FEATURES entry, a
# kernel config fragment, a COMPATIBLE_MACHINE opt-in list) that must happen to
# agree with what was requested, and nothing checked that they did. This class
# is that check.
#
# AVOCADO_SECURITY_CAPABILITIES is also what recipes gate on to BUILD a
# capability's tooling - `bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES',
# 'encrypted-var', ...)` - so declaring is what puts it in the feed, and the
# user's avocado.yaml decides whether a runtime uses it.
#
# AVOCADO_SECURITY_CAPABILITIES is the one place a machine states which of
# these features it can deliver. It is deliberately its own variable rather
# than a MACHINE_FEATURES entry, because MACHINE_FEATURES cannot distinguish
# "this board declared no security capabilities" from "nobody has migrated
# this board onto the declaration yet" - both read as the feature's absence
# from the list. AVOCADO_SECURITY_CAPABILITIES being unset (getVar returns
# None) is the second case; being set to an explicitly empty string is the
# first, and the two produce different diagnostics below.
#
# Registered on bb.event.ConfigParsed rather than checked in a recipe task,
# because DISTRO_FEATURES and MACHINE resolve once, from local.conf/machine
# conf/distro conf, at config-parse time - long before any recipe is parsed.
# That is what lets this check reach a bare `bitbake <recipe>`, not only a
# full image build: a guard placed in a recipe task never runs if the
# recipe's own parse dies first (which is exactly what happened to
# avocado-slot-root-generator, fixed separately). oe-core's own sanity.bbclass
# uses this same addhandler + bb.event.ConfigParsed + bb.fatal shape
# (classes-global/sanity.bbclass:1149-1151, :188), so the pattern is
# house-idiomatic here, not invented for this class.
#
# features_check.bbclass (already used by five recipes in this tree) is not
# reused as the enforcement point, on purpose: it fails via
# bb.parse.SkipRecipe, which for an ordinary recipe just means the recipe is
# skipped, but for a SECURITY feature means the feature silently does not
# ship. A silent skip is the exact failure mode this class exists to remove.

# verified-boot joins the list so that requesting it on a machine that has not
# declared it is REFUSED rather than silently ignored. Until now
# kas/feature/verified-boot.yml appended the token to DISTRO_FEATURES and every
# consumer gated on it independently, so asking for it on a machine with no FIT
# signing key wired produced an ordinary unsigned build and no diagnostic - the
# failure mode this class exists to remove.
#
# encrypted-var is deliberately NOT in this list any more. It is no longer a
# build-time request: a machine that declares the capability gets the tooling
# built (dm-crypt in the kernel, cryptsetup-var in the initramfs, the udev and
# posture pieces in the rootfs), and whether a device encrypts is decided per
# runtime by avocado.yaml (var.encrypt). A leftover DISTRO_FEATURES token from an
# old kas overlay is harmless and warned about below. docs/security-capabilities.md
# has the model.
AVOCADO_SECURITY_FEATURES ?= "ahab ftpm tpm2 verified-boot"

def avocado_security_capabilities_check(d):
    if "encrypted-var" in (d.getVar("DISTRO_FEATURES") or "").split():
        bb.warn(
            "DISTRO_FEATURES contains encrypted-var, which no longer selects "
            "anything: the tooling ships wherever AVOCADO_SECURITY_CAPABILITIES "
            "declares encrypted-var, and a runtime turns it on with avocado.yaml "
            "var.encrypt. Drop the token (kas/feature/encrypted-var.yml is gone)."
        )
    requested = [
        feature
        for feature in (d.getVar("AVOCADO_SECURITY_FEATURES") or "").split()
        if feature in (d.getVar("DISTRO_FEATURES") or "").split()
    ]

    # No security feature requested: the check has nothing to say, on a
    # migrated machine or not. An unmigrated machine building its ordinary,
    # non-security image must not be affected by this class existing.
    if not requested:
        return

    machine = d.getVar("MACHINE") or "<unknown>"
    capabilities = d.getVar("AVOCADO_SECURITY_CAPABILITIES")

    # Absent declaration: this machine has not been migrated onto
    # AVOCADO_SECURITY_CAPABILITIES at all. Refused, distinctly from the
    # explicitly-empty case below (that one names the features missing from a
    # real, non-empty-or-empty declaration; this one names the declaration
    # itself as absent) - migrating a board is "add the line", not "guess
    # which features it happens to support by trying a build".
    #
    # This was landed permissive through groups 1-3 while avocado-qemuarm64,
    # avocado-qemux86-64, avocado-imx93-frdm and avocado-raspberrypi migrated
    # (raspberrypi's migration was in fact stopped mid-way on an unrelated,
    # pre-existing partition-numbering defect - see task 2.4's notes - so it
    # remains unmigrated and is refused here along with
    # avocado-grinn-astra-1680-sbc, avocado-rubikpi3 and the Jetson family).
    # A machine with no declaration and no security feature requested is
    # unaffected either way - see the empty-`requested`-list return above.
    #
    # No square brackets in these messages: bakar streams bitbake's log
    # through a RichHandler with markup=True (observability.py:132), and Rich
    # console markup parses "[...]" as a style tag. An unrecognised tag is
    # dropped silently rather than printed literally, so "requested feature
    # [encrypted-var]" reaches the terminal as "requested feature " with the
    # feature name gone - verified directly against a live bakar build.
    # That defeats the one property this diagnostic exists for: naming the
    # machine, the feature and the prerequisite so an operator does not have
    # to read the check to interpret the failure.
    if capabilities is None:
        bb.fatal(
            "machine %s requested security feature(s) %s but declares no "
            "AVOCADO_SECURITY_CAPABILITIES at all. Unmet prerequisite: add "
            "AVOCADO_SECURITY_CAPABILITIES to this machine's conf naming "
            "every security feature it can actually deliver, or drop the "
            "feature request if this machine has not been migrated onto the "
            "declaration yet."
            % (machine, ", ".join(requested))
        )

    declared = capabilities.split()
    missing = [feature for feature in requested if feature not in declared]
    if not missing:
        return

    # An explicitly empty declaration ("this machine supports nothing") is
    # refused now, not deferred to the task 4.1 flip - it is a real answer
    # from a migrated machine, not the "nobody has looked at this yet" state
    # the absent-declaration branch above exists to tolerate temporarily.
    bb.fatal(
        "machine %s requested security feature(s) %s not present in its "
        "AVOCADO_SECURITY_CAPABILITIES declaration (%s). Unmet prerequisite: "
        "add %s to AVOCADO_SECURITY_CAPABILITIES in this machine's conf, or "
        "drop the feature request if the machine genuinely cannot deliver it."
        % (
            machine,
            " ".join(missing),
            "AVOCADO_SECURITY_CAPABILITIES = \"%s\"" % capabilities if capabilities else "explicitly empty",
            " ".join(missing),
        )
    )

# This handler checks REQUEST versus DECLARATION only: did the machine say it
# can deliver a feature that DISTRO_FEATURES asked for. It cannot check
# DELIVERABILITY - whether a declared capability's tooling can actually reach
# a booted device (e.g. a key provider for encrypted-var) - because that
# question depends on FILESEXTRAPATHS, which is recipe-level data that does
# not exist yet when bb.event.ConfigParsed fires here; DISTRO_FEATURES and
# MACHINE are parsed by then, but no recipe has been parsed at all.
# cryptsetup-var.bb carries the second half of this enforcement, in TWO tiers,
# and which one refuses decides where to look:
#   - at recipe parse, that a var-key provider resolves via FILESEXTRAPATHS and
#     declares itself usable, or test-only for a machine meta-avocado has
#     listed as permitted to waive the refusal check;
#   - at do_install, that the INSTALLED provider actually derives - it is run
#     against two synthetic identity fixtures and must return two different
#     64-byte keys, then against an empty one and must refuse. A provider
#     that cannot refuse has to declare itself test-only, which is accepted
#     for a disposable virtual target, gated on a meta-avocado machine list,
#     and warns when the check runs (sstate can skip it).
# A build that gets past parse and fails at do_install failed the second tier,
# not this class and not the first. See README-deliverability.md beside that
# recipe, "The var-key provider contract".
# Read them together - this class covers request-vs-declaration, that recipe
# covers declaration-vs-deliverability.
# --- var-key provider declaration parsing -------------------------------------
#
# These live here rather than in cryptsetup-var.bb because that recipe is no
# longer the only reader. The image-scope gate below parses the SAME
# declarations out of the provider that was actually installed into the
# initramfs, and a second copy of this parser is precisely the drift this whole
# check exists to prevent: the two readers would disagree about what a
# declaration means and the disagreement would be invisible.
#
# The class is inherited globally (conf/distro/include/avocado-security.inc),
# so cryptsetup-var.bb reaches them without an explicit inherit.

def avocado_var_key_flat(text):
    """Flatten square brackets so bakar's Rich log handler cannot eat a value.

    bakar streams bitbake's log through a Rich handler with markup enabled,
    which parses a bracketed span as a style tag and drops it. Module level, so
    BOTH tiers reach it: the parse tier interpolates provider-file content -
    a status token is whatever the file says, and `[usable]` parses as a valid
    single token - and rendering that message lost the exact string an author
    needs to fix.
    """
    return str(text).replace("[", "(").replace("]", ")")


def avocado_var_key_declarations(contents, marker):
    """Every comment line in CONTENTS declaring MARKER, as a list of values.

    Exactly one leading '#' is stripped, not all of them: lstrip("#") also
    matched an indented documentation example like '#   # <marker>: usable', so
    a provider that merely SHOWS the contract in prose was read as declaring it.
    Both tiers match a declaration rather than prose, and stripping one hash is
    what distinguishes them.
    """
    found = []
    prose = []
    for line in contents.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        body = stripped[1:].strip()
        if not body.startswith(marker):
            continue
        value = body[len(marker):].strip()
        # A declaration's value is a single bare token. Stripping one '#'
        # separates a declaration from an indented example of one, but not from
        # prose that opens with the marker and runs on into a sentence - a
        # migration note reading '<marker>: usable was previously required ...'
        # was collected as a declaration whose status was the whole remaining
        # sentence, and refused the build for an unrecognised status.
        #
        # A multi-token line is returned SEPARATELY rather than dropped, and the
        # distinction is load-bearing rather than tidy. Dropping is safe for the
        # status marker, where losing every match still ends in a fatal, and
        # unsafe for the identity marker, where losing ONE of several is
        # invisible: the fixture is built one path short, the provider falls
        # through to a path that is populated, two different keys still come
        # out, and the build passes while the dropped read resolves against the
        # build host - the exact case the two-identity assertion exists to
        # catch. Each caller decides which of the two it can afford.
        if value and len(value.split()) == 1:
            found.append(value)
        else:
            prose.append(body)
    return found, prose


def avocado_var_key_test_only_machines():
    """Machines permitted to ship a `test-only` var-key provider.

    A literal, not a d.getVar. AVOCADO_VAR_KEY_TEST_ONLY_MACHINES is published
    for readers only: conf files parse before recipes, so a machine conf or a
    local.conf setting it wins over any assignment in a recipe, and a vendor
    could name its own machine into the waiver. An allow-list the constrained
    party can edit constrains nobody.

    Here rather than in cryptsetup-var.bb because both the parse tier and the
    image-scope gate below decide the same waiver, and an allow-list that
    disagrees with itself across two readers is worse than either copy.
    """
    return ("avocado-qemux86-64", "avocado-qemuarm64")


addhandler avocado_security_capabilities_eventhandler
avocado_security_capabilities_eventhandler[eventmask] = "bb.event.ConfigParsed"
python avocado_security_capabilities_eventhandler() {
    avocado_security_capabilities_check(e.data)
}

# Runtime-readable artifact exposing this machine's declared
# AVOCADO_SECURITY_CAPABILITIES to a booted device. Generated FROM the
# BitBake variable at image-build time - never a second, hand-maintained
# copy of the declaration - so an extension's on-device activation check
# can tell "this device's base image claims capability X" without any
# channel back to build-time BitBake state.
#
# None (unset) vs "" (explicitly empty) matters here exactly as it does in
# the ConfigParsed check above: an unmigrated machine gets no artifact at
# all (nothing to read is the correct answer, not a fabricated empty file),
# while a migrated machine that declares no capabilities gets an empty
# file - a real, distinguishable answer from a real declaration.
#
# Hooked from ROOTFS_POSTPROCESS_COMMAND by avocado-image-rootfs.bb AND
# avocado-image-initramfs.bb rather than added here, so this class stays
# enforcement-only for recipes that merely inherit it globally
# (conf/distro/include/avocado-security.inc) without becoming an image
# rootfs itself. Both images need it: the rootfs is where an on-device
# extension reads the declaration, and the initramfs is where
# cryptsetup-var.sh reads it - that unit is an initrd unit, so the
# initramfs is actually the FIRST consumer.
python avocado_security_capabilities_write_artifact() {
    import os

    capabilities = d.getVar("AVOCADO_SECURITY_CAPABILITIES")
    if capabilities is None:
        return

    rootfs = d.getVar("IMAGE_ROOTFS")
    sysconfdir = d.getVar("sysconfdir")
    destdir = rootfs + sysconfdir
    bb.utils.mkdirhier(destdir)
    path = os.path.join(destdir, "avocado-security-capabilities")
    with open(path, "w") as f:
        f.write(capabilities + "\n")
}

# The gate that cannot be disarmed from cryptsetup-var.bbappend.
#
# cryptsetup-var.bb's two tiers both read AVOCADO_SECURITY_CAPABILITIES from
# THAT RECIPE'S datastore, while the artifact above is written from the IMAGE
# recipe's. The two are different datastores, so a one-line
#
#     AVOCADO_SECURITY_CAPABILITIES = ""
#
# in a cryptsetup-var.bbappend silenced both tiers while the image went on
# shipping /etc/avocado-security-capabilities containing encrypted-var. The
# device's own check (cryptsetup-var.sh) reads that file, passes, and derives
# with whatever var-key.sh shipped - including the `unusable` placeholder the
# whole check exists to stop. Confirmed on a real build: the refusal count went
# from 1 to 0 with that bbappend in place.
#
# Fixed by altitude rather than by another variable. Every variable is
# overridable by whoever is doing the overriding, so a canonical copy in a
# second variable moves the problem rather than removing it. Here the
# declaration and the shipped provider are visible in ONE datastore at ONE
# point, so they cannot disagree: this runs from the initramfs image's
# ROOTFS_POSTPROCESS_COMMAND, reads the capability the image is about to write,
# and inspects the provider that image actually contains.
#
# The initramfs and not the rootfs, because that is where the provider ships:
# packagegroup-avocado-initramfs.bb installs `cryptsetup cryptsetup-var` when
# the capability is declared, while the rootfs gets only the udev and posture
# packages. It is also where the provider is consumed first, cryptsetup-var.sh
# being an initrd unit.
#
# Deliberately NOT a second copy of the derivation check. cryptsetup-var.bb
# runs the provider against synthetic identities and that stays the expensive,
# authoritative tier. This one answers the question that tier cannot ask about
# itself - "did it run at all, and over the provider that shipped?" - which a
# status read is enough for.
python avocado_security_capabilities_check_provider() {
    import hashlib
    import os

    capabilities = d.getVar("AVOCADO_SECURITY_CAPABILITIES")
    if capabilities is None or "encrypted-var" not in capabilities.split():
        return

    flat = avocado_var_key_flat
    machine = d.getVar("MACHINE") or "<unknown>"
    marker = d.getVar("AVOCADO_VAR_KEY_MARKER") or "avocado-var-key-provider:"
    rootfs = d.getVar("IMAGE_ROOTFS")
    libexecdir = d.getVar("libexecdir")
    provider = os.path.join(
        rootfs + libexecdir, "cryptsetup-var", "var-key.sh"
    )
    lead = ("machine %s declares encrypted-var and this image "
            % flat(machine))

    # A symlink is not the artifact, and here the mismatch is worse than in the
    # recipe tier: os.path.isfile() and open() follow the link, so an ABSOLUTE
    # symlink in the image resolves against the build host now and against the
    # image's own root at boot. A link to a host file declaring `usable` would
    # pass this gate while the device finds something else, or nothing.
    if os.path.islink(provider):
        bb.fatal(
            lead + "ships its var-key.sh at %s as a symlink. This gate and the "
            "device resolve it in different namespaces, so a declaration read "
            "here says nothing about what the device runs. Ship the provider "
            "as a regular file." % flat(provider)
        )

    if not os.path.isfile(provider):
        bb.fatal(
            lead + "ships no var-key.sh at %s. cryptsetup-var.sh reads "
            "/etc/avocado-security-capabilities from this initramfs, sees "
            "encrypted-var, and has nothing to derive a key with, so /var "
            "never unlocks. Either the capability does not belong on this "
            "machine, or packagegroup-avocado-initramfs is not installing "
            "cryptsetup-var." % flat(provider)
        )

    try:
        with open(provider, encoding="utf-8", errors="replace") as f:
            contents = f.read()
    except OSError as exc:
        bb.fatal(
            lead + "could not read the var-key.sh it ships at %s: %s."
            % (flat(provider), flat(exc))
        )

    # THE ATTESTATION, before the status declaration is trusted at all.
    #
    # A status line says what a provider claims; it says nothing about whether
    # THIS file is the one tier 2 executed. A bbappend postfunc registered after
    # avocado_var_key_check_deliverability can replace the validated script with
    # an `exit 1` or a constant-key body carrying the same `usable` line, and
    # every check below would pass it. Tier 2 writes the digest of the bytes it
    # actually exercised beside the provider; requiring a match is what binds
    # what was tested to what ships.
    #
    # A MISSING attestation is the louder case, not the quieter one: tier 2
    # writes it last, so its absence means tier 2 did not finish - and the way
    # it does not finish is by returning early on a capability this image still
    # declares. That is the recipe-datastore bypass, caught here a second time
    # and by a different signal than the status read below.
    attestation = provider + ".sha256"
    if not os.path.isfile(attestation):
        bb.fatal(
            lead + "ships a var-key.sh (%s) with no attestation beside it. "
            "cryptsetup-var.bb writes that file last, after every deliverability "
            "check passes, so its absence means those checks did not run over "
            "this provider - most likely a cryptsetup-var.bbappend clearing "
            "AVOCADO_SECURITY_CAPABILITIES, which does not reach this image's "
            "declaration." % flat(provider)
        )

    try:
        with open(attestation, encoding="utf-8", errors="replace") as f:
            recorded = f.read().strip()
        with open(provider, "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
    except OSError as exc:
        bb.fatal(
            lead + "could not read the var-key.sh it ships (%s) or its "
            "attestation: %s." % (flat(provider), flat(exc))
        )

    if recorded != actual:
        bb.fatal(
            lead + "ships a var-key.sh (%s) that is NOT the file cryptsetup-var "
            "validated. The attestation records %s and the shipped provider "
            "hashes to %s, so the script this image will run was replaced after "
            "it was checked - a do_install postfunc in a bbappend is the way "
            "that happens. Whatever the replacement declares about itself, it "
            "has not been shown to derive a device-unique key."
            % (flat(provider), flat(recorded or "<empty>"), flat(actual))
        )

    statuses, _prose = avocado_var_key_declarations(contents, marker)
    if len(statuses) != 1:
        bb.fatal(
            lead + "ships a var-key.sh (%s) carrying %d '%s' status lines; "
            "exactly one is required. cryptsetup-var.bb refuses this at parse "
            "time, so reaching it here means that check did not run over this "
            "provider."
            % (flat(provider), len(statuses), marker)
        )

    status = statuses[0]
    if status == "unusable":
        bb.fatal(
            lead + "ships the placeholder var-key.sh (%s), which declares "
            "itself unusable and cannot derive a key at all. cryptsetup-var.bb "
            "refuses this at parse time, so reaching it here means that check "
            "was disarmed - most likely by a cryptsetup-var.bbappend clearing "
            "AVOCADO_SECURITY_CAPABILITIES, which does not reach this image's "
            "declaration." % flat(provider)
        )

    if status not in ("usable", "test-only"):
        bb.fatal(
            lead + "ships a var-key.sh (%s) declaring the unrecognised status "
            "'%s'; expected 'usable', 'test-only' or 'unusable'."
            % (flat(provider), flat(status))
        )

    if status == "test-only":
        allowed = avocado_var_key_test_only_machines()
        if machine not in allowed:
            bb.fatal(
                lead + "ships a var-key.sh (%s) declared test-only, which "
                "waives the requirement to refuse when no hardware identity is "
                "readable - so every device built from this image derives the "
                "SAME /var key. Permitted only for %s."
                % (flat(provider), ", ".join(allowed))
            )
        bb.warn(
            "machine %s ships a test-only var-key.sh (%s) in its initramfs: "
            "every device built from this image may derive the same /var key. "
            "Intended for disposable virtual targets only."
            % (machine, flat(provider))
        )
}

# devtool-debt: kas/feature/ftpm.yml (imx93-ahab-secure-boot branch only, not
# present on this branch) still does MACHINE_FEATURES:append = " optee-ftpm"
# directly, a second place avocado-imx93-frdm's fTPM support gets asserted
# outside AVOCADO_SECURITY_CAPABILITIES. Not fixable from here: the file does
# not exist on this branch to edit. Ceiling: the duplication stands for as
# long as the two branches remain separate. Upgrade trigger: the branches
# merge, or ftpm.yml's own MACHINE_FEATURES:append is replaced with a read of
# this machine's AVOCADO_SECURITY_CAPABILITIES declaration.
