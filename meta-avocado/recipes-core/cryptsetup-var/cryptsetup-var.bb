SUMMARY = "LUKS2 /var unlock and first-boot-format script"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://cryptsetup-var.sh \
    file://var-key.sh \
    file://cryptsetup-var.service \
    file://99-zz-cryptsetup-var.rules \
    file://avocado-posture-publish.sh \
    file://avocado-posture-publish.service \
"
# Refuse a build whose machine declares encrypted-var but resolves to a
# var-key.sh that cannot actually derive a key on this machine.
#
# The gate reads AVOCADO_SECURITY_CAPABILITIES, not DISTRO_FEATURES.
# Declaring the capability is what pulls this tooling into the image, so the
# declaration IS the build-time request; DISTRO_FEATURES no longer carries an
# encrypted-var token at all, and avocado-security-capabilities.bbclass warns
# when a leftover one appears. Gating on that token would make this check
# dormant on every machine in the tree.
#
# This lives here rather than in avocado-security-capabilities.bbclass's own
# ConfigParsed handler because the fact it tests - which var-key.sh a
# FILESEXTRAPATHS-aware lookup resolves to for THIS machine - does not exist
# yet at ConfigParsed time. FILESEXTRAPATHS is a per-recipe BBPATH/FILESPATH
# construction that only settles once this recipe is being parsed; the
# ConfigParsed event fires before any recipe, including this one, has been
# parsed, so a check placed there could not call bb.utils.which against a
# resolved FILESPATH at all. Checking it here, in the one recipe that ships
# and installs var-key.sh, is the earliest point the fact is available.
# Every provider declares its own status on an anchored comment line:
#
#     # avocado-var-key-provider: usable
#     # avocado-var-key-provider: unusable
#
# The check FAILS CLOSED on anything it cannot affirmatively verify - a missing
# line, an unrecognised status, a provider that does not resolve, a file it
# cannot read. This is the direction design.md already chose ("a usable
# provider wrongly refused, loudly, rather than an unusable one wrongly
# accepted"); an earlier form treated absence-of-sentinel as "usable", so an
# empty or always-failing var-key.sh dropped into a layer passed silently and
# shipped the first-boot failure this check exists to prevent.
#
# Anchored to a comment line rather than searched as a substring: a usable
# provider whose prose happens to mention the marker - a migration note, a
# comment explaining this contract - must not be refused for talking about it.
#
# The declaration is only the first of two tiers. It is a CLAIM, and a comment
# line cannot show that a provider derives anything: a script that exits 1 on
# every path, that emits hex rather than raw bytes, or that a bad bbappend
# truncated, declares itself usable exactly as convincingly as a working one.
# check_var_key_deliverability below is the check of that claim - it runs the
# installed provider against a synthetic identity and requires 64 key bytes
# out. This tier stays because it is the cheap one: it refuses at parse time,
# before anything is fetched or compiled.
AVOCADO_VAR_KEY_MARKER = "avocado-var-key-provider:"

# Identity sources a usable provider reads, one absolute path per line, read by
# the execution tier to decide which paths its fixture must populate.
AVOCADO_VAR_KEY_IDENTITY_MARKER = "avocado-var-key-identity:"

# The synthetic hardware identity written into every declared path. Chosen to
# collide with none of the DMI placeholder strings the x86-64 provider refuses,
# so a provider that rejects it is rejecting the fixture itself rather than
# recognising a known-bad value.
AVOCADO_VAR_KEY_FIXTURE_ID = "avocado-build-time-synthetic-identity-0000000000000001"

def avocado_var_key_declarations(contents, marker):
    """Every comment line in CONTENTS declaring MARKER, as a list of values.

    Exactly one leading '#' is stripped, not all of them: lstrip("#") also
    matched an indented documentation example like '#   # <marker>: usable', so
    a provider that merely SHOWS the contract in prose was read as declaring it.
    Both tiers match a declaration rather than prose, and stripping one hash is
    what distinguishes them.
    """
    found = []
    for line in contents.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        body = stripped[1:].strip()
        if body.startswith(marker):
            found.append(body[len(marker):].strip())
    return found

python __anonymous() {
    if not bb.utils.contains(
        "AVOCADO_SECURITY_CAPABILITIES", "encrypted-var", True, False, d
    ):
        return

    machine = d.getVar("MACHINE") or "<unknown>"
    marker = d.getVar("AVOCADO_VAR_KEY_MARKER")
    lead = "machine %s declares encrypted-var but " % machine
    # The remedy states the WHOLE contract, both tiers, deliberately. Naming
    # only this tier's requirement sends an author who follows it exactly into
    # a second, differently-worded refusal one full parse-and-fetch later - the
    # defect an earlier commit already had to fix once by removing a remedy that
    # did not clear the check.
    remedy = (
        " Ship a var-key.sh for this machine carrying the comment line "
        "'# %s usable' and able to derive a device-unique key. It must also "
        "carry one '# %s <absolute path>' line per file it reads its hardware "
        "identity from, and prefix every one of those reads with the script's "
        "optional first argument, so the build-time check can derive against a "
        "synthetic identity - see README-deliverability.md. A var-hwkey.sh does "
        "not satisfy any of this on its own: per cryptsetup-var.sh it supplies "
        "the passphrase of a SECOND keyslot and leaves the var-key.sh keyslot "
        "as the recovery path, so a machine with only a hwkey backend still "
        "cannot derive that recovery key."
        % (marker, d.getVar("AVOCADO_VAR_KEY_IDENTITY_MARKER"))
    )

    # An empty FILESPATH would send bb.utils.which to the host PATH, where a
    # stray var-key.sh would be inspected as though it were the shipped one.
    filespath = d.getVar("FILESPATH")
    if not filespath:
        bb.fatal(lead + "FILESPATH is empty at parse time, so which var-key.sh ships cannot be determined." + remedy)

    provider = bb.utils.which(filespath, "var-key.sh")
    if not provider:
        bb.fatal(lead + "no var-key.sh resolves on FILESPATH at all." + remedy)

    try:
        with open(provider, encoding="utf-8", errors="replace") as f:
            contents = f.read()
    except OSError as exc:
        bb.fatal(lead + "its var-key.sh at %s could not be read: %s." % (provider, exc) + remedy)

    # Collect EVERY declaration rather than stopping at the first. First-match
    # wins turned the realistic migration - copy the shared provider, prepend a
    # usable line, forget to delete its unusable one - into a silent pass on a
    # provider that still cannot derive a key.
    declarations = avocado_var_key_declarations(contents, marker)

    if len(declarations) > 1:
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) carries %d "
            "'%s' status lines (%s); exactly one is required, so which one "
            "governs cannot be decided." % (provider, len(declarations), marker, ", ".join(declarations))
            + remedy
        )

    status = declarations[0] if declarations else None

    if status is None:
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares no "
            "'%s' status line, so it cannot be shown to derive a key." % (provider, marker) + remedy
        )
    if status == "unusable":
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares itself "
            "unusable: it is the placeholder that cannot actually derive a key." % provider + remedy
        )
    if status != "usable":
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares an "
            "unrecognised status '%s'; expected 'usable' or 'unusable'." % (provider, status) + remedy
        )
}

# Second tier: run the installed provider against two synthetic hardware
# identities and require a distinct 64-byte key from each. This is what makes
# "usable" mean something - the declaration tier above can only read a claim
# back, and a single run could only measure the key's size.
#
# It reads ${D}, not FILESPATH. The installed copy is what ships, so this closes
# the window where a bbappend's do_install:append replaces the file after the
# parse-time check has already passed on the FILESPATH source. It does NOT close
# every window: postfuncs run in the order they were appended, so a bbappend
# adding its own do_install postfunc lands behind this one and could still swap
# the file. Ordering against a bbappend is not winnable from here - a bbappend
# parses last by construction - which is why the tier is stated as closing the
# :append case rather than as making the artifact immutable.
#
# The fixture root is passed as argv 1 and every identity read in a provider is
# prefixed with it. That prefixing is load-bearing rather than tidiness: an
# unprefixed /sys/class/dmi/id/product_uuid read would be satisfied by the BUILD
# HOST's own DMI, and the provider would pass without the fixture having been
# consulted at all - the check would then be measuring the build machine. The
# two-identity assertion at the end is what detects that, since a read that
# never consulted the fixture returns the same key both times.
#
# argv rather than an environment variable, deliberately, and the reason is
# sharper than ambient-inheritance hygiene. An env var would have been reachable
# from the kernel command line via systemd.setenv= on a device without verified
# boot; on a FIRST-ENROLMENT boot that redirects the identity before luksFormat
# runs, so the volume is created under an attacker-chosen key - a permanent
# compromise rather than a failed unlock. An argument has to be passed by the
# caller, and cryptsetup-var.sh passes none.
#
# What this does NOT establish, in order of how likely each is to bite:
#   - That the identity is readable on the real device at initramfs time. That
#     is a property of the target's kernel config and boot path, not of the
#     script, and no build-time check can reach it.
#   - That the DEVICE's openssl behaves like the build host's. The derivation
#     here runs against openssl-native; the device runs target openssl-bin, and
#     `openssl kdf ARGON2ID` needs 3.2 or newer. A layer that pins the target
#     older than the native passes here and fails at first boot.
#   - That any provider branch other than the declared one works. Only the
#     declared identity paths are populated, so a fallback leg is not exercised.
# See README-deliverability.md, "The var-key provider contract", for the full
# statement of both tiers.
#
# devtool-debt: the validating shell is whatever HOSTTOOLS resolves `sh` to
# (bash on Arch, dash on Debian), not the target's initramfs shell, and it is
# not part of the task hash. Ceiling: providers that stay plain POSIX sh, where
# the three shells agree. Upgrade trigger: a provider grows a construct whose
# behaviour differs across sh implementations, or a refusal is traced to the
# build host's shell rather than to the provider.
#
# devtool-debt: runs under do_install, so sstate skips it - a machine restored
# from cache never re-runs the check, and on a shared sstate cluster it is
# enforced only on whichever builder populated the cache. Ceiling: the script
# content, the capability declaration and openssl-native are all in the task
# hash, so a change to any of them does re-run it. Upgrade trigger: a provider
# regression reaches a device having been masked by an sstate hit.
python avocado_var_key_check_deliverability() {
    if not bb.utils.contains(
        "AVOCADO_SECURITY_CAPABILITIES", "encrypted-var", True, False, d
    ):
        return

    import os
    import shutil
    import subprocess

    machine = d.getVar("MACHINE") or "<unknown>"
    marker = d.getVar("AVOCADO_VAR_KEY_IDENTITY_MARKER")
    installed = os.path.join(
        d.getVar("D") + d.getVar("libexecdir"), "cryptsetup-var", "var-key.sh"
    )
    lead = "machine %s declares encrypted-var but " % machine

    # bakar streams bitbake's log through a Rich handler with markup enabled,
    # which parses a bracketed span as a style tag and silently drops it. EVERY
    # value interpolated below is flattened, not just the provider's stderr: a
    # WORKDIR or a declared path carrying a bracket would otherwise reach the
    # terminal blank, which is the same failure the stderr flattening was added
    # for.
    def flat(text):
        return str(text).replace("[", "(").replace("]", ")")

    if not marker:
        bb.fatal(
            "AVOCADO_VAR_KEY_IDENTITY_MARKER is empty or unset, so every comment "
            "line in a provider would match as an identity declaration. It is set "
            "by cryptsetup-var.bb and is not an opt-out switch."
        )

    if not os.path.isfile(installed):
        bb.fatal(lead + "no var-key.sh was installed at %s." % flat(installed))

    try:
        with open(installed, encoding="utf-8", errors="replace") as f:
            contents = f.read()
    except OSError as exc:
        bb.fatal(
            lead + "its installed var-key.sh at %s could not be read: %s."
            % (flat(installed), flat(exc))
        )

    identities = avocado_var_key_declarations(contents, marker)
    if not identities:
        bb.fatal(
            lead + "its installed var-key.sh (%s) declares no '%s' line, so the "
            "paths to populate for a build-time derivation cannot be determined. "
            "Add one '# %s <absolute path>' line per file the provider reads its "
            "hardware identity from, and prefix every one of those reads in the "
            "script with its optional first argument."
            % (flat(installed), marker, marker)
        )

    relative = []
    for declared in identities:
        if not declared.startswith("/") or "\0" in declared:
            bb.fatal(
                lead + "its installed var-key.sh (%s) declares the identity path "
                "'%s'; a declared path must be absolute and free of NUL."
                % (flat(installed), flat(declared))
            )
        relative.append(declared.lstrip("/"))

    def populate(root, value):
        # rmtree REFUSES a symlink and ignore_errors=True hides the refusal, so
        # a symlink left at this path would survive and every write below would
        # land wherever it points - while the lexical guard further down still
        # reported the target as inside the fixture.
        if os.path.islink(root) or os.path.isfile(root):
            os.unlink(root)
        else:
            shutil.rmtree(root, ignore_errors=True)
        for declared, rel in zip(identities, relative):
            target = os.path.normpath(os.path.join(root, rel))
            # A declaration containing .. would otherwise be written outside
            # WORKDIR, into whatever the traversal resolves to.
            if not target.startswith(root + os.sep):
                bb.fatal(
                    lead + "its installed var-key.sh (%s) declares an identity "
                    "path '%s' that escapes the fixture root."
                    % (flat(installed), flat(declared))
                )
            try:
                bb.utils.mkdirhier(os.path.dirname(target))
                with open(target, "w", encoding="utf-8") as f:
                    f.write(value)
            except OSError as exc:
                bb.fatal(
                    lead + "its installed var-key.sh (%s) declares an identity "
                    "path '%s' the fixture could not create: %s. Two declared "
                    "paths where one is a parent directory of the other do this."
                    % (flat(installed), flat(declared), flat(exc))
                )

    def derive(root):
        try:
            proc = subprocess.run(
                ["sh", installed, root],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            bb.fatal(
                lead + "its installed var-key.sh (%s) could not be run against "
                "the synthetic identity fixture: %s."
                % (flat(installed), flat(exc))
            )
        stderr = flat(proc.stderr.decode("utf-8", "replace").strip()) or "(none)"
        if proc.returncode != 0:
            bb.fatal(
                lead + "its installed var-key.sh (%s) exited %d when run against "
                "a synthetic identity at the paths it declares (%s). A provider "
                "that cannot derive a key from its own declared identity sources "
                "cannot derive one on the device either. Provider stderr: %s"
                % (
                    flat(installed),
                    proc.returncode,
                    flat(", ".join(identities)),
                    stderr,
                )
            )
        if len(proc.stdout) != 64:
            bb.fatal(
                lead + "its installed var-key.sh (%s) emitted %d bytes, not the "
                "64 raw key bytes cryptsetup-var.sh reads from its stdout. "
                "Provider stderr: %s"
                % (flat(installed), len(proc.stdout), stderr)
            )
        return proc.stdout

    # TWO derivations from two DIFFERENT synthetic identities, because a length
    # check alone cannot tell a device-unique derivation from a constant.
    #
    # This is the assertion that makes the tier worth its cost. A provider that
    # emits a hardcoded 64 bytes passes a size check; so does one whose identity
    # read is missing its ROOT prefix and therefore resolves against the build
    # host's own /sys, never reading the fixture at all. Both produce the SAME
    # key twice, and both are the fleet-wide-identical-key failure every
    # provider's comment says it exists to prevent. Neither is detectable from
    # one run.
    base = d.getVar("WORKDIR")
    first = os.path.join(base, "var-key-deliverability-fixture-a")
    second = os.path.join(base, "var-key-deliverability-fixture-b")

    populate(first, "avocado-synthetic-identity-aaaa00000000000000000001")
    key_a = derive(first)
    populate(second, "avocado-synthetic-identity-bbbb00000000000000000002")
    key_b = derive(second)

    if key_a == key_b:
        bb.fatal(
            lead + "its installed var-key.sh (%s) derived the SAME key from two "
            "different synthetic identities, so it is not deriving from the "
            "identity sources it declares (%s). Either it emits a constant, or "
            "one of those reads is not prefixed with the script's first argument "
            "and resolved against the build host instead of the fixture. Every "
            "device in the fleet would unlock with one key."
            % (flat(installed), flat(", ".join(identities)))
        )
}
do_install[postfuncs] += "avocado_var_key_check_deliverability"

# MACHINE is read only to name the machine in a diagnostic, but a getVar inside
# a postfunc enters do_install's signature. Left in, it would split do_install
# sstate across every machine that shares one provider and installs byte
# identical content - the six Jetson machines on meta-avocado-nvidia's.
do_install[vardepsexclude] += "MACHINE"

# Tools cryptsetup-var.sh + var-key.sh invoke in the (minimal) initramfs:
#   cryptsetup    - luksFormat / open / resize
#   openssl-bin   - var-key.sh derives the phase-1 key via `openssl kdf ARGON2ID`
#                   (libcrypto is already present via systemd; this adds the CLI)
#   btrfs-tools   - mkfs.btrfs on first boot (the filesystem is grown at mount
#                   time via x-systemd.growfs, not here)
#   gawk          - awk in the cpuinfo-serial lookup and the dm resize check
#   sed           - strips the `openssl dgst` prefix when deriving the salt
#   libdevmapper  - provides dmsetup, used by maybe_resize's data-offset
#                   query. Not actually in the initramfs otherwise: nothing
#                   else RDEPENDS on it, unlike blockdev/blkid (util-linux)
#                   and systemd-cryptenroll (systemd), which genuinely are
#                   already there via packagegroup-avocado-initramfs.
#                   The package is libdevmapper, NOT device-mapper: dmsetup
#                   ships in meta-oe lvm2's own `PACKAGES =+ "libdevmapper"`
#                   split (FILES:libdevmapper carries ${sbindir}/dmsetup).
#                   `device-mapper` is what other distros call it and nothing
#                   in this layer set RPROVIDES that name, so asking for it
#                   fails dependency resolution rather than pulling in dmsetup.
# (blockdev, blkid, systemd-cryptenroll, mktemp, dirname, tr, cut are already
#  in the avocado initramfs.)
RDEPENDS:${PN} = "cryptsetup openssl-bin btrfs-tools gawk sed libdevmapper"

# openssl-native puts the openssl CLI the providers derive with on the task
# PATH. HOSTTOOLS does not whitelist openssl, so without this the build-time
# deliverability check would fail every provider for want of a binary rather
# than for any property of the provider itself.
#
# Gated on the capability for the same reason the check is: a machine that never
# runs the check should not carry a native openssl build in its graph. `+=`
# rather than `=` so an inherit or bbappend adding its own DEPENDS is not
# silently dropped depending on where it lands in the parse order.
DEPENDS += "${@bb.utils.contains('AVOCADO_SECURITY_CAPABILITIES', 'encrypted-var', 'openssl-native', '', d)}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "cryptsetup-var.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${libexecdir}/cryptsetup-var
    install -m 0750 ${UNPACKDIR}/cryptsetup-var.sh ${D}${libexecdir}/cryptsetup-var/
    install -m 0750 ${UNPACKDIR}/var-key.sh ${D}${libexecdir}/cryptsetup-var/
    # Optional hardware key backend, added to SRC_URI by a vendor bbappend for
    # machines with a key-wrapping engine (see var-hwkey.sh's contract in
    # cryptsetup-var.sh). Absent on machines without one.
    if [ -e ${UNPACKDIR}/var-hwkey.sh ]; then
        install -m 0750 ${UNPACKDIR}/var-hwkey.sh ${D}${libexecdir}/cryptsetup-var/
    fi

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/cryptsetup-var.service ${D}${systemd_system_unitdir}/

    # Statically enable the unit for the initrd. SYSTEMD_AUTO_ENABLE relies on
    # the preset being applied at image time, but the initramfs rootfs build
    # does not enable a WantedBy=initrd-root-fs.target unit there, so the
    # .wants symlink is never created and /var unlock never runs (boot drops to
    # emergency mode). Stage the symlink by hand so the service is pulled into
    # the initrd regardless of preset handling.
    install -d ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants
    ln -sf ../cryptsetup-var.service \
        ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants/cryptsetup-var.service

    # udev rule that re-creates /dev/mapper/var in the real root (the device is
    # opened in the initrd; see the rule for why the rootfs coldplug otherwise
    # drops it). Shipped in its own package so it can be installed into the
    # rootfs - the rest of cryptsetup-var is initramfs-only.
    install -d ${D}${nonarch_base_libdir}/udev/rules.d
    install -m 0644 ${UNPACKDIR}/99-zz-cryptsetup-var.rules \
        ${D}${nonarch_base_libdir}/udev/rules.d/99-zz-cryptsetup-var.rules

    # Posture publisher: reads what cryptsetup-var.sh left in /run and puts it in
    # the U-Boot KV store, which is what peridiod already reads.
    install -m 0750 ${UNPACKDIR}/avocado-posture-publish.sh \
        ${D}${libexecdir}/cryptsetup-var/
    install -m 0644 ${UNPACKDIR}/avocado-posture-publish.service \
        ${D}${systemd_system_unitdir}/
}

PACKAGES =+ "${PN}-udev ${PN}-posture"
FILES:${PN}-udev = "${nonarch_base_libdir}/udev/rules.d/99-zz-cryptsetup-var.rules"

# Posture publishing is rootfs-only, so it gets its own package rather than
# riding along in ${PN} and being pulled into the initrd - it reads what the
# initramfs recorded, it does not run there.
#
# The split relies on PACKAGES order, which is load-bearing here: FILES:${PN}
# below globs the whole ${libexecdir}/cryptsetup-var/ directory and so also
# matches this script, and the first package in PACKAGES to match a file claims
# it. `PACKAGES =+` prepends, putting ${PN}-posture ahead of ${PN}, so the script
# lands here rather than in the initramfs package. Switching that to `=.` or
# appending instead would silently pull the publisher into the initrd.
#
# libubootenv supplies fw_printenv/fw_setenv and util-linux-findmnt supplies
# findmnt. Both are RDEPENDS rather than optional probes because a posture
# reporter that silently cannot read posture is worse than one that fails to
# install; the script still degrades cleanly if the fw_env.config a given
# machine needs was never generated.
FILES:${PN}-posture = " \
    ${libexecdir}/cryptsetup-var/avocado-posture-publish.sh \
    ${systemd_system_unitdir}/avocado-posture-publish.service \
"
RDEPENDS:${PN}-posture = "libubootenv util-linux-findmnt"
# SYSTEMD_PACKAGES defaults to ${PN} alone; without listing the subpackage the
# SYSTEMD_SERVICE/AUTO_ENABLE lines below are ignored and no preset is generated,
# so the unit shipped "disabled; preset: disabled" and never published.
SYSTEMD_PACKAGES += "${PN}-posture"
SYSTEMD_SERVICE:${PN}-posture = "avocado-posture-publish.service"
SYSTEMD_AUTO_ENABLE:${PN}-posture = "enable"

FILES:${PN} += "${libexecdir}/cryptsetup-var/"
FILES:${PN} += "${systemd_system_unitdir}/cryptsetup-var.service"
FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/cryptsetup-var.service"
