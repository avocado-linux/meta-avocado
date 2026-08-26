# Fails a build, loudly, when it requests a security feature the selected
# machine cannot deliver.
#
# The request side (DISTRO_FEATURES: encrypted-var, ahab, ftpm, tpm2) has no
# machine restriction today - kas/feature/encrypted-var.yml composes with any
# machine.yml. The delivery side is a set of per-machine facts (a raw
# AVOCADO_VAR_PART_DEV path, a MACHINE_FEATURES entry, a kernel config
# fragment, a COMPATIBLE_MACHINE opt-in list) that must happen to agree with
# what was requested, and nothing checked that they did. This class is that
# check.
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
AVOCADO_SECURITY_FEATURES ?= "encrypted-var ahab ftpm tpm2 verified-boot"

def avocado_security_capabilities_check(d):
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

# devtool-debt: kas/feature/ftpm.yml (imx93-ahab-secure-boot branch only, not
# present on this branch) still does MACHINE_FEATURES:append = " optee-ftpm"
# directly, a second place avocado-imx93-frdm's fTPM support gets asserted
# outside AVOCADO_SECURITY_CAPABILITIES. Not fixable from here: the file does
# not exist on this branch to edit. Ceiling: the duplication stands for as
# long as the two branches remain separate. Upgrade trigger: the branches
# merge, or ftpm.yml's own MACHINE_FEATURES:append is replaced with a read of
# this machine's AVOCADO_SECURITY_CAPABILITIES declaration.
