# Depend on whichever bootloader the machine selects (u-boot-imx for the NXP
# EVK/FRDM, u-boot-compulab for CompuLab, u-boot-variscite for Variscite), not
# a hardcoded recipe. virtual/bootloader rather than ${IMX_DEFAULT_BOOTLOADER}:
# Variscite selects its bootloader through PREFERRED_PROVIDER_virtual/bootloader
# alone and leaves IMX_DEFAULT_BOOTLOADER at imx-base.inc's u-boot-imx, which is
# not COMPATIBLE_MACHINE for its boards, so the old form had no provider there.
do_compile[depends] += "virtual/bootloader:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

# avocado-imx-fitimage assembles the FIT a FIT-booting machine's boot partition
# manifest expects (any machine requiring avocado-imx-fit.inc); virtual/kernel's own do_deploy (implied above via
# IMX_DEFAULT_BOOTLOADER/imx-boot) only deploys the discrete Image/dtb files
# linux-imx itself produces, not the FIT bundling them - that is a separate
# recipe now (kernel.bbclass rejects KERNEL_IMAGETYPE=fitImage in this oe-core
# release; see avocado-imx-fitimage.bb's own header).
do_compile[depends] += "${@bb.utils.contains('KERNEL_CLASSES', 'kernel-fit-extra-artifacts', ' avocado-imx-fitimage:do_deploy', '', d)}"

DEPENDS += " jq-native mkfat-native fwup-native"

# fw_setenv, for stone-provision-uuu-emmc.sh, which patches devnum and mmcblk
# into the U-Boot environment inside the disk image before writing it. jq and
# fwup arrive above; fw_setenv had no provider, so do_stone_provision died with
# "fw_setenv: command not found" the first time that profile was selected.
# libubootenv ships it (it also PROVIDES u-boot-fw-utils).
#
# Scoped to the profile that calls it rather than added to the shared
# avocado-stone.bb: 5 of the 30 avocado-*.conf machines list uuu-emmc in
# STONE_PROVISIONING, and the other 25 would build a native package for a
# script they never deploy.
DEPENDS:append:stone-uuu-emmc = " libubootenv-native"

SRC_URI += " \
    file://rootdisk.conf \
"

SRC_URI:append:stone-uuu-emmc = " \
    file://stone-provision-uuu-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  # The manifests name a rootfs dm-verity hash image (rootfs_hash) for the
  # per-slot hash partitions. A project build produces the real tree when
  # rootfs.image.verity is on; the distro's own bundle never does - its FIT
  # carries no root hash, so the partition content is never read - but stone
  # validate/bundle still require the file. Same zero-filled placeholder the
  # runtime build writes when verity is off.
  truncate -s 4096 ${DEPLOYDIR}/avocado-image-rootfs-${MACHINE_SHORT_NAME}.verity
}

do_deploy:append:stone-uuu-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-uuu-emmc.sh ${DEPLOYDIR}/stone-provision-uuu-emmc.sh
}

# With AHAB on, the boot partition carries a signed OS container instead of a
# bare Image, dtb and initramfs. U-Boot's booti takes the container address and
# reads the kernel and fdt destinations back out of it (cmd/booti.c), and the
# initramfs is bundled into the kernel Image, so none of the three is loaded.
#
# Dropping the initramfs is not just tidiness: a copy left on disk is one an
# attacker can point a modified environment at.
#
# The boot partitions grow to 256 MiB with it. Bundling embeds the initramfs
# uncompressed - oe-core's copy_initramfs unpacks the .cpio.zst and the kernel
# stores what it is given (usr/Makefile:6) - so the container lands near 170 MB
# rather than the ~66 MB the compressed archive would suggest. Compressing it
# back is not reachable from a config fragment: the compression choice is
# `depends on INITRAMFS_SOURCE != ""` (usr/Kconfig:112) and that variable
# reaches the kernel only as a make argument during do_bundle_initramfs, so the
# symbol is inactive when .config is written. Buying the space costs disk this
# board has; the alternative costs an oe-core class override to re-check on
# every uprev.
#
# recovery grows too. It is bootpart 5 in the U-Boot environment, so it holds a
# boot filesystem like boot-a and boot-b, and a recovery slot that cannot hold
# the image it is meant to recover from is worse than no recovery slot.
#
# Rewritten here rather than forked into a second machine JSON: the file list
# is the only difference, and two near-identical manifests drift.
DEPENDS:append = "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', ' avocado-os-container', '', d)}"
do_compile[depends] += "${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'avocado-os-container:do_deploy', '', d)}"

do_deploy:append() {
    if ${@bb.utils.contains('DISTRO_FEATURES', 'ahab', 'true', 'false', d)}; then
        _m="${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json"
        jq '(.storage_devices.rootdisk.images.boot.build_args.files) |=
                (map(select(. != "Image"
                            and (endswith(".dtb") | not)
                            and (startswith("avocado-image-initramfs") | not)))
                 + ["os_cntr_signed.bin"])
            | .storage_devices.rootdisk.images.boot.size = 256
            | (.storage_devices.rootdisk.partitions[]
               | select(.name == "boot-a" or .name == "boot-b" or .name == "recovery")
               | .size) = 256' \
            "$_m" > "$_m.ahab" || bbfatal "failed to rewrite the boot file list for AHAB"
        mv "$_m.ahab" "$_m"

        if ! grep -q 'os_cntr_signed.bin' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still has no signed OS container"
        fi
        if grep -q '"Image"' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still ships a bare Image"
        fi
        if grep -q 'avocado-image-initramfs' "$_m"; then
            bbfatal "AHAB is enabled but the boot partition still ships a loose initramfs; it rides inside the signed container, and a second copy would be unauthenticated as well as redundant"
        fi

        # Assert the container fits before stone tries to write it. Without this
        # the failure surfaces from inside the FAT builder as "Failed to write
        # to file 'os_cntr_signed.bin': No space left on device", which reads
        # like a full disk and sent this exact investigation after the host
        # filesystem first time round.
        _cntr="${DEPLOY_DIR_IMAGE}/os_cntr_signed.bin"
        if [ -f "$_cntr" ]; then
            _have=$(stat -Lc%s "$_cntr")
            _cap_mib=$(jq -r '.storage_devices.rootdisk.images.boot.size' "$_m")
            # Arithmetic via awk rather than $(( )): bitbake's shell parser
            # raises NotImplementedError on $(( while collecting task
            # dependencies, so the recipe fails to parse rather than to run.
            #
            # 4 MiB covers the FAT32 reserved sectors, both tables and the root
            # directory, which the container shares the partition with.
            if awk -v h="$_have" -v c="$_cap_mib" 'BEGIN { exit !(h > c * 1048576 - 4194304) }'; then
                bbfatal "signed OS container is ${_have} bytes and does not fit a ${_cap_mib} MiB boot partition; grow images.boot.size and the boot-a/boot-b/recovery partitions together"
            fi
        fi
    fi
}

# Stage an EFI System Partition layout in the boot slot so the kernel can be
# entered through its EFI stub, which is what populates efivarfs for the
# userspace boot-integrity reporter. Injected into the deployed manifest rather
# than written into stone-imx93-frdm.json because it is PoC-only: the payload
# is an EFI-stub kernel that the default boot path never executes, and staging a
# second bootable kernel in the ESP of a board whose AHAB lifecycle is open
# hands anyone who can write the boot medium a differently-configured kernel for
# free. A default build's manifest stays byte-identical.
#
# The DTB comes from FIT_CONF_DEFAULT_DTB rather than a literal name so the EFI
# path and the FIT path cannot drift onto different device trees. The machine
# conf pins that variable precisely because a KERNEL_DEVICETREE reorder would
# otherwise boot a wrong-pinmux DTB with no build error; hardcoding here would
# reintroduce that silent failure on the second boot path.
#
# devtool-debt: appends to build_args.files, so nothing detects two entries
# claiming one output path.
# Ceiling: this block is the only writer of the boot partition's file list.
# Upgrade trigger: stone gains build_args.files_append on a revision this layer
# pins - then move these two entries there and drop this marker.
#
# files_append is the better field and is deliberately NOT used yet. stone runs
# merge_fat_files() over (files, files_append), which dedups by output path and
# hard-errors when two entries claim one output with different inputs
# (manifest.rs:718, called from bundle.rs:395), and it is the field stone's own
# --overlay mechanism populates. But stone_2.2.0.bb pins SRCREV b58a6411, which
# predates that support, and the commit adding it is not on stone's origin/main
# either. An older stone does not reject the unknown key - it ignores it, builds
# a FAT with only the base `files`, and exits 0. Verified the hard way: a green
# build produced a boot.img containing fitImage and neither EFI payload, because
# the stone binary in the build carried no `files_append` string at all. Writing
# to a field the pinned tool has never heard of fails silently and green, which
# is worse than having no conflict detection.
#
# Both inputs are deployed unconditionally by linux-imx, so neither depends on
# the PoC feature being on.
AVOCADO_BOOT_INTEGRITY_POC = "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', '1', '0', d)}"

# Wrapped in an `if` rather than guarded by an early `return`, for the reason
# spelled out in u-boot-imx_%.bbappend's do_compile:prepend: bitbake concatenates
# every :append into ONE shell function with the recipe's own task body, so a
# `return` here ends do_deploy rather than this block, silently skipping whatever
# append was concatenated after it. Less damaging in an :append than in a
# :prepend, which is why this one never surfaced - but it is the same defect and
# it depends on parse order to stay harmless.
do_deploy:append:avocado-imx93-frdm() {
  if [ "${AVOCADO_BOOT_INTEGRITY_POC}" = "1" ]; then
    bbwarn "boot-integrity-poc: staging EFI/BOOT/BOOTAA64.EFI and ${FIT_CONF_DEFAULT_DTB} in the boot partition of stone-${MACHINE_SHORT_NAME}.json. This is PoC scaffolding: the staged kernel is unauthenticated and writable by anyone with access to the boot medium."

    manifest="${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json"
    jq --arg dtb "${FIT_CONF_DEFAULT_DTB}" \
      '.storage_devices.rootdisk.images.boot.build_args.files += [
         {"in": "Image", "out": "EFI/BOOT/BOOTAA64.EFI"},
         {"in": $dtb, "out": $dtb}
       ]' \
      "$manifest" > "$manifest.efi-poc"
    mv "$manifest.efi-poc" "$manifest"
  fi
}

# Payload signing for the EFI boot path. sbsigntool-native supplies sbsign and
# sbverify; sb-keys generates the db key pair, whose private half never leaves
# AVOCADO_SB_KEYS_DIR on the build host (sb-keys.bb deploys and installs only
# .crt/.der, deliberately).
#
# Gated exactly as the shell block below is - this machine, this token - rather
# than added unconditionally: the other 29 avocado-* machines have no EFI boot
# path, and a bare DEPENDS would build a native signing tool for a step they
# never run.
DEPENDS:append:avocado-imx93-frdm = "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', ' sb-keys sbsigntool-native', '', d)}"

# Image comes from linux-imx's own do_deploy; nothing this recipe builds
# produces it. Declared rather than left to devspec task order or to whatever
# else happens to pull the kernel in first, because the build graph knows
# nothing about either: on a clean TMPDIR or an sstate-restored build this task
# would otherwise reach the signing step with no Image in DEPLOY_DIR_IMAGE, and
# a developer's warm TMPDIR hides that indefinitely.
do_deploy[depends] += "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', ' virtual/kernel:do_deploy', '', d)}"

# Sign a COPY of the deployed kernel and leave the original alone.
#
# Image is deployed unconditionally by linux-imx and feeds the FIT path as well
# as this one, so signing it in place would change what a token-absent build
# consumes - breaking this change's contract that the FIT path is untouched -
# and would also destroy the unsigned payload the harness's
# signed_payload_refused mode needs in order to prove the firmware refuses one.
#
# Written to DEPLOYDIR rather than straight into DEPLOY_DIR_IMAGE so the
# artifact travels with this recipe's own sstate; deploy.bbclass copies it out.
#
# Same `if` wrapper and the same reason as the block above: bitbake concatenates
# every :append into ONE shell function with the recipe's task body, so a bare
# `return` at statement position would end the WHOLE do_deploy.
do_deploy:append:avocado-imx93-frdm() {
  if [ "${AVOCADO_BOOT_INTEGRITY_POC}" = "1" ]; then
    # The two halves of one token. This recipe cannot see whether the U-Boot
    # recipe enrolled anything, and that recipe cannot see whether the payload
    # was signed - so each enforces the half it can observe. u-boot-imx's
    # do_deploy writes db.fingerprint only after proving the seed really reached
    # $(srctree), which makes its presence the evidence that enrolment happened.
    # Absent, under a set token, means the bootloader trusts nothing while we
    # are about to hand it a payload signed for a key database that was never
    # enrolled.
    _fp="${DEPLOY_DIR_IMAGE}/sb-keys/db.fingerprint"
    if [ ! -f "$_fp" ]; then
        bbfatal "boot-integrity-poc: ${DEPLOY_DIR_IMAGE}/sb-keys/db.fingerprint is absent, so no U-Boot in this build enrolled a key database. Refusing to sign an EFI payload for a bootloader that would report enforcement it cannot perform."
    fi

    _crt="${AVOCADO_SB_KEYS_DIR}/db.crt"
    _key="${AVOCADO_SB_KEYS_DIR}/db.key"
    if [ ! -f "$_crt" ] || [ ! -f "$_key" ]; then
        bbfatal "boot-integrity-poc: the db key pair is absent from ${AVOCADO_SB_KEYS_DIR}. sb-keys' gen-sbkeys.sh produces db.crt and db.key; this recipe DEPENDS on sb-keys under the same gate."
    fi

    # Changing a certificate's CONTENT at an unchanged AVOCADO_SB_KEYS_DIR path
    # does not invalidate sstate, so a cached signed payload can otherwise pair
    # with a freshly-built bootloader carrying a different db - which bricks the
    # board on its next boot with no build error anywhere. Fatal, never a
    # warning: a warning here ships exactly that image.
    _have=$(sha256sum "$_crt" | awk '{print $1}')
    _want=$(awk 'NR==1 {print $1}' "$_fp")
    if [ "$_have" != "$_want" ]; then
        bbfatal "boot-integrity-poc: db.crt hashes ${_have} but the bootloader in this build enrolled ${_want}. The payload would be signed by a key the firmware does not trust. Rebuild u-boot-imx and sb-keys together, or clean this recipe's sstate."
    fi

    _img="${DEPLOY_DIR_IMAGE}/Image"
    if [ ! -f "$_img" ]; then
        bbfatal "boot-integrity-poc: ${DEPLOY_DIR_IMAGE}/Image is absent at do_deploy. linux-imx deploys it; do_deploy[depends] on virtual/kernel:do_deploy should have ordered that before this task."
    fi

    if ! sbsign --key "$_key" --cert "$_crt" \
                --output ${DEPLOYDIR}/Image.signed "$_img"; then
        bbfatal "boot-integrity-poc: sbsign failed on ${_img}. The EFI-stub kernel must be a PE/COFF image for sbsign to attach a signature to it."
    fi

    # sbsign exiting 0 is not evidence the output carries a signature this db
    # validates - read the output back rather than trusting the writer. Without
    # this an unsigned or wrongly-signed payload ships on a green build and the
    # failure surfaces as a board that will not boot.
    if ! sbverify --cert "$_crt" ${DEPLOYDIR}/Image.signed; then
        bbfatal "boot-integrity-poc: sbverify rejected ${DEPLOYDIR}/Image.signed against db.crt, so sbsign produced an output this key database does not validate."
    fi
  fi
}
