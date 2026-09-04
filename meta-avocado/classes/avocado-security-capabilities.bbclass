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


def avocado_var_key_marker():
    """The status-declaration token, owned here because both tiers read it.

    It used to be a recipe-scope `=` in cryptsetup-var.bb with a hardcoded
    copy in the image tier's `getVar(...) or "..."` fallback. An image recipe's
    datastore never carries a recipe-scope variable, so the fallback was not a
    fallback - it was the only branch that tier ever took, and a second source
    of truth for the string. Renaming the token in the recipe would have left
    the image tier scanning for the old one and reporting "0 status lines;
    exactly one is required", accusing a bbappend of a bypass that never
    happened.
    """
    return "avocado-var-key-provider:"


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
def avocado_var_key_attested_components():
    """Everything on the /var unlock path the attestation binds.

    Each entry is (directory variable, path under it, required). Two
    directories, not one: the list started as scripts under
    ${libexecdir}/cryptsetup-var/ and that was the wrong boundary. Binding the
    scripts while leaving the unit that RUNS them unbound is the same mistake
    one level up as binding var-key.sh while leaving cryptsetup-var.sh unbound
    - the provider derives 64 bytes, cryptsetup-var.sh decides whether it is
    called, and cryptsetup-var.service decides whether ANY of it happens.

    cryptsetup-var.service earns its place on the strength of two lines it
    carries. `ExecStart=` names which script performs the unlock, so repointing
    it substitutes the whole path at once. `ConditionPathExists=` gates the
    unit, so a path that never exists skips it silently and fstab mounts a
    plaintext /var - which the unit's own comment identifies as the failure it
    was written to prevent. Neither edit changes a single script digest.

    avocado-posture-publish.sh is deliberately absent. It ships in
    ${PN}-posture, which lands in the rootfs and never in the initramfs, while
    everything here ships in ${PN}; attesting it would put its digest in a
    different package from the script - FILES:${PN} globs the libexec directory
    and would claim the .sha256 while FILES:${PN}-posture names only the
    script. It also runs after unlock and gates nothing.

    Also absent, and for a reason that is a limit rather than a decision:
    /etc/avocado/var-hardware selects unlock POLICY (which engine must hold a
    keyslot) and is written by avocado-cli at a different lifecycle stage, not
    by this recipe. Nothing here can attest a file it does not produce. Read
    "the unlock path is bound" as covering the mechanism, not the policy.

    var-hwkey.sh is optional in ONE direction: a machine without a key-wrapping
    engine ships no such file and that is correct, but a machine that does ship
    one must attest it. Skipping an unattested optional component is the
    obvious implementation and it reopens the hole for the exact file a vendor
    bbappend adds.
    """
    return (
        ("libexecdir", "cryptsetup-var/cryptsetup-var.sh", True),
        ("libexecdir", "cryptsetup-var/var-key.sh", True),
        ("libexecdir", "cryptsetup-var/var-hwkey.sh", False),
        ("systemd_system_unitdir", "cryptsetup-var.service", True),
    )


def avocado_var_key_digest(path):
    """SHA-256 of PATH's bytes, as the hex string the .sha256 files carry."""
    import hashlib

    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def avocado_var_key_resolve_shipped(root, subpath, lead, flat, fatal):
    """Resolve SUBPATH under ROOT, refusing anything that escapes it.

    `os.path.islink` on the leaf alone is not enough, and that was the first
    version of this guard. A symlink at ANY component redirects the read: a
    postfunc that replaces the `cryptsetup-var` DIRECTORY with a link leaves
    the leaf a regular file, so `islink(leaf)` is False and `isfile(leaf)` is
    True while both this gate and the attestation beside it resolve into a
    directory the author chose. Resolving the whole path and requiring it to
    stay under ROOT covers every component at once.

    Returns the resolved path. Calls FATAL and does not return when the path
    escapes; the caller decides what an ABSENT file means, because that answer
    differs per image.
    """
    import os

    candidate = os.path.join(root, subpath.lstrip("/"))

    # The escape check below asks WHERE the path lands, and a link pointing
    # back inside ROOT answers that correctly while still being two files: the
    # same postfunc that wrote the link can retarget it after this gate has
    # read through it, so what was attested and what boots are decided
    # separately. Worse when the link DANGLES - os.path.isfile is then False,
    # so a caller's not-required branch skips the component as merely absent
    # and nothing is attested at all.
    #
    # Checked here rather than at each call site: this is the one function all
    # three tiers resolve through, and the leaf-versus-parent split above is
    # already the lesson that a guard added to one caller is a guard missing
    # from the others. Found by executing the avocado-cli half of this check,
    # not by reading either half.
    if os.path.islink(candidate):
        fatal(
            lead + "ships %s as a symlink. This gate reads the link's target "
            "on the build host and the device reads whatever the same path "
            "resolves to at boot, so a check here says nothing about what "
            "runs there. Ship it as a regular file."
            % flat(candidate)
        )

    resolved = os.path.realpath(candidate)
    root_resolved = os.path.realpath(root)
    if resolved != root_resolved and not resolved.startswith(
        root_resolved + os.sep
    ):
        fatal(
            lead + "ships %s as a path that resolves outside the image, to %s. "
            "A symlink at any component - the file or a parent directory - "
            "makes this gate and the device read different files, so a "
            "declaration read here says nothing about what the device runs. "
            "Ship it as a regular file inside the image."
            % (flat(candidate), flat(resolved))
        )
    return candidate


# Registered HERE and not in a named image recipe. It lived in
# avocado-image-initramfs.bb alone, so a machine setting its own
# INITRAMFS_IMAGE - avocado-grinn-astra-1680-sbc.conf:26 already does - got no
# image-scope gate, and the recipe-datastore bypass this tier exists to catch
# would have reopened in full for it. An image bbappend could also drop the
# line with ROOTFS_POSTPROCESS_COMMAND:remove and leave no trace.
#
# Ordered after the artifact writer so the capability file it validates against
# is the one just written. The check returns early on any image that neither
# declares the capability nor ships a provider, so inheriting it everywhere
# costs a non-participating image one getVar.
ROOTFS_POSTPROCESS_COMMAND:append = " avocado_security_capabilities_check_provider;"

python avocado_security_capabilities_check_provider() {
    import os

    capabilities = d.getVar("AVOCADO_SECURITY_CAPABILITIES")
    if capabilities is None or "encrypted-var" not in capabilities.split():
        return

    flat = avocado_var_key_flat
    machine = d.getVar("MACHINE") or "<unknown>"
    # The marker is recipe-scope in cryptsetup-var.bb, so it is never set in an
    # IMAGE recipe's datastore and the getVar below always returns None. That
    # made the fallback the only live branch and a second source of truth for
    # the token - in the file whose own header argues the parser moved here so
    # the two readers could not disagree. The class owns the default now, and
    # the recipe reads it from here, so there is one string again.
    marker = d.getVar("AVOCADO_VAR_KEY_MARKER") or avocado_var_key_marker()
    rootfs = d.getVar("IMAGE_ROOTFS")
    libexecdir = d.getVar("libexecdir")
    lead = ("machine %s declares encrypted-var and this image "
            % flat(machine))

    components = avocado_var_key_attested_components()

    # A bbclass helper is a plain `def` in BitBake's process-global method pool,
    # and bb/methodpool.py's insert_method adds it with, in its own words, "no
    # checking will be done" - so a later `def` of the same name in an image
    # bbappend silently wins. Returning a one-element tuple there would leave
    # this loop iterating nothing while the gate still ran and still reported
    # success, which is quieter than the ROOTFS_POSTPROCESS_COMMAND:remove
    # escape already named below because that one is at least greppable.
    #
    # Asserting the two required names is the cheapest closure. Kept despite
    # "delete-and-test" - nothing fails without it, because the failure it
    # catches is a redefinition no test can introduce.
    required_names = {os.path.basename(sub) for _dv, sub, req in components if req}
    if not {"cryptsetup-var.sh", "var-key.sh",
            "cryptsetup-var.service"} <= required_names:
        bb.fatal(
            lead + "resolved a component list missing a required script (got "
            "%s). avocado_var_key_attested_components() is a bbclass def and a "
            "bbappend can redefine it, so this gate refuses a list it does not "
            "recognise rather than checking whatever it was handed."
            % flat(", ".join(sorted(required_names)) or "<empty>")
        )

    # Which components this image actually ships, resolved BEFORE any decision
    # about an absent provider.
    #
    # Gating the component checks on var-key.sh is what the first version of
    # this loop did, and it made the higher-value target checkable only when the
    # smaller one was present: the early return below fires for a rootfs, so
    # deleting the provider disarmed the cryptsetup-var.sh check entirely.
    # Measured - a rootfs sysroot carrying a substituted unlock script, a stale
    # digest and no provider passed with no diagnostic. The provider derives 64
    # bytes; cryptsetup-var.sh decides whether it is ever asked to, so the set
    # cannot hang off the member it exists to stop being the only one checked.
    shipped = {}
    for dirvar, subpath, _required in components:
        root_dir = d.getVar(dirvar)
        if not root_dir:
            bb.fatal(
                lead + "cannot resolve %s, so it cannot say where %s should "
                "be. That variable is set by bitbake.conf for every image."
                % (flat(dirvar), flat(subpath))
            )
        candidate = avocado_var_key_resolve_shipped(
            rootfs, root_dir + "/" + subpath, lead, flat, bb.fatal,
        )
        if os.path.isfile(candidate):
            shipped[os.path.basename(subpath)] = candidate

    # NOTHING from cryptsetup-var reached this image, which means different
    # things in different images: this class is inherited globally and registers
    # the check on EVERY image, while only the initramfs is required to carry
    # the unlock path. The rootfs legitimately ships the udev and posture
    # packages without it - though on Jetson it ships the full set too, via
    # packagegroup-avocado-tegra-extra, and that copy is validated here rather
    # than waved through.
    #
    # Registering per-image in the class rather than in one named image recipe
    # is what closes the hole this replaced: tier 3 lived in
    # avocado-image-initramfs.bb alone, so a machine setting its own
    # INITRAMFS_IMAGE got no image-scope gate at all.
    # avocado-grinn-astra-1680-sbc.conf already does that, and the bypass tier
    # 3 exists to catch would have reopened in full the moment it declared the
    # capability.
    if not shipped:
        if d.getVar("PN") != d.getVar("INITRAMFS_IMAGE"):
            return
        bb.fatal(
            lead + "ships no var-key.sh at %s. cryptsetup-var.sh reads "
            "/etc/avocado-security-capabilities from this initramfs, sees "
            "encrypted-var, and has nothing to derive a key with, so /var "
            "never unlocks. Either the capability does not belong on this "
            "machine, or packagegroup-avocado-initramfs is not installing "
            "cryptsetup-var."
            % flat(os.path.join(rootfs.rstrip("/"),
                                (libexecdir + "/cryptsetup-var/var-key.sh")
                                .lstrip("/")))
        )

    # Something from the package is here, so the whole required set has to be.
    # One script without the others means the directory was edited after
    # packaging: they install from a single do_install into a single package,
    # so packaging cannot produce a partial set.
    for _dirvar, subpath, required in components:
        component = os.path.basename(subpath)
        if component in shipped:
            continue
        if not required:
            continue
        bb.fatal(
            lead + "ships no %s, but does ship %s beside it. They install from "
            "one package, so an image carrying one and not the other has had "
            "its cryptsetup-var directory edited after packaging. Nothing "
            "calls the provider without cryptsetup-var.sh, and cryptsetup-var.sh "
            "has nothing to call without var-key.sh, so /var never unlocks."
            % (component, flat(", ".join(sorted(shipped))))
        )

    # Attesting the unit is not enough on its own: the same edit that repoints
    # ExecStart can instead delete the symlink that pulls the unit into the
    # initrd, which leaves every digest matching and the unit simply never
    # started. do_install stages that link by hand precisely because the preset
    # does not create it, so its absence is never legitimate here.
    enable_link = os.path.join(
        rootfs.rstrip("/"),
        (d.getVar("systemd_system_unitdir") + "/initrd-root-fs.target.wants/"
         "cryptsetup-var.service").lstrip("/"),
    )
    if not os.path.lexists(enable_link):
        bb.fatal(
            lead + "ships cryptsetup-var.service but not the %s symlink that "
            "pulls it into the initrd. cryptsetup-var.bb stages that link in "
            "do_install because the preset does not create it for a "
            "WantedBy=initrd-root-fs.target unit, so an image missing it has "
            "had the unit disabled after packaging - every digest still "
            "matches and /var is simply never unlocked."
            % flat(enable_link)
        )

    provider = shipped["var-key.sh"]

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
    # writes one per component only after the deliverability checks it CAN run
    # have run, so an absence means tier 2 did not reach this file - and the way
    # it does not reach it is by returning early on a capability this image
    # still declares. That is the recipe-datastore bypass, caught here a second
    # time and by a different signal than the status read below.
    #
    # Not "written last" - that was true while var-key.sh was the only
    # attestation, and it is not any more. cryptsetup-var.sh is attested first,
    # so a resolve_shipped fatal on IT also leaves this file absent, for a
    # different reason than the bypass. The absence is still conclusive; the
    # inference about which cause produced it is not.
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
        actual = avocado_var_key_digest(provider)
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

    # The rest of the unlock path, bound the same way. Checked here rather than
    # left to the provider's own digest because the provider is the smaller
    # target: cryptsetup-var.sh reads the capability declaration, decides
    # whether to call the provider, and decides what to do when it refuses. A
    # constant key file substituted there ships a fleet-wide /var key with
    # var-key.sh.sha256 still matching perfectly.
    #
    # Runs BEFORE the status read below. A status line is a claim by a file
    # this image has not yet been shown to have validated; asking whether the
    # bytes were validated has to come first for the claim to mean anything.
    for _dirvar, subpath, _required in components:
        component = os.path.basename(subpath)
        if component == "var-key.sh":
            continue
        if component not in shipped:
            # Absent optional component. The required ones were refused above,
            # before the provider's own attestation was read.
            continue
        component_path = shipped[component]
        if not os.path.isfile(component_path + ".sha256"):
            bb.fatal(
                lead + "ships no attestation for %s (%s). cryptsetup-var.bb "
                "writes one for every script on the unlock path, so a missing "
                "one means tier 2 did not reach this file - or that it was "
                "added to the image afterwards."
                % (component, flat(component_path))
            )
        # Reset per iteration. These are function-scoped, not loop-scoped, so
        # a future edit that made the OSError branch non-terminating would
        # compare component N against component N-1's digests - which match
        # each other, so a tampered file would read as clean. Cheaper to make
        # the stale read impossible than to rely on the fatal staying fatal.
        recorded_component = None
        actual_component = None
        try:
            with open(component_path + ".sha256", encoding="utf-8",
                      errors="replace") as f:
                recorded_component = f.read().strip()
            actual_component = avocado_var_key_digest(component_path)
        except OSError as exc:
            bb.fatal(
                lead + "could not read the %s it ships (%s) or its "
                "attestation: %s." % (component, flat(component_path),
                                      flat(exc))
            )
        if recorded_component != actual_component:
            bb.fatal(
                lead + "ships a %s (%s) whose bytes do not match the "
                "attestation beside it. The attestation records %s and the "
                "shipped file hashes to %s, so the script this image will run "
                "was replaced after it was checked. var-key.sh matching says "
                "nothing about this: the provider derives the key, this script "
                "decides whether it is ever asked to."
                % (component, flat(component_path),
                   flat(recorded_component or "<empty>"),
                   flat(actual_component))
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
