FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# Set by the boot-integrity-poc block below when this machine gets the EFI boot
# path. Defaulted here so do_configure's test reads a defined value on every
# other build rather than depending on how bitbake expands an unset variable
# inside a shell function.
AVOCADO_EFI_BOOT_ENV ?= "0"

# The UUU tag goes on the boot partition. For 8+, the boot partition image
# is imx-boot, so disable UUU-tagging here
UUU_BOOTLOADER:mx8-generic-bsp = ""
UUU_BOOTLOADER:mx9-generic-bsp = ""

SRC_URI:append:class-target = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

# The FRDM defconfigs enable EFI capsule authentication, whose ESL step shells
# out to a host tool no recipe here provides, so do_compile fails on a clean
# workspace whether or not signing is on. Not gated on any feature for that
# reason. See the fragment for the full account.
#
# SRC_URI is the whole mechanism - do NOT add a cat line to do_configure:append
# below for this fragment. UBOOT_DEFCONFIG expands to the literal ['sd'] (its
# `.split((',', 1)[0])` is `.split(',')`, which returns a list), so every cat
# line writes to a path named ['sd'] and the real defconfig is never touched.
# These fragments reach .config via cml1.bbclass's merge_config.sh over
# SRC_URI's file://*.cfg entries instead.
#
# AHAB (i.MX9) signed-boot support in U-Boot, gated on the 'ahab'
# DISTRO_FEATURE: machine-only gating compiled CONFIG_AHAB_BOOT=y into every
# imx93-frdm/imx91-frdm u-boot, so booti demanded a signed container even on
# builds that never constructed one ("Authenticate OS container is failed" on a
# plain build). The EFI capsule options the stock defconfig enables are already
# turned off for every board and version by disable-unused-vendor-features.cfg.
SRC_URI:append:imx93-frdm = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' file://ahab.cfg', '', d)}"
SRC_URI:append:imx91-frdm = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' file://ahab.cfg', '', d)}"

# disable-unused-vendor-features.cfg turns off NXP stock defconfig defaults
# (EFI capsule-on-disk, USB DFU) that Avocado never uses and that do not build
# in this layer set - see the fragment's own header. Every u-boot-imx board:
# the same symbols are on in the imx8mp-evk, imx91/93/95-frdm defconfigs alike.
SRC_URI:append:class-target = " file://disable-unused-vendor-features.cfg"

# fit.cfg enables base FIT container support (CONFIG_FIT) on every u-boot-imx
# board. Capability, not policy: it is already =y in the stock imx8m/imx9
# defconfigs and costs nothing where the env still boots loose files, and a
# machine that flips to `bootm fitImage` (avocado-imx-fit.inc) must be able to
# parse a FIT whether or not signing is on.
# fit.cfg enables base FIT container support (CONFIG_FIT) unconditionally on
# avocado-imx93-frdm. The boot partition manifest (stone-imx93-frdm.json) and
# the U-Boot env boot command (avocado-imx93-frdm.env) are both static
# per-machine files with no bitbake conditional mechanism, and both already
# bootm a single FIT unconditionally - so U-Boot on this machine must always
# be able to parse a FIT, signed or not. Every other NXP board is unaffected.
#
# SRC_URI is the whole mechanism. cml1.bbclass's do_configure runs
# merge_config.sh over every file://*.cfg in SRC_URI, straight from the layer
# path - that is what puts these symbols in .config. Do NOT add a `cat` line
# into do_configure:append for a new fragment: UBOOT_DEFCONFIG below expands to
# the literal ['sd'] (its `.split((',', 1)[0])` is `.split(',')`, which returns
# a list), so every cat line in this file appends to a path named `['sd']` and
# the real defconfig is never touched. Confirmed from temp/run.do_configure and
# log.do_configure on a real build. A fragment added only via a cat line
# therefore reaches nothing, silently - which for a verification Kconfig means
# shipping a bootloader that enforces nothing.
SRC_URI:append:class-target = " file://fit.cfg"

# fit-verify.cfg enables U-Boot FIT signature verification, and the same gate
# embeds the FIT public key into U-Boot's own control DTB so the running
# bootloader carries its own trust anchor rather than reading the key from
# writable storage (spec: "the verification key is not modifiable from the
# running system"). Gated on the 'verified-boot' DISTRO_FEATURES token alone -
# no machine check - so every u-boot-imx board that opts in gets the same
# treatment; a board whose env still boots loose files with booti is unaffected
# by CONFIG_FIT_SIGNATURE (it only ever acts inside bootm).
# Compile the Avocado boot flow into U-Boot's default environment.
#
# Until this landed, the flow (bootcmd, avocado_boot_init, load_image,
# avocado_boot and the variables they read) reached U-Boot ONLY as the saved
# environment: u-boot-env.inc runs mkenvimage over env/${MACHINE}.txt and fwup
# writes the result to the uboot-env partition. That is exactly what
# CONFIG_ENV_WRITEABLE_LIST rejects - env/mmc.c imports the saved copy with
# H_EXTERNAL and env/flags.c drops every H_EXTERNAL variable missing the 'w'
# access flag - so the permit list alone would leave the board running U-Boot's
# stock bootcmd with no Avocado boot path at all.
#
# Unconditional for this machine rather than gated on verified-boot, for the
# same reason fit.cfg is unconditional: a build without the feature has to boot
# the same way as one with it. Without the feature the saved environment is
# still imported and still wins, so nothing changes for those builds.
#
# env/${MACHINE}.txt deliberately keeps its own full copy of the flow, and must.
# env/env.c's env_load() seeds the built-in default before the storage driver
# only under CONFIG_ENV_WRITEABLE_LIST; with the feature off the hash table is
# built from the saved environment alone, so a reduced .txt would leave those
# builds with no bootcmd. See the debt marker there.
#
# avocado-imx93-frdm.env includes the vendor's own board .env, which is what
# the build picked up before this and which supplies values the flow relies on
# without setting them - initrd_high, and the fastboot/manufacturing helpers
# that uuu recovery uses.
SRC_URI:append:avocado-imx93-frdm = " file://env-compiled-in.cfg file://avocado-imx93-frdm.env"

# CONFIG_ENV_SOURCE_FILE resolves against board/$(SYS_VENDOR)/$(SYS_BOARD),
# which board/nxp/imx93_frdm/Kconfig fixes at nxp/imx93_frdm for this target.
# No bitbake variable carries it, so the path is spelled out.
#
# It is spelled out TWICE - here, and in the fragment's own #include - and both
# assume the 2026.04 layout. This is a `%` bbappend and the machine no longer
# pins a version, so u-boot-imx 2025.04 is still reachable, and 2025.04 keeps
# this board at board/freescale/imx93_frdm instead. Guard rather than let
# `install` fail: its "cannot create regular file" names a path that appears in
# no recipe, and CONFIG_ENV_SOURCE_FILE exists in 2025.04 too, so merge_config
# accepts the fragment silently and offers no second chance to notice.
do_configure:prepend:avocado-imx93-frdm () {
    if [ ! -d ${S}/board/nxp/imx93_frdm ]; then
        bbfatal "board/nxp/imx93_frdm is absent from ${S}. u-boot-imx 2025.04 keeps this board at board/freescale/imx93_frdm; the compiled-in environment (CONFIG_ENV_SOURCE_FILE, and the #include inside avocado-imx93-frdm.env) assumes the 2026.04 layout. Build this machine against 2026.04, or teach both paths about the older layout."
    fi
    install -m 0644 ${UNPACKDIR}/avocado-imx93-frdm.env \
        ${S}/board/nxp/imx93_frdm/avocado.env

    # boot-integrity-poc: append the EFI boot path so its redefinitions of
    # image_file, avocado_boot and bootcmd win over the base environment's.
    # env2string.awk keys an awk array by variable name and emits each key once,
    # so last definition wins and no duplicate reaches U-Boot - but only if this
    # lands after the base file, which is why it is a concatenation and not a
    # second install.
    #
    # sed rather than a literal DTB name in the .env: FIT_CONF_DEFAULT_DTB is
    # what the FIT path already pins, and spelling the name twice is how the two
    # boot paths would come to disagree about which device tree is the default.
    # The U-Boot ${...} references in that file are invisible to bitbake because
    # they live in a file rather than in this recipe body - inlining the block
    # here would let bitbake expand ${bootpart} and friends to nothing.
    if [ "${AVOCADO_EFI_BOOT_ENV}" = "1" ]; then
        # An empty FIT_CONF_DEFAULT_DTB would substitute to `fdt_file=`, and the
        # board would then fail to load a device tree at boot with nothing in the
        # build log pointing back here. Fail the build instead.
        if [ -z "${FIT_CONF_DEFAULT_DTB}" ]; then
            bbfatal "boot-integrity-poc: FIT_CONF_DEFAULT_DTB is empty, so the EFI boot path has no device tree to load. It is set in the machine conf; this build has lost it."
        fi
        bbwarn "boot-integrity-poc: replacing this board's FIT boot path with an EFI hand-off (bootefi on an EFI-stub kernel staged in the ESP). Slot selection is unchanged. The staged kernel is signed against the enrolled db, so the firmware refuses a replacement it cannot verify - but the bootloader performing that verification is itself unauthenticated, because AHAB is open on this part and cannot be closed. A boot-medium writer can replace U-Boot, seed and all."
        printf '\n' >> ${S}/board/nxp/imx93_frdm/avocado.env
        sed -e 's|@FDT_FILE@|${FIT_CONF_DEFAULT_DTB}|' \
            ${UNPACKDIR}/avocado-imx93-frdm-efi-boot.env \
            >> ${S}/board/nxp/imx93_frdm/avocado.env
    fi

    # Stage the UEFI variable seed where U-Boot's own build can find it.
    # lib/efi_loader/Makefile resolves CONFIG_EFI_VAR_SEED_FILE as
    # $(srctree)/$(EFI_VAR_SEED_FILE) - a path relative to the SOURCE tree, not
    # to the deploy directory - so a seed left where sb-keys deployed it is a
    # seed U-Boot never reads. It would still build, with an empty variable
    # store, and the board would come up in setup mode while the build log
    # claimed enrolment.
    #
    # Same `if` wrapper, same reason as the block above and the do_compile
    # prepend below: a bare `return` at statement position ends the WHOLE
    # concatenated do_configure, not just this fragment of it.
    if [ "${AVOCADO_EFI_BOOT_ENV}" = "1" ]; then
        if [ ! -f ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var ]; then
            bbfatal "boot-integrity-poc: ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var is absent, so U-Boot would compile with an empty preseed and the board would come up in setup mode while this build reported enrolment. sb-keys' do_deploy produces it; this recipe DEPENDS on sb-keys under the same gate."
        fi
        # TWO copies, deliberately, because two different consumers resolve the
        # seed two different ways and satisfying one does not satisfy the other:
        #
        #   ${S}/ubootefi.var
        #     The MAKE PREREQUISITE. lib/efi_loader/Makefile declares
        #     $(obj)/efi_var_seed.o: $(srctree)/$(EFI_VAR_SEED_FILE), so make
        #     refuses to build the object unless the file exists at exactly this
        #     path. It is also what the do_deploy:append below tests before it
        #     will write db.fingerprint - removing this copy silently disables
        #     that integrity check as well as breaking the build.
        #
        #   ${S}/lib/efi_loader/ubootefi.var
        #     The ASSEMBLER INCLUDE PATH. efi_var_seed.S carries a bare
        #     .incbin "ubootefi.var", which gas resolves against its own -I list.
        #     That list does NOT contain the srctree root, so the prerequisite
        #     above being satisfied is not enough: on an out-of-tree build
        #     (O=${B}, which is how this recipe builds) the assembler fails with
        #     "Error: file not found: ubootefi.var". The -I list DOES already
        #     contain $(srctree)/lib/efi_loader, so a copy here makes the bare
        #     filename resolve with no U-Boot patch and no absolute path in
        #     CONFIG_EFI_VAR_SEED_FILE (which would break the prerequisite, since
        #     make would expand it to $(srctree)//abs/path).
        install -m 0644 ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var ${S}/ubootefi.var
        install -m 0644 ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var ${S}/lib/efi_loader/ubootefi.var
    fi
}

# The fingerprint of the db certificate that went into the seed, written only on
# the path that actually staged it. Task 4.1 compares the payload it signs
# against this value before signing, and refuses to sign when the marker is
# absent - the two halves of one token, each enforcing the half it can observe,
# since neither recipe can see the other's task outcome.
#
# do_deploy rather than the do_configure:prepend that stages the seed, even
# though that is where the staging is decided: deploy.bbclass sets
# do_deploy[cleandirs] = "${DEPLOYDIR}", so anything written there earlier in
# the task graph is erased before do_deploy runs, and the marker would vanish
# without a trace. The `${S}/ubootefi.var` test below is what keeps the claim
# honest across the move - the marker is written because the seed IS in the
# source tree, not because the gate was on.
do_deploy:append:avocado-imx93-frdm() {
    if [ "${AVOCADO_EFI_BOOT_ENV}" = "1" ]; then
        if [ ! -f ${S}/ubootefi.var ]; then
            bbfatal "boot-integrity-poc: ${S}/ubootefi.var is absent at do_deploy, so the seed never reached \$(srctree) and this U-Boot enrols nothing. Refusing to write the db.fingerprint marker that task 4.1 reads as proof it did."
        fi

        # The seed file existing proves it was STAGED, not that it was COMPILED
        # IN. Those come apart quietly: merge_config.sh warns rather than fails
        # when a requested symbol loses to a dependency, so a defconfig bump
        # that turns EFI_MM_COMM_TEE back on (PRESEED depends on !that) drops
        # PRESEED, `obj-$(CONFIG_EFI_VARIABLES_PRESEED) += efi_var_seed.o`
        # simply never builds, and the staged file sits in $(srctree) unread.
        # Every downstream gate then passes on a bootloader that enrols nothing.
        #
        # EFI_SECURE_BOOT is checked for the same reason and is the worse loss:
        # without it efi_image_authenticate() is not compiled, so the firmware
        # admits any payload while still reporting a key database.
        #
        # Read the PRODUCED config, not the fragment: the fragment is the
        # request, the .config is the answer. This layer's own convention
        # elsewhere is the same, because linux-imx applies fragments with a raw
        # cat that can lose a symbol without saying so.
        # This recipe builds one directory PER UBOOT_CONFIG - the observed layout
        # is ${B}/imx93_11x11_frdm_defconfig-sd/.config, not ${B}/.config - and
        # every variant it produces has to enforce, so check them all rather
        # than reconstructing one name from UBOOT_CONFIG. Both layouts are
        # globbed so a single-config recipe still works.
        #
        # Finding NO config is a failure, not a pass: it means this check could
        # not run, and a check that silently does not run is worse than none.
        # A string flag, not a counter. BitBake's build_dependencies shell
        # parser raises NotImplementedError('$((') on arithmetic expansion in a
        # task body, and it does so at PARSE time for every u-boot-imx recipe in
        # the tree - including versions this machine never builds - so the whole
        # parse halts rather than the one task failing.
        _cfg_seen=no
        for _cfg in ${B}/.config ${B}/*/.config; do
            [ -f "$_cfg" ] || continue
            _cfg_seen=yes
            for _sym in CONFIG_EFI_VARIABLES_PRESEED CONFIG_EFI_SECURE_BOOT; do
                if ! grep -q "^${_sym}=y\$" "$_cfg"; then
                    bbfatal "boot-integrity-poc: ${_sym} is not set in the produced $_cfg, so this U-Boot does not do what the enrolment claims. The fragment requests it; Kconfig did not grant it, which means an unmet dependency rather than a missing request. Check those first: EFI_SECURE_BOOT needs EFI_LOADER and FIT_SIGNATURE (fit-verify.cfg supplies the latter), and EFI_VARIABLES_PRESEED needs EFI_MM_COMM_TEE off. Refusing to write db.fingerprint."
                fi
            done
        done
        if [ "$_cfg_seen" != yes ]; then
            bbfatal "boot-integrity-poc: no .config found under ${B} at do_deploy, so it cannot be confirmed that the seed was compiled in rather than merely staged. Refusing to write db.fingerprint on an unverifiable build."
        fi
        # LEG 2: is the seed in $(srctree) the seed sb-keys just produced?
        #
        # The staging install lives in do_configure:prepend, so a valid
        # do_configure stamp means it does not re-run. Rotate the keys and
        # rebuild without invalidating that stamp - the key directory sits
        # outside tmp/ and is excluded from task hashing, so this is easy to do
        # accidentally - and $(srctree) keeps the OLD seed while the deploy
        # directory holds the new one. This task would then publish a marker
        # describing the new keys for a bootloader compiling the old ones.
        #
        # A whole-file compare rather than a db-only one: the seed now carries
        # four variables, and a stale PK or dbx is just as wrong as a stale db.
        # BOTH staged copies, not just the srctree-root one. do_configure:prepend
        # installs the seed twice on purpose (see its comment): ${S}/ubootefi.var
        # satisfies make's prerequisite, and ${S}/lib/efi_loader/ubootefi.var is
        # what gas actually embeds, because efi_var_seed.S carries a bare
        # `.incbin "ubootefi.var"` resolved against its own -I list.
        #
        # Checking only the root copy checked the file that is NOT linked in. A
        # hand edit, a partial source-tree clean, or any path refreshing one and
        # not the other publishes db.fingerprint describing the root copy while
        # the bootloader carries the other - which is verbatim the failure the
        # message below names, passing the check that exists to catch it.
        if [ ! -f ${S}/lib/efi_loader/ubootefi.var ]; then
            bbfatal "boot-integrity-poc: ${S}/lib/efi_loader/ubootefi.var is absent at do_deploy. That is the copy efi_var_seed.S actually includes, so this U-Boot cannot have compiled the seed in. Refusing to write db.fingerprint."
        fi
        if ! cmp -s ${S}/lib/efi_loader/ubootefi.var ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var; then
            bbfatal "boot-integrity-poc: the seed at ${S}/lib/efi_loader/ubootefi.var - the copy gas embeds - differs from the one sb-keys deployed. Run 'bitbake -c cleansstate u-boot-imx' (or -c configure) so the current seed is staged, rather than publishing a marker for keys this binary does not carry."
        fi
        if ! cmp -s ${S}/ubootefi.var ${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var; then
            bbfatal "boot-integrity-poc: the seed staged at ${S}/ubootefi.var differs from the one sb-keys deployed. do_configure staged an older seed and its stamp is still valid, so this U-Boot compiles a key database that is not the current one. Run 'bitbake -c cleansstate u-boot-imx' (or -c configure) so the current seed is staged, rather than publishing a marker for keys this binary does not carry."
        fi

        # LEG 1: fingerprint what was PACKED, not what is in the key directory.
        #
        # This used to be sha256(${AVOCADO_SB_KEYS_DIR}/db.crt), read fresh at
        # this task - a different artifact, at a later time, than the DER
        # gen-efi-seed.sh actually packed. The manifest records that digest in
        # the same run as the pack, so there is no window between the two.
        #
        # Note it is the DER's digest, not the .crt's: the firmware enrols DER,
        # so the DER hash is what the on-device reporter can compare against the
        # db efivar. avocado-stone compares against db.der for the same reason.
        _mf="${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var.manifest"
        if [ ! -f "$_mf" ]; then
            bbfatal "boot-integrity-poc: $_mf is absent, so the digest of the db certificate actually packed into the seed is unavailable. Re-hashing the key directory here is what this marker was changed to stop doing. sb-keys' gen-efi-seed.sh writes it beside the seed."
        fi
        _db_digest=$(awk '$1 == "db" { print $2 }' "$_mf")
        case "$_db_digest" in
            "" | *[!0-9a-f]*)
                bbfatal "boot-integrity-poc: $_mf carries no usable db digest (got '$_db_digest'). Refusing to write db.fingerprint from a manifest this task cannot read."
                ;;
        esac
        install -d ${DEPLOYDIR}/sb-keys
        # Bare hex, no filename column: the consumer compares a value, and
        # sha256sum's second field is a build-tree path that would differ
        # between two builds of the identical certificate.
        printf '%s\n' "$_db_digest" > ${DEPLOYDIR}/sb-keys/db.fingerprint
    fi
}

# fit-verify.cfg enables U-Boot FIT signature verification. It is NOT
# unconditional like fit.cfg above: it is only meaningful on
# avocado-imx93-frdm (the only machine this change wires a FIT signing key
# for) and only when the customer has opted in via the 'verified-boot'
# DISTRO_FEATURES token, so every other NXP board and every frdm build
# without the feature build exactly as before (still gets an unsigned FIT
# via fit.cfg above, but no signature enforcement).
#
# u-boot.inc already unconditionally inherits OE-core's uboot-sign.bbclass, so
# setting UBOOT_SIGN_ENABLE plus the same UBOOT_SIGN_KEYDIR/UBOOT_SIGN_KEYNAME
# ="FIT" pair avocado-imx-fit.inc sets for the kernel-fit-image side is enough:
# uboot-sign's do_uboot_assemble_fitimage task (added unconditionally by
# u-boot.inc, gated internally on UBOOT_SIGN_ENABLE) runs mkimage -f auto-conf
# against AVOCADO_SB_KEYS_DIR/FIT.crt and embeds the PUBLIC half only into
# u-boot.dtb before it is concatenated into the final u-boot binary - the
# private FIT.key never leaves the build host. The imx8m/imx9 defconfigs build
# with CONFIG_OF_SEPARATE=y, the precondition uboot-sign.bbclass documents for
# this embedding step, so no CONFIG_DEFAULT_DEVICE_TREE/binman fallback is
# needed. DEPENDS on sb-keys is added under the same gate so FIT.crt exists in
# AVOCADO_SB_KEYS_DIR before this recipe's fitimage-assemble task runs.
python () {
    if bb.utils.contains('DISTRO_FEATURES', 'verified-boot', True, False, d):
        d.appendVar('SRC_URI', ' file://fit-verify.cfg')
        # Saved-environment lockdown, for the boards that carry a permit list
        # and a compiled-in boot flow (env-compiled-in.cfg): the list is
        # CFG_ENV_FLAGS_LIST_STATIC, a C #define in that board's config header
        # that env-writeable-list.patch adds, so it cannot be a .cfg entry, and
        # env-writeable-list.cfg's CONFIG_ENV_WRITEABLE_LIST without it would
        # reject every saved variable - avocado_boot_slot included. The two
        # ride the same gate and the same machine scope on purpose; a board
        # whose Avocado boot flow still lives only in the saved environment
        # must not get either.
        if d.getVar('MACHINE') == 'avocado-imx93-frdm':
            d.appendVar('SRC_URI', ' file://env-writeable-list.cfg file://env-writeable-list.patch')
        d.appendVar('DEPENDS', ' sb-keys')
        d.setVar('UBOOT_SIGN_ENABLE', '1')
        d.setVar('UBOOT_SIGN_KEYDIR', d.getVar('AVOCADO_SB_KEYS_DIR'))
        d.setVar('UBOOT_SIGN_KEYNAME', 'FIT')
}

# efi-vars-poc.cfg gives this board a UEFI variable store so that efivarfs
# exists and userspace can read a SecureBoot value. It is PoC scaffolding with
# a known replacement, not a step toward the real capability, and the two
# differ in the one property that matters: the PoC store is a file on the ESP
# that anyone who can write the boot medium can edit.
#
# Gated on 'boot-integrity-poc' and deliberately NOT on
# 'boot-integrity-reporting'. That second name belongs to the authenticated
# capability, and letting scaffolding answer to it is exactly what would make a
# PoC read as delivered to anything inspecting the tree.
#
# Gated on the token ALONE rather than on token-and-machine, unlike fit-verify
# above. The variable store is not machine-specific, so restricting it to one
# machine would leave any other board that opted in with the token set and no
# store - a silent no-op. The warning below covers the converse case: a board
# that gets the store but has no EFI boot path to reach it.
python () {
    if not bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', True, False, d):
        return

    # Refuse the PoC and the real capability together. They are not additive:
    # EFI_VARIABLE_FILE_STORE and EFI_MM_COMM_TEE are alternatives in one
    # Kconfig `choice`, so two fragments setting different members do not
    # produce two stores - merge_config.sh applies them in order and the LAST
    # one wins, with nothing printed. When that is the PoC fragment the image
    # gets an UNAUTHENTICATED store while its own feature tokens claim an
    # authenticated one, which is the worst available outcome and is invisible
    # in a build log.
    #
    # Fatal rather than a warning, and rather than picking a winner here. A
    # build asking for both has an incoherent intent, and guessing which one
    # was meant is how the unauthenticated store ends up shipping under the
    # authenticated name.
    if bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-reporting', True, False, d):
        bb.fatal("boot-integrity-poc and boot-integrity-reporting are mutually "
                 "exclusive: they select different members of U-Boot's UEFI "
                 "variable-store Kconfig choice, so enabling both lets fragment "
                 "order decide silently which store the image gets. Pick one.")

    d.appendVar('SRC_URI', ' file://efi-vars-poc.cfg')

    # The spec permits an unauthenticated store ONLY when the build announces
    # the substitution; a silent one is the failure it forbids. So this warning
    # is a required output of the build, not commentary on it - if it ever
    # becomes conditional or gets downgraded, the build stops satisfying the
    # requirement that licensed the PoC in the first place.
    bb.warn("boot-integrity-poc: UEFI variables will be stored UNAUTHENTICATED "
            "in /ubootefi.var on the EFI system partition. They persist across "
            "reboot, which is NOT the same as being protected - anyone who can "
            "write the boot medium can change them. Do not read a value from "
            "this store as evidence about how the device booted.")

    # A store with no EFI boot path to consume it produces no efivarfs, and now
    # that the same token also enrols a key database, that is no longer the
    # harmless no-op it was when this only warned. Enrolment takes the firmware
    # out of setup mode, so the board reports SecureBoot=1 on a machine that
    # will never run bootefi - a device claiming enforcement on a path it does
    # not take, which is exactly the false claim this change exists to remove.
    #
    # Escalated in place rather than added as a second check. A distinct block
    # would test the identical condition and leave this warning's "nothing will
    # reach it" reading standing next to a fatal that says the opposite; one
    # test with one verdict is what a reader can act on.
    if d.getVar('MACHINE') != 'avocado-imx93-frdm':
        bb.fatal("boot-integrity-poc: the EFI boot path is wired for "
                 "avocado-imx93-frdm only, so on %s this would enrol a UEFI "
                 "key database and take the firmware out of setup mode on a "
                 "board that never runs bootefi - the device would report "
                 "enforcement on a boot path it does not take, and efivarfs "
                 "would be absent besides. Drop the token for this machine, or "
                 "wire the EFI boot path for it here first."
                 % d.getVar('MACHINE'))

    # CONFIG_EFI_SECURE_BOOT is `depends on EFI_LOADER && FIT_SIGNATURE`, and
    # FIT_SIGNATURE is carried by fit-verify.cfg under the SEPARATE verified-boot
    # token - which kas/feature/boot-integrity-poc.yml does not set. So the
    # documented PoC build (that feature file on top of the machine file) selects
    # EFI_SECURE_BOOT only because the pinned vendor defconfig happens to set
    # FIT_SIGNATURE itself, at configs/imx93_11x11_frdm_defconfig:37.
    #
    # Requesting the fragment here removes that dependency on a vendor default
    # rather than documenting it. It is a NO-OP against today's defconfig - both
    # symbols are already =y - and becomes load-bearing the moment a u-boot-imx
    # bump drops either one, which is the case the do_deploy assertion below can
    # detect but not prevent.
    #
    # Only the FRAGMENT, not the signing wiring. UBOOT_SIGN_ENABLE and the
    # UBOOT_SIGN_KEYDIR/KEYNAME pair stay in the verified-boot block above, so a
    # PoC-only build gets the Kconfig symbols and runs no signing step - exactly
    # what it does today via the defconfig. Skipped when verified-boot is also
    # set, because that block has already appended the same file and unpacking
    # one SRC_URI entry twice is not something to rely on.
    if not bb.utils.contains('DISTRO_FEATURES', 'verified-boot', True, False, d):
        d.appendVar('SRC_URI', ' file://fit-verify.cfg')

    # The preseed fragment. CONFIG_EFI_VARIABLES_PRESEED compiles the seed into
    # the U-Boot binary, which is what leaves no interval in which the board is
    # powered on and still accepting any key database, and which also makes
    # PK/KEK/db/dbx immutable at runtime (see the fragment's own header).
    #
    # SRC_URI is the whole mechanism - cml1.bbclass's merge_config.sh over the
    # file://*.cfg entries is what puts these symbols in .config. Do NOT add a
    # cat line into do_configure:append for it; see the UBOOT_DEFCONFIG note
    # below for why every such line writes to a path named ['sd'].
    d.appendVar('SRC_URI', ' file://efi-secureboot.cfg')

    # sb-keys' do_deploy writes the seed this build consumes, and its do_compile
    # writes the db.crt the fingerprint below is taken from. Without the
    # dependency do_configure races the recipe that produces its input.
    d.appendVar('DEPENDS', ' sb-keys')

    # DEPENDS alone is not enough here and the gap is silent. It orders this
    # recipe's do_configure after sb-keys:do_populate_sysroot, but the seed is
    # DEPLOYED, not installed - sb-keys' own `addtask deploy after do_install
    # before do_build` leaves do_deploy outside that chain entirely. Without
    # this flag the seed copy races its producer and loses on a clean build,
    # which surfaces as the bbfatal in do_configure:prepend rather than as a
    # missing dependency, so the cause would be read as a broken sb-keys.
    d.appendVarFlag('do_configure', 'depends', ' sb-keys:do_deploy')

    # The EFI boot path itself. Machine-gated where the store above is not:
    # the store is board-independent, but this block hardcodes this board's
    # boot flow, so shipping it anywhere else would break booting rather than
    # be a no-op. do_configure:prepend concatenates it onto the compiled-in
    # environment; see that function and the .env file's own header for why
    # appending (rather than replacing) is what makes the override take.
    d.appendVar('SRC_URI', ' file://avocado-imx93-frdm-efi-boot.env')
    d.setVar('AVOCADO_EFI_BOOT_ENV', '1')
}

# The PoC has to reach the SAVED environment as well as the compiled-in one,
# and this is not belt-and-braces. CONFIG_ENV_WRITEABLE_LIST rides the
# 'verified-boot' gate, and its permit list (env-writeable-list.patch) admits
# only avocado_boot_slot, the device identity vars, devnum and mmcblk - no
# boot-path variable - so with that feature ON the saved copies of bootcmd and
# image_file are rejected on import and the compiled-in EFI override above wins
# unopposed. With it OFF nothing rejects them: the saved environment is imported
# whole and wins, so the board would boot the FIT path while the build log
# claimed the PoC was enabled. That is the silent-substitution failure this
# change exists to avoid, arrived at from the opposite direction.
#
# The override text comes from the same .env file rather than a second copy in
# mkenvimage's flat format. grep pulls out its bare assignments; the C comment
# block does not survive, which is required, since mkenvimage has no notion of
# one. Two spellings of one boot path is how they come to disagree.
#
# Superseded keys are FILTERED OUT rather than shadowed by a later duplicate.
# The compiled-in path could rely on last-definition-wins because env2string.awk
# keys an awk array and emits each name once; mkenvimage has no such step - it
# rewrites line separators and checksums the result - so an appended duplicate
# would put two image_file entries into one environment blob and leave which one
# survives to U-Boot's import order. Filtering keeps the blob single-valued.
#
# The filter list is derived from the override file itself, so a variable added
# there is superseded automatically. Hardcoding the three names that collide
# today would leave the next addition shadowed-but-duplicated. It also makes the
# step idempotent across a do_compile rerun on a UNPACKDIR that was not
# re-unpacked, since a previous run's lines are filtered before the re-append.
#
# The body is wrapped in an `if` rather than guarded by an early `return`.
# bitbake concatenates a :prepend and the recipe's own do_compile into ONE
# shell function, so a `return` here does not end the prepend - it ends
# do_compile, before u-boot.inc's uboot_compile/uboot_compile_config ever run.
# That shipped: every avocado-imx93-frdm build WITHOUT boot-integrity-poc
# compiled no u-boot at all, and it stayed invisible because those builds always
# restored u-boot-imx from sstate. It surfaced only on a forced rebuild, as
# do_install failing on a missing u-boot-sd.bin - a message that points at
# u-boot.inc and names nothing here.
do_compile:prepend:avocado-imx93-frdm() {
    if [ "${AVOCADO_EFI_BOOT_ENV}" = "1" ]; then
        override="${WORKDIR}/avocado-efi-boot-flat.txt"
        # `|| true` so an empty extraction reaches the bbfatal below. bitbake
        # runs shell tasks under `set -e`, and without it a grep that matches
        # nothing aborts the task with grep's bare exit 1 - naming no file and
        # no cause.
        sed -e 's|@FDT_FILE@|${FIT_CONF_DEFAULT_DTB}|' \
            ${UNPACKDIR}/avocado-imx93-frdm-efi-boot.env \
            | grep -E '^[a-z_]+=' > "$override" || true

        # awk, not `cut | paste`: bitbake runs tasks under a restricted
        # HOSTTOOLS PATH that carries awk and sed but NOT paste, so the pipeline
        # died with `paste: command not found` (exit 127) at do_compile rather
        # than at parse.
        keys=$(awk -F= '{printf "%s%s", sep, $1; sep="|"} END {print ""}' "$override")
        if [ -z "$keys" ]; then
            bbfatal "boot-integrity-poc: extracted no assignments from avocado-imx93-frdm-efi-boot.env, so the saved environment would keep the FIT boot path while the build reported the PoC enabled."
        fi

        grep -vE "^($keys)=" ${UNPACKDIR}/${MACHINE}.txt > "$override.merged"
        cat "$override" >> "$override.merged"
        mv "$override.merged" ${UNPACKDIR}/${MACHINE}.txt
    fi
}

MKENVIMAGE_EXTRA_ARGS = "-r"

# Broken, and load-bearing for nothing - kept only because the two cat lines
# below have depended on it since before this change and fixing it would move
# where avocado.cfg/env-mmc.cfg land, which is a separate change with its own
# verification. `(',', 1)[0]` is the string ',', so this is UBOOT_CONFIG.split(',')
# - a LIST, which bitbake stringifies to ['sd']. Every cat line below therefore
# writes to ${S}/configs/['sd'] and the real defconfig is never touched. Those
# fragments still reach .config, via cml1.bbclass's merge_config.sh over SRC_URI;
# the cat lines are dead. Do not add a third.
UBOOT_DEFCONFIG = "${@'${UBOOT_CONFIG}'.split((',', 1)[0])}"

do_configure:append:class-target () {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

# With CONFIG_AHAB_BOOT, booti stops taking a raw kernel: cmd/booti.c reads its
# first argument as an AHAB container, authenticates it, and pulls the kernel
# and fdt destinations out of it via container_get_image_dst(). Handing it the
# bare Image the stock environment loads is what produces
# "Authenticate OS container is failed" and drops the board to a prompt.
#
# So the boot flow changes shape, not just its inputs: one signed container
# replaces the separate Image, dtb and initramfs loads, and both trailing
# arguments go away. The fdt address comes out of the container, and the
# initramfs is bundled into the kernel Image (INITRAMFS_IMAGE_BUNDLE, set in
# the machine configuration) so it rides inside the signed exec payload.
#
# booti never authenticates argv[1], so leaving the initramfs there would leave
# the component that unlocks LUKS /var outside the chain. Passing "-" instead
# is the documented no-ramdisk form - boot/image-board.c:474 compares the
# selector against "-" before trying to locate one.
#
# Patched into the environment text rather than kept as a second env file so
# the non-AHAB and AHAB environments cannot drift apart in every other line.
do_compile:prepend:bootvars-ubootenv() {
    if ${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'true', 'false', d)}; then
        # The container is staged at cntr_addr, NOT at image_addr, and the two
        # must not be the same address. authenticate_os_container() memcpys each
        # image to the destination recorded inside the container - which for the
        # kernel is image_addr - and booti then calls container_get_image_dst()
        # on the container to learn where that landed. Load the container at
        # image_addr and the first step overwrites what the second reads: the ELE
        # authenticates fine, then the parse fails with "Parse kernel and fdt
        # address failed -1", or the header check reports a bad container.
        # Verified on an FRDM-IMX93 - booti at a staged address boots Linux,
        # booti at image_addr does not.
        sed -i \
            -e 's|^load_image=.*|load_image=load ${devtype} ${devnum}:${bootpart} ${cntr_addr} os_cntr_signed.bin|' \
            -e 's|^avocado_boot=.*|avocado_boot=booti ${cntr_addr} - -;|' \
            -e 's|^bootcmd=run avocado_boot_init load_image load_devicetree load_initramfs avocado_boot|bootcmd=run avocado_boot_init load_image avocado_boot|' \
            -e 's|^fdt_addr=.*|fdt_addr=0x94000000|' \
            -e 's|^bootm_size=.*|bootm_size=0x40000000|' \
            ${ENV_FILEPATH}

        # fdt_addr and bootm_size are rewritten here rather than carried in the
        # environment, because only the signed path needs them. The bundled
        # kernel is ~200 MB and unpacks over the stock fdt_addr, and reaching
        # the new one needs a window wider than NXP's 256 MiB. An unsigned build
        # loads a ~33 MB kernel and is fine with the stock values, so moving
        # them unconditionally would change a boot path this feature does not
        # own.
        #
        # cntr_addr has to exist and has to differ from image_addr, per the
        # collision described above. Asserted rather than assumed because the
        # failure is a board that authenticates and then refuses to boot.
        if ! grep -q '^cntr_addr=' ${ENV_FILEPATH}; then
            bbfatal "AHAB is enabled but the environment defines no cntr_addr to stage the container at"
        fi
        if [ "$(sed -n 's/^cntr_addr=//p' ${ENV_FILEPATH})" = "$(sed -n 's/^image_addr=//p' ${ENV_FILEPATH})" ]; then
            bbfatal "cntr_addr equals image_addr; the container would be overwritten by its own payload during authentication"
        fi

        if ! grep -q 'os_cntr_signed.bin' ${ENV_FILEPATH}; then
            bbfatal "AHAB is enabled but the U-Boot environment still loads a bare kernel"
        fi
        if grep '^bootcmd=' ${ENV_FILEPATH} | grep -q 'load_devicetree'; then
            bbfatal "AHAB bootcmd still loads a separate device tree; the container carries that address itself"
        fi

        # The whole point of bundling the initramfs into the signed container in
        # the first place. A separate initramfs load reintroduces an
        # unauthenticated argv[1], and it fails open rather than loudly: the
        # board boots, /var unlocks, and nothing reports that the initrd that
        # derived the key was never checked.
        if grep '^bootcmd=' ${ENV_FILEPATH} | grep -q 'load_initramfs'; then
            bbfatal "AHAB bootcmd still loads a separate initramfs; booti never authenticates it, so it must be bundled into the kernel Image instead"
        fi
        if grep -q '^avocado_boot=.*ramdisk_addr' ${ENV_FILEPATH}; then
            bbfatal "AHAB boot command still passes a ramdisk argument to booti; that argument is never authenticated"
        fi
    fi
}

require recipes-bsp/u-boot/u-boot-env.inc
