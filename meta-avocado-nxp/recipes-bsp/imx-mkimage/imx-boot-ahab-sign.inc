# AHAB-sign the assembled imx-boot container.
#
# Pulled in by imx-boot_%.bbappend only when the `ahab` DISTRO_FEATURE is set,
# which is opt-in: signing needs private keys that cannot live in the build, so
# a target that has not been given any must not silently produce an unsigned
# image that looks signed. The key handling and that fail-closed check live in
# avocado-ahab-sign.bbclass, shared with the OS container signer.
#
# Container 0 is the ELE firmware and is signed by NXP - this touches only the
# OEM container carrying SPL, ATF and U-Boot.

inherit avocado-ahab-sign

# Which imx-mkimage target gets signed. Defaults to the first entry of
# IMXBOOT_TARGETS, matching what the unsigned deploy links `imx-boot` to.
AHAB_SIGN_TARGET ?= "${@ d.getVar('IMXBOOT_TARGETS').split()[0] }"

AHAB_UNSIGNED_IMAGE = "${UUU_BOOTLOADER}-${MACHINE}-sd.bin-${AHAB_SIGN_TARGET}"
AHAB_SIGNED_IMAGE = "signed-${AHAB_UNSIGNED_IMAGE}"

do_sign_ahab() {
    avocado_ahab_sign "${B}/${AHAB_UNSIGNED_IMAGE}" "${B}/${AHAB_SIGNED_IMAGE}"
}

do_compile[postfuncs] += "do_sign_ahab"

do_deploy:append() {
    install -m 0644 "${B}/${AHAB_SIGNED_IMAGE}" "${DEPLOYDIR}/${AHAB_SIGNED_IMAGE}"
    # Replace the unsigned image the bootloader consumers pick up by name, so a
    # target that asked for AHAB cannot be provisioned with the unsigned one by
    # forgetting to change a path.
    ln -sf "${AHAB_SIGNED_IMAGE}" "${DEPLOYDIR}/${UUU_BOOTLOADER}"
}
