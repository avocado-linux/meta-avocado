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
#     # avocado-var-key-provider: test-only
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
# avocado_var_key_check_deliverability below is the check of that claim - it runs the
# installed provider against a synthetic identity and requires 64 key bytes
# out. This tier stays because it is the cheap one: it refuses at parse time,
# before anything is fetched or compiled.
# The token itself lives in avocado-security-capabilities.bbclass, which
# both this recipe and the image tier read. Published as a variable here
# for readers and for anything that greps for it; the checks call the
# function, so the two tiers cannot scan for different strings.
AVOCADO_VAR_KEY_MARKER = "${@avocado_var_key_marker()}"

# Machines permitted to resolve to a provider declared test-only, which waives
# the requirement to refuse when no hardware identity is readable. Kept here,
# in meta-avocado, rather than being inferred from the provider: the layer
# shipping a provider must not be able to grant itself the waiver. Only virtual
# targets belong on this list, because only they have no identity to read.
#
# Published for readers, and NOT read by the check. The permitted set is a
# literal inside the parse tier below - the `python __anonymous` block, not the
# do_install postfunc - because a
# BitBake variable is the wrong container for a security allow-list: conf files
# parse before recipes, so `?=` here would be a no-op against any machine conf
# or local.conf that set the variable first, and even `=` is reachable from a
# bbappend. Either way the vendor decides which machines may waive the refusal
# check, which is exactly what the split exists to prevent. Keep this in step
# with the literal; the check refuses on the literal regardless of what this
# says.
AVOCADO_VAR_KEY_TEST_ONLY_MACHINES = "avocado-qemux86-64 avocado-qemuarm64"

# Identity sources a usable provider reads, one absolute path per line, read by
# the execution tier to decide which paths its fixture must populate.
AVOCADO_VAR_KEY_IDENTITY_MARKER = "avocado-var-key-identity:"

# avocado_var_key_flat() and avocado_var_key_declarations() are defined in
# avocado-security-capabilities.bbclass, which is inherited globally by
# conf/distro/include/avocado-security.inc. They moved there when the
# image-scope gate became a second reader of the same declarations - one
# parser, so the two readers cannot disagree about what a declaration means.

python __anonymous() {
    if not bb.utils.contains(
        "AVOCADO_SECURITY_CAPABILITIES", "encrypted-var", True, False, d
    ):
        return

    flat = avocado_var_key_flat
    machine = d.getVar("MACHINE") or "<unknown>"
    marker = d.getVar("AVOCADO_VAR_KEY_MARKER")
    if not marker:
        bb.fatal(
            "AVOCADO_VAR_KEY_MARKER is empty or unset, so every comment line in "
            "a provider would match as a status declaration. It is set by "
            "cryptsetup-var.bb and is not an opt-out switch."
        )
    lead = "machine %s declares encrypted-var but " % flat(machine)
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

    # An empty FILESPATH splits into [""], so bb.utils.which would stat
    # var-key.sh relative to the task's working directory - a file that is not
    # the shipped provider, inspected as though it were.
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
        bb.fatal(
            lead + "its var-key.sh at %s could not be read: %s."
            % (flat(provider), flat(exc)) + remedy
        )

    # Collect EVERY declaration rather than stopping at the first. First-match
    # wins turned the realistic migration - copy the shared provider, prepend a
    # usable line, forget to delete its unusable one - into a silent pass on a
    # provider that still cannot derive a key.
    declarations, _prose = avocado_var_key_declarations(contents, marker)

    if len(declarations) > 1:
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) carries %d "
            "'%s' status lines (%s); exactly one is required, so which one "
            "governs cannot be decided."
            % (
                flat(provider),
                len(declarations),
                marker,
                flat(", ".join(declarations)),
            )
            + remedy
        )

    status = declarations[0] if declarations else None

    if status is None:
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares no "
            "'%s' status line, so it cannot be shown to derive a key." % (flat(provider), marker) + remedy
        )
    if status == "unusable":
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares itself "
            "unusable: it is the placeholder that cannot actually derive a key." % flat(provider) + remedy
        )
    if status not in ("usable", "test-only"):
        bb.fatal(
            lead + "the var-key.sh that resolves for it (%s) declares an "
            "unrecognised status '%s'; expected 'usable', 'test-only' or "
            "'unusable'." % (flat(provider), flat(status)) + remedy
        )

    # test-only exempts a provider from the execution tier's refusal check, so
    # it is the one fail-open path in a system whose every other tier fails
    # closed. It is therefore NOT self-asserted: the provider asks for the
    # exemption, and this list, which lives in meta-avocado rather than in the
    # vendor layer shipping the provider, decides whether the machine may have
    # it.
    #
    # Without that split the exemption is unlocked by editing one comment line
    # in a file the vendor already owns. A provider whose identity read falls
    # back to a constant fails the refusal check, and the one-word edit turns
    # that failure into a warning among the thousands an image build emits -
    # shipping a fleet whose every board opens with the same /var key while the
    # capability declaration still says encrypted-var.
    if status == "test-only":
        # Shared with the image-scope gate in
        # avocado-security-capabilities.bbclass, which decides the same waiver
        # over the provider that actually shipped. Two copies that disagree
        # would be worse than either.
        allowed = avocado_var_key_test_only_machines()
        if machine not in allowed:
            bb.fatal(
                lead + "the var-key.sh that resolves for it (%s) declares "
                "itself test-only, which waives the requirement to refuse when "
                "no hardware identity is readable - meaning every device built "
                "from this image derives the SAME /var key. That is permitted "
                "only for machines listed in AVOCADO_VAR_KEY_TEST_ONLY_MACHINES "
                "(currently: %s), which is set in meta-avocado and is not for a "
                "vendor layer to extend in order to pass this check. A machine "
                "that ships to hardware needs a provider that refuses."
                % (flat(provider), ", ".join(allowed))
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
#   - That a provider behaves the same when it is NOT being tested. The check
#     runs it as `sh var-key.sh <fixture-root>` while the device runs it with no
#     argument, so the artifact under test can see it is under test. A provider
#     written to derive properly whenever argv 1 is set, and to emit a constant
#     when it is empty, passes every assertion here and ships a fleet-wide key.
#     This bounds the whole tier: it catches mistakes and careless providers,
#     not a provider written to evade it. That is a real gap and not a
#     theoretical one, and it is the reason the waiver above is gated on a list
#     this recipe owns rather than on anything a provider says about itself.
#
# devtool-debt: the fixture is delivered as an argument, so the provider can
# detect the test. Ceiling: providers written in good faith, where the argument
# is a convenience rather than a signal to behave differently. Upgrade trigger:
# a provider is found branching on argv 1 for anything other than path
# prefixing, or a third party outside this tree starts supplying providers. The
# fix is to run the provider through its real no-argument interface with the
# synthetic identities mounted at their true absolute paths - the tree already
# has that shape in scripts/test-security-capability-guards.sh's `in_ns`, which
# runs a shipped script unmodified under `unshare -rm`; it was not used here
# because a nested user namespace under do_install's pseudo is fragile and
# cannot see ${D}.
#
# devtool-debt: provider output is bounded on READ, not on WRITE. Ceiling: a
# provider that terminates and does not deliberately flood; the 30s timeout
# plus the read caps hold there. Upgrade trigger: a build is seen filling its
# temporary filesystem from this check, or a provider is found backgrounding a
# writer that outlives the timeout. The fix is an RLIMIT_FSIZE on the child and
# killing the whole process group rather than the direct child.
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
    import re
    import shutil
    import subprocess
    import tempfile
    import types

    machine = d.getVar("MACHINE") or "<unknown>"
    marker = d.getVar("AVOCADO_VAR_KEY_IDENTITY_MARKER")
    installed = os.path.join(
        d.getVar("D") + d.getVar("libexecdir"), "cryptsetup-var", "var-key.sh"
    )
    lead = "machine %s declares encrypted-var but " % avocado_var_key_flat(machine)

    # Every provider-derived value interpolated below is flattened - paths,
    # statuses, declared identity paths and the provider's own stderr - because
    # bakar's Rich log handler parses a bracketed span as a style tag and drops
    # it, so a bracket in any of them would reach the terminal blank. `machine`
    # is flattened at `lead` where it enters.
    flat = avocado_var_key_flat

    status_marker = d.getVar("AVOCADO_VAR_KEY_MARKER")
    if not marker or not status_marker:
        bb.fatal(
            "AVOCADO_VAR_KEY_IDENTITY_MARKER or AVOCADO_VAR_KEY_MARKER is empty "
            "or unset, so every comment line in a provider would match as a "
            "declaration. Both are set by cryptsetup-var.bb and neither is an "
            "opt-out switch."
        )

    # A symlink is not the artifact. os.path.isfile() and open() both FOLLOW
    # one, so a link installed here resolves against the BUILD HOST while the
    # same link resolves inside the image at boot - the check reads one file
    # and the device runs another.
    #
    # Resolved and bounded, not islink() on the leaf: a do_install:append that
    # replaces the cryptsetup-var DIRECTORY with a link leaves the leaf a
    # regular file, so a leaf-only guard reads straight through it and the
    # attestation written beside it lands in the same redirected directory.
    # Shared with the image tier, which had the identical gap - one helper, so
    # a future component check cannot be added to only one of them.
    avocado_var_key_resolve_shipped(
        d.getVar("D"), d.getVar("libexecdir") + "/cryptsetup-var/var-key.sh",
        lead, flat, bb.fatal,
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

    identities, identity_prose = avocado_var_key_declarations(contents, marker)

    # An identity line the parser could not read as a declaration is FATAL here,
    # where the same shape is merely dropped for the status marker. Losing one
    # of several identity paths is silent and dangerous: the fixture is built a
    # path short, the provider falls through to one that IS populated, two
    # different keys still come out, and the build passes while the unreadable
    # path's read went to the build host. Refusing costs an author one comment
    # edit; accepting costs a fleet its /var key.
    if identity_prose:
        bb.fatal(
            lead + "its installed var-key.sh (%s) carries %d '%s' line(s) whose "
            "value is not a single path: %s. An identity declaration names one "
            "absolute path and nothing else - move any annotation to its own "
            "comment line, because a line this check cannot read is a path its "
            "fixture would not populate."
            % (flat(installed), len(identity_prose), marker,
               flat("; ".join(identity_prose)))
        )

    if not identities:
        bb.fatal(
            lead + "its installed var-key.sh (%s) declares no '%s' line, so the "
            "paths to populate for a build-time derivation cannot be determined. "
            "Add one '# %s <absolute path>' line per file the provider reads its "
            "hardware identity from, and prefix every one of those reads in the "
            "script with its optional first argument."
            % (flat(installed), marker, marker)
        )

    # The status decides whether the negative control below applies. Read from
    # the INSTALLED file rather than carried over from the parse tier, which
    # judged the FILESPATH source: the two can differ, and this tier exists
    # precisely because they can.
    statuses, _status_prose = avocado_var_key_declarations(
        contents, status_marker
    )
    status = statuses[0] if len(statuses) == 1 else None
    if status is None:
        bb.fatal(
            lead + "its installed var-key.sh (%s) carries %d status lines; "
            "exactly one is required, and the parse-time check passed, so the "
            "installed copy differs from the one on FILESPATH."
            % (flat(installed), len(statuses))
        )
    # Membership, not just cardinality. Without this an installed copy declaring
    # `unusable` - the status the parse tier refuses outright - reaches the
    # negative control below and can pass it, so the two tiers would disagree
    # about what `unusable` means.
    if status not in ("usable", "test-only"):
        bb.fatal(
            lead + "its installed var-key.sh (%s) declares the status '%s', "
            "which the parse-time check would have refused. The installed copy "
            "differs from the one on FILESPATH."
            % (flat(installed), flat(status))
        )

    # The EXEMPTION is not taken from the installed copy alone. Every behavioural
    # check below deliberately judges ${D}, because that is what ships and a
    # do_install:append can replace it after parse. For a waiver the same
    # property runs the other way: the installed copy is the LESS trustworthy
    # artifact, so letting it declare itself test-only would hand a bbappend the
    # one fail-open path in this system. A `sed -i` over ${D} in a
    # do_install:append body runs before this postfunc, keeps the count at one,
    # and would otherwise skip the refusal check on a provider that passed parse
    # as `usable`. Both copies have to agree.
    source_status = None
    filespath = d.getVar("FILESPATH")
    source = bb.utils.which(filespath, "var-key.sh") if filespath else None
    if source:
        try:
            with open(source, encoding="utf-8", errors="replace") as f:
                source_statuses, _ = avocado_var_key_declarations(
                    f.read(), status_marker
                )
            if len(source_statuses) == 1:
                source_status = source_statuses[0]
        except OSError:
            source_status = None

    if status == "test-only" and source_status != "test-only":
        bb.fatal(
            lead + "its INSTALLED var-key.sh (%s) declares itself test-only "
            "while the provider on FILESPATH (%s) declares '%s'. The test-only "
            "waiver skips the requirement to refuse when no identity is "
            "readable, so it is honoured only when both copies agree; a "
            "do_install:append that rewrites the status in ${D} is exactly what "
            "this refuses."
            % (flat(installed), flat(source or "<unresolved>"),
               flat(source_status or "<none>"))
        )

    # Duplicates are refused, not deduped. A repeated identity line is the
    # copy-a-provider-and-forget-to-delete-a-line migration the status tier is
    # already hardened against, and silently collapsing it would hide that the
    # provider was edited carelessly. It also breaks the rewrite below.
    if len(set(identities)) != len(identities):
        seen = set()
        dupes = sorted({i for i in identities if i in seen or seen.add(i)})
        bb.fatal(
            lead + "its installed var-key.sh (%s) declares the same identity "
            "path more than once (%s). Each file the provider reads gets "
            "exactly one declaration."
            % (flat(installed), flat(", ".join(dupes)))
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

    def reset(root):
        # rmtree REFUSES a symlink and ignore_errors=True hides the refusal, so
        # a symlink left at this path would survive and every write below would
        # land wherever it points - while the lexical guard further down still
        # reported the target as inside the fixture.
        # Not just isfile: a FIFO, socket or device node left here is neither a
        # symlink nor a regular file, so it took the rmtree branch, where
        # ignore_errors swallowed the NotADirectoryError and the node survived -
        # surfacing later as a parent-directory diagnosis unrelated to the real
        # state.
        if os.path.islink(root) or (
            os.path.exists(root) and not os.path.isdir(root)
        ):
            os.unlink(root)
        else:
            shutil.rmtree(root, ignore_errors=True)
        bb.utils.mkdirhier(root)

    def fixture_path(root, index):
        target = os.path.normpath(os.path.join(root, relative[index]))
        # A declaration containing .. would otherwise be written outside
        # WORKDIR, into whatever the traversal resolves to.
        if not target.startswith(root + os.sep):
            bb.fatal(
                lead + "its installed var-key.sh (%s) declares an identity "
                "path '%s' that escapes the fixture root."
                % (flat(installed), flat(identities[index]))
            )
        return target

    def populate(root, index, value):
        """Reset ROOT and write VALUE at the single declared path INDEX.

        One path at a time, not all of them at once. Populating every declared
        path together was the hole: a provider whose SECONDARY read is missing
        its ROOT prefix is shadowed by a primary that resolves, so the broken
        read is never walked and the differential is satisfied entirely by the
        good path. Leaving one declared path as the only source of an identity
        forces each read to be exercised on its own.
        """
        reset(root)
        target = fixture_path(root, index)
        try:
            bb.utils.mkdirhier(os.path.dirname(target))
            with open(target, "w", encoding="utf-8") as f:
                f.write(value)
        except OSError as exc:
            bb.fatal(
                lead + "its installed var-key.sh (%s) declares an identity "
                "path '%s' the fixture could not create: %s."
                % (flat(installed), flat(identities[index]), flat(exc))
            )

    # Output is captured through bounded temporary files rather than pipes.
    # `timeout` caps elapsed time, not volume, so a provider looping on `yes`
    # or dumping a large file writes as much as it can inside the window while
    # subprocess accumulates all of it in the worker's memory - and the 64-byte
    # check that would have rejected it only runs after that read completes.
    # The validator could be taken down by the artifact it is validating. The
    # caps are far above any legitimate output (64 key bytes, a few lines of
    # diagnostics) and exist only to bound the pathological case.
    _STDOUT_CAP = 4096
    _STDERR_CAP = 16384

    def run(script, argv):
        try:
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                rc = subprocess.call(
                    ["sh", script] + list(argv),
                    stdout=out,
                    stderr=err,
                    timeout=30,
                )
                out.seek(0)
                err.seek(0)
                proc = types.SimpleNamespace(
                    returncode=rc,
                    stdout=out.read(_STDOUT_CAP),
                    stderr=err.read(_STDERR_CAP),
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            bb.fatal(
                lead + "its installed var-key.sh (%s) could not be run against "
                "the synthetic identity fixture: %s."
                % (flat(installed), flat(exc))
            )
        return proc

    # Both paths, not just the installed one. The spec requires the diagnostic
    # to name the RESOLVED provider, and an operator who has only the ${D} path
    # cannot tell which layer or bbappend to correct - least of all in the case
    # this tier exists for, where the installed copy is not what FILESPATH
    # resolved.
    where = "installed %s, resolved from %s" % (
        flat(installed), flat(source or "<unresolved on FILESPATH>")
    )

    def derive(script, argv, context):
        proc = run(script, argv)
        stderr = flat(proc.stderr.decode("utf-8", "replace").strip()) or "(none)"
        if proc.returncode != 0:
            bb.fatal(
                lead + "its var-key.sh (%s) exited %d when run against "
                "%s. A provider that cannot derive a key from its own declared "
                "identity sources cannot derive one on the device either. "
                "Provider stderr: %s"
                % (where, proc.returncode, context, stderr)
            )
        if len(proc.stdout) != 64:
            bb.fatal(
                lead + "its var-key.sh (%s) emitted %d bytes, not the "
                "64 raw key bytes cryptsetup-var.sh reads from its stdout, when "
                "run against %s. Provider stderr: %s"
                % (where, len(proc.stdout), context, stderr)
            )
        return proc.stdout

    # Both values must collide with NO placeholder string any provider
    # refuses, or a good provider is rejected for a property of this check
    # rather than of itself. The x86-64 provider's is_placeholder() is the
    # strictest today: a named lowercase list, plus a degenerate rule matching
    # anything made only of zeros, or only of ones, once dashes and whitespace
    # are discounted. Check both literals
    # against it before editing either, or before widening that rule.
    #
    # A recipe variable used to hold this and was read by nothing after the
    # two-identity assertion replaced the single fixture, so the invariant
    # above was documented in one place and enforced in neither. Literals with
    # the rule beside them beat a variable nothing consults.
    _VALUE_A = "avocado-synthetic-identity-aaaa00000000000000000001"
    _VALUE_B = "avocado-synthetic-identity-bbbb00000000000000000002"

    base = d.getVar("WORKDIR")

    # PER DECLARED PATH: populate it alone under two different values and
    # require the derived key to change.
    #
    # Comparing keys ACROSS paths is the weaker form and does not close this.
    # An unprefixed read that RESOLVES on the build host yields key(fixture)
    # for the prefixed path and key(host) for the broken one - two different
    # keys, so a cross-path differential passes while the broken read never
    # touched the fixture. Changing one path's own value and requiring the key
    # to follow is what proves the provider read THAT path from THIS root.
    # Comment lines are excluded when looking for the path, and are still
    # rewritten. Searching the whole file made this check dead code: every
    # declared path appears in its own '# <identity marker>: <path>' line by
    # construction, so the membership test could never fail and a provider
    # assembling its path at run time passed straight through. Measured on the
    # four shipping providers, each declared path occurs at least once outside
    # a comment, so requiring that costs none of them.
    code_only = "\n".join(
        line for line in contents.splitlines()
        if not line.strip().startswith("#")
    )
    def require_literal_paths():
        for declared in identities:
            if declared not in code_only:
                bb.fatal(
                    lead + "its installed var-key.sh (%s) declares the identity "
                    "path '%s', which does not appear literally in the script. "
                    "The check rewrites every declared path into a copy and runs "
                    "it with no argument, the way a device does; a path assembled "
                    "at run time cannot be rewritten, so such a read cannot be "
                    "shown to reach the fixture rather than the build host. Write "
                    "the path as a literal."
                    % (flat(installed), flat(declared))
                )

    def no_argv_copy(root, index):
        """A copy with every declared path rewritten into ROOT, runnable bare.

        THE DEVICE PASSES NO ARGUMENT. Every argv run hands the provider a
        fixture root, which cryptsetup-var.sh never does, so the artifact under
        test can see that it is under test: one written to derive properly
        whenever $1 is set and to emit a constant when it is empty satisfied
        every other assertion here and shipped a fleet-wide key. Rewriting the
        paths removes the signal instead of trusting its absence.
        """
        # ONE pass over the original text, longest path first.
        #
        # Sequential str.replace re-scans text it has already rewritten, so a
        # declared path that is a PREFIX of another gets the fixture root
        # spliced in twice: rewriting /sys/.../serial_number first turns the
        # /sys/.../serial_number_raw literal into <root>/sys/.../serial_number_raw,
        # and the next pass rewrites the <root> part again. The copy then reads
        # a path that does not exist, and the build is refused with a message
        # blaming the provider for a defect in this rewrite. Measured on a
        # prefix pair and on a duplicated declaration; both doubled the root.
        order = sorted(range(len(identities)), key=lambda i: -len(identities[i]))
        pattern = re.compile(
            "|".join(re.escape(identities[i]) for i in order)
        )
        target = {identities[i]: fixture_path(root, i) for i in range(len(identities))}
        text = pattern.sub(lambda m: target[m.group(0)], contents)
        # Not chmodded. run() invokes it as `sh <path>`, which needs no execute
        # bit, so setting one would only widen the mode of a file in WORKDIR
        # for no reader.
        path = os.path.join(base, "var-key-no-argv-%d.sh" % index)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            bb.fatal(
                lead + "a path-rewritten copy of its installed var-key.sh (%s) "
                "could not be written to %s: %s."
                % (flat(installed), flat(path), flat(exc))
            )
        return path

    for index, declared in enumerate(identities):
        context = "a synthetic identity at %s alone" % flat(declared)
        root_a = os.path.join(base, "var-key-fixture-%d-a" % index)
        root_b = os.path.join(base, "var-key-fixture-%d-b" % index)

        populate(root_a, index, _VALUE_A)
        key_a = derive(installed, [root_a], context)

        # The SAME identity must yield the SAME key, settled BEFORE the
        # no-argument comparison below. That comparison asks whether two
        # invocations agree, which is meaningless for a provider whose two
        # invocations never agree - a provider mixing in a timestamp, $RANDOM or
        # an openssl-generated salt would otherwise be reported as an argv
        # evader, naming the wrong defect entirely. On a device this is worse
        # than a constant key: first boot formats /var with one key and every
        # later boot derives another, so the volume never opens again. Once, on
        # the first path: reproducibility is a property of the provider, not of
        # a path.
        if index == 0:
            again = derive(installed, [root_a], context + ", a second time")
            if key_a != again:
                bb.fatal(
                    lead + "its installed var-key.sh (%s) derived two DIFFERENT "
                    "keys from the same synthetic identity, so its derivation is "
                    "not reproducible. A device would format /var with one key on "
                    "first boot and fail to unlock with another on the next. "
                    "Remove whatever varies between runs - a timestamp, a random "
                    "salt, an unseeded value - and derive only from the declared "
                    "identity sources (%s)."
                    % (flat(installed), flat(", ".join(identities)))
                )

        populate(root_b, index, _VALUE_B)
        key_b = derive(installed, [root_b], context)

        if key_a == key_b:
            bb.fatal(
                lead + "its installed var-key.sh (%s) derived the SAME key from "
                "two DIFFERENT identities at its declared path '%s', so that "
                "read is not reaching the fixture. Either the provider emits a "
                "constant, or that read is not prefixed with the script's "
                "optional first argument and resolved against the build host "
                "instead. Every device in the fleet would unlock with one key."
                % (flat(installed), flat(declared))
            )

        # The no-argument run happens PER PATH, not once for the first.
        #
        # Running it only against the first path proved the property for the
        # primary and nothing else: the primary resolves, short-circuits, and
        # every fallback branch stays unwalked in the one no-argv run. A
        # provider that handles its secondary source correctly with $1 set and
        # emits a constant without it passed every per-path argv check and the
        # single no-argv check, and then gave one key to every device whose
        # primary identity is missing - which is the population that depends on
        # the fallback in the first place.
        # Called HERE and not hoisted above the loop, though it reads only
        # loop-invariant data. Hoisting makes it pre-empt the per-path
        # differential, so a provider that emits a constant - and therefore
        # never mentions its declared path in code - is refused for not
        # writing the path literally rather than for emitting a constant.
        # Both refuse; only one names the defect. Measured: hoisting turns
        # four tier-test cases red on the wrong branch.
        require_literal_paths()
        unargued = derive(
            no_argv_copy(root_a, index),
            [],
            "%s, through a path-rewritten copy invoked with no argument" % context,
        )
        if unargued != key_a:
            bb.fatal(
                lead + "its installed var-key.sh (%s) derived a DIFFERENT key "
                "when invoked with no argument against the identity at '%s', "
                "reached through its declared paths rewritten into the fixture. "
                "The device invokes it with no argument, so the key this check "
                "verified is not the key the device would derive. A provider "
                "must behave the same whether its optional first argument is "
                "present or absent - branch on nothing but the identity it "
                "reads." % (flat(installed), flat(declared))
            )

    # NEGATIVE CONTROL: with no identity present at all, a provider must REFUSE
    # rather than substitute a constant.
    #
    # The differential above proves the provider reads its declared sources. It
    # says nothing about what the provider does when those sources are missing
    # on a real device, which is the case that produces a fleet-wide key: a
    # fallback to a fixed string derives a perfectly good-looking 64 bytes that
    # every board in the fleet shares. Only running against an empty root
    # separates "derives from the identity" from "derives something regardless".
    #
    # This is the check `test-only` exists to be exempt from. A provider carrying
    # that status is declaring that it CANNOT refuse - the qemu one substitutes
    # `qemu-no-serial` because a virtual machine has no unique identity to read -
    # which is correct for a disposable target and disqualifying for anything
    # that ships to hardware.
    empty = os.path.join(base, "var-key-deliverability-fixture-empty")
    reset(empty)
    negative = run(installed, [empty])

    if status == "test-only" and negative.returncode == 0:
        bb.warn(
            "machine %s resolves to a var-key.sh (%s) declared test-only: with "
            "no identity readable it emitted %d bytes instead of refusing, so "
            "every device built from this image derives the SAME /var key. That "
            "is intended for disposable virtual targets only, and this machine "
            "is permitted to waive the refusal check for that reason. A machine "
            "that ships to hardware must resolve to a provider declared usable, "
            "which is required to refuse instead."
            % (machine, flat(installed), len(negative.stdout))
        )
    elif status == "test-only":
        # The waiver is declared but no longer needed: this provider DID refuse.
        # Reported rather than passed over silently, because the previous form
        # branched on the status alone and would have gone on announcing a
        # fleet-wide key over a provider that had grown a real refusal path -
        # asserting an outcome it never looked at.
        bb.warn(
            "machine %s resolves to a var-key.sh (%s) declared test-only, but it "
            "refused the empty identity fixture (exit %d) rather than emitting a "
            "key. The waiver is no longer doing anything: declare this provider "
            "usable and drop the machine from the permitted list."
            % (machine, flat(installed), negative.returncode)
        )
    elif negative.returncode == 0:
        # The remedy names the fix and NOT the waiver, deliberately. The only
        # reader of this message is someone whose provider just failed, and
        # test-only is gated on a machine list they cannot reach from here
        # anyway; offering it as an alternative would be handing out the bypass
        # in the same paragraph as the diagnosis.
        bb.fatal(
            lead + "its installed var-key.sh (%s) derived a key from an EMPTY "
            "identity fixture, emitting %d bytes rather than refusing. A "
            "provider that substitutes a constant when no identity is readable "
            "gives every device in the fleet the same /var key, with no symptom "
            "until one device's disk opens on another. Make it exit non-zero "
            "when it finds no identity, the way the i.MX, Jetson and x86-64 "
            "providers do."
            % (flat(installed), len(negative.stdout))
        )

    # ATTESTATION: bind the bytes that just passed to the bytes that ship.
    #
    # Everything above validates ${D} at the moment this postfunc runs. A
    # bbappend registering its OWN do_install postfunc runs after this one and
    # can replace the provider with anything carrying `# ...: usable` - an
    # `exit 1`, or a constant key - and the image tier, which reads only the
    # status declaration, accepts it. The check has already passed by then and
    # never looks again.
    #
    # Record the digest of what was actually exercised, next to it, so the image
    # tier can require the copy it ships to be that same file.
    #
    # What this does NOT stop: an edit that updates the digest alongside the
    # provider. Both are in ${D} and equally writable, so this binds against a
    # postfunc that replaces the provider without knowing the attestation
    # exists - the accidental and the expedient case, which is the same threat
    # the image tier was added for. It is not a signature and a determined
    # author defeats it in one more line.
    #
    # WHAT THE ATTESTATION MEANS DIFFERS PER COMPONENT, and saying otherwise
    # was the sharpest thing a review caught here. Everything above executes
    # var-key.sh against synthetic identities, so ITS digest means "these bytes
    # derived a device-unique key". Nothing in this recipe executes or parses
    # cryptsetup-var.sh or var-hwkey.sh, so THEIR digests mean only "these bytes
    # were in ${D} when do_install finished".
    #
    # That weaker binding is still worth having: it catches a postfunc that
    # replaces a script after this one runs, and any edit between packaging and
    # the image. It does not catch a do_install:append that lands BEFORE this
    # postfunc, which for the two unexecuted components means a substituted
    # unlock script is attested rather than refused. Closing that needs a
    # behavioural check for cryptsetup-var.sh, which does not exist yet.
    #
    # devtool-debt: the companions are attested without being validated.
    # Ceiling: catches post-do_install substitution only.
    # Upgrade trigger: a behavioural check for cryptsetup-var.sh exists - at
    # minimum, one that runs it against a fixture and requires it to refuse
    # when the capability is undeclared.
    #
    # Every script on the unlock path, not just the provider. var-key.sh is the
    # smaller target: it derives 64 bytes and returns them, while
    # cryptsetup-var.sh decides whether to call it at all, what to do with the
    # result, and whether to refuse. Substituting a constant key file there, or
    # deleting the capability check, left the provider's own digest matching and
    # passed all three tiers. avocado_var_key_attested_components() carries the
    # list and the reason avocado-posture-publish.sh is not on it.
    for dirvar, subpath, required in avocado_var_key_attested_components():
        component = os.path.basename(subpath)
        root_dir = d.getVar(dirvar)
        if not root_dir:
            bb.fatal(
                lead + "cannot resolve %s, so it cannot say where %s should be "
                "installed. That variable is set by bitbake.conf."
                % (flat(dirvar), flat(subpath))
            )
        # Resolved the same way the provider is, and for the same reason: a
        # symlink at any component makes this write and the device's read land
        # in different files, so an attestation written through one attests
        # bytes the image will not run.
        target = avocado_var_key_resolve_shipped(
            d.getVar("D"), root_dir + "/" + subpath, lead, flat, bb.fatal,
        )
        if not os.path.isfile(target):
            if not required:
                # A machine with no key-wrapping engine ships no var-hwkey.sh,
                # which is correct. The image tier still refuses one that ships
                # unattested, so absence here cannot be used to smuggle one in.
                continue
            why = {
                "cryptsetup-var.sh":
                    "cryptsetup-var.sh is what reads the capability "
                    "declaration at boot and calls the provider; an image "
                    "without it never unlocks /var whatever the provider does.",
                "var-key.sh":
                    "var-key.sh is what derives the phase-1 key; without it "
                    "cryptsetup-var.sh has nothing to call.",
                "cryptsetup-var.service":
                    "cryptsetup-var.service is what starts the unlock at all; "
                    "its ExecStart names the script and its "
                    "ConditionPathExists gates the whole unit, so without it "
                    "fstab mounts a plaintext /var.",
            }.get(component, "It is declared required by "
                             "avocado_var_key_attested_components().")
            bb.fatal(
                lead + "installs no %s at %s. %s"
                % (component, flat(target), why)
            )
        # Digest FIRST, then open for write. Computing it inside the "w"
        # context reported an unreadable source as a failed write, sending the
        # author to check permissions on a directory that was writable, and
        # truncated the .sha256 before the failure - leaving a zero-byte
        # attestation that tier 3 already has a branch for.
        try:
            digest = avocado_var_key_digest(target)
        except OSError as exc:
            bb.fatal(
                lead + "could not read its installed %s (%s) to attest it: %s."
                % (component, flat(target), flat(exc))
            )
        try:
            with open(target + ".sha256", "w", encoding="utf-8") as f:
                f.write(digest + "\n")
        except OSError as exc:
            bb.fatal(
                lead + "its installed %s (%s) passed every check but the "
                "attestation beside it could not be written: %s. The image tier "
                "requires that file, so shipping without it would refuse the "
                "build later with a less useful diagnostic."
                % (component, flat(target), flat(exc))
            )
}
do_install[postfuncs] += "avocado_var_key_check_deliverability"

# MACHINE is read only to name the machine in a diagnostic, but a getVar inside
# a postfunc enters do_install's signature. Left in, it would split do_install
# sstate across every machine that shares one provider and installs byte
# identical content - the seven Jetson-family machines on meta-avocado-nvidia's.
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
#   coreutils     - tr, cut and printf, which EVERY var-key provider uses to
#                   normalise its identity and derive the salt. Declared rather
#                   than assumed: the line below used to say these were "already
#                   in the avocado initramfs", which was true and is not a
#                   dependency. sed was declared for stripping the `openssl
#                   dgst` prefix while cut - one pipe further along that same
#                   line - was not, so the recipe already disagreed with itself
#                   about what counts as needing a declaration.
#
#                   The failure this prevents is invisible to all three tiers.
#                   They run the provider on the BUILD HOST, where GNU coreutils
#                   is always present, so a provider that would find no `tr` in
#                   the initramfs derives a key perfectly at build time and
#                   fails at first boot with /var never unlocking. Free today:
#                   coreutils 9.10 is already in the initramfs manifest, so this
#                   changes nothing about what ships, only about what is
#                   guaranteed to.
#
#                   Not sufficient on its own for a busybox initramfs. Nothing
#                   in this layer installs busybox and `tr` resolves to
#                   tr.coreutils today (verified on the built qemux86-64
#                   initramfs), but busybox `tr` gates POSIX character classes
#                   behind CONFIG_FEATURE_TR_CLASSES, and without it
#                   `tr '[:upper:]' '[:lower:]'` treats the argument as a
#                   literal character set - the placeholder normalisation then
#                   silently stops matching and an OEM default is accepted as a
#                   device identity. An RDEPENDS cannot express "and not the
#                   busybox applet", so that stays a property of the image.
# (blockdev, blkid, systemd-cryptenroll, mktemp and dirname come in via
#  util-linux and systemd, which packagegroup-avocado-initramfs installs.)
RDEPENDS:${PN} = "cryptsetup openssl-bin btrfs-tools gawk sed coreutils libdevmapper"

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
# Named explicitly: FILES:${PN} globs ${libexecdir}/cryptsetup-var/ and so
# picks up the three script digests for free, but nothing globs the unit
# directory. Without this line the unit's attestation is packaged nowhere, the
# image ships without it, and tier 3 refuses every build with "ships no
# attestation for cryptsetup-var.service".
FILES:${PN} += "${systemd_system_unitdir}/cryptsetup-var.service.sha256"
FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/cryptsetup-var.service"
