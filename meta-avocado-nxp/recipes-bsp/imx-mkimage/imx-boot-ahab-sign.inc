# AHAB-sign the assembled imx-boot container with SPSDK.
#
# Pulled in by imx-boot_%.bbappend only when the `ahab` DISTRO_FEATURE is set,
# which is opt-in: signing needs private keys that cannot live in the build, so
# a target that has not been given any must not silently produce an unsigned
# image that looks signed.
#
# The signing step is one SPSDK call on the finished container. `nxpimage ahab
# sign` locates the containers inside flash.bin itself, so there is no CSF to
# generate and no offsets to scrape out of the imx-mkimage log. NXP's cst_signer
# wrapper exists to do that discovery for the CST path; on AHAB it only shells
# this same command, so it is not in the dependency chain here.
#
# Container 0 is the ELE firmware and is signed by NXP - this touches only the
# OEM container that carries SPL, ATF and U-Boot.

# Directory holding the AHAB PKI tree, laid out as `nxpcrypto pki-tree ahab`
# emits it: crts/ for the SRK certificates, keys/ for the private keys. There is
# deliberately no default that works - see the bbfatal in do_sign_ahab.
AVOCADO_AHAB_KEYS_DIR ?= ""

# Which of the four SRKs signs. The fused SRK hash covers the whole table, so
# rotating to another index does not need a re-fuse.
AVOCADO_AHAB_SRK_ID ?= "0"

# SPSDK is a host tool, not a recipe: it is a large Python application and the
# keys it needs are out-of-band anyway, so a hermetic build is not achievable
# for this step regardless. Point this at the directory holding `nxpimage`.
AVOCADO_AHAB_SPSDK_BINDIR ?= ""

SPSDK_KEY_TYPE ?= "secp384r1"
AHAB_SIGNED_IMAGE = "signed-${UUU_BOOTLOADER}-${MACHINE}-sd.bin-${AHAB_SIGN_TARGET}"

# Which imx-mkimage target gets signed. Defaults to the first entry of
# IMXBOOT_TARGETS, matching what the unsigned deploy links `imx-boot` to.
AHAB_SIGN_TARGET ?= "${@ d.getVar('IMXBOOT_TARGETS').split()[0] }"

python () {
    if not bb.utils.contains('DISTRO_FEATURES', 'ahab', True, False, d):
        return
    if not d.getVar('AVOCADO_AHAB_KEYS_DIR'):
        bb.fatal("DISTRO_FEATURES contains 'ahab' but AVOCADO_AHAB_KEYS_DIR is "
                 "unset. Set it to an AHAB PKI tree (see "
                 "meta-avocado-nxp/docs/imx93-srk-pki.md) or drop the feature. "
                 "Refusing to deploy an unsigned bootloader for a target that "
                 "asked for secure boot.")
    if not d.getVar('AVOCADO_AHAB_SPSDK_BINDIR'):
        bb.fatal("DISTRO_FEATURES contains 'ahab' but AVOCADO_AHAB_SPSDK_BINDIR "
                 "is unset. SPSDK provides `nxpimage`, which does the signing; "
                 "install it (`uv tool install spsdk`) and point this at its bin "
                 "directory.")
}

do_sign_ahab() {
    keys="${AVOCADO_AHAB_KEYS_DIR}"
    nxpimage="${AVOCADO_AHAB_SPSDK_BINDIR}/nxpimage"
    unsigned="${B}/${UUU_BOOTLOADER}-${MACHINE}-sd.bin-${AHAB_SIGN_TARGET}"

    if [ ! -x "$nxpimage" ]; then
        bbfatal "nxpimage not executable at $nxpimage"
    fi
    if [ ! -f "$unsigned" ]; then
        bbfatal "no imx-boot container to sign at $unsigned"
    fi

    srk_id="${AVOCADO_AHAB_SRK_ID}"
    signer="$keys/keys/SRK${srk_id}_${SPSDK_KEY_TYPE}_key.pem"
    if [ ! -f "$signer" ]; then
        bbfatal "signing key $signer not found; AVOCADO_AHAB_KEYS_DIR must hold a tree as produced by 'nxpcrypto pki-tree ahab'"
    fi

    # Written out with absolute paths rather than SIG_DATA_PATH-relative ones so
    # a failure names the file it could not find.
    cat > "${B}/spsdk_ahab.yaml" <<EOF
family: mimx9352
revision: latest
srk_set: oem
used_srk_id: $srk_id
signer: $signer
srk_table:
  flag_ca: false
  hash_algorithm: sha384
  srk_array:
    - $keys/crts/SRK0_${SPSDK_KEY_TYPE}_cert.pem
    - $keys/crts/SRK1_${SPSDK_KEY_TYPE}_cert.pem
    - $keys/crts/SRK2_${SPSDK_KEY_TYPE}_cert.pem
    - $keys/crts/SRK3_${SPSDK_KEY_TYPE}_cert.pem
EOF

    "$nxpimage" ahab sign --force \
        -c "${B}/spsdk_ahab.yaml" \
        -b "$unsigned" \
        -o "${B}/${AHAB_SIGNED_IMAGE}"

    if [ ! -f "${B}/${AHAB_SIGNED_IMAGE}" ]; then
        bbfatal "signing reported success but produced no ${AHAB_SIGNED_IMAGE}"
    fi

    # Prove the OEM container actually carries a signature rather than trusting
    # the exit status: an image that merely round-tripped through the tool would
    # still deploy and would only fail on a fused board.
    if ! "$nxpimage" ahab info -f mimx9352 -b "${B}/${AHAB_SIGNED_IMAGE}" \
            | grep -q 'Signed by OEM keys'; then
        bbfatal "${AHAB_SIGNED_IMAGE} carries no OEM signature"
    fi
}

do_compile[postfuncs] += "do_sign_ahab"

do_deploy:append() {
    install -m 0644 "${B}/${AHAB_SIGNED_IMAGE}" "${DEPLOYDIR}/${AHAB_SIGNED_IMAGE}"
    # Replace the unsigned image the bootloader consumers pick up by name, so a
    # target that asked for AHAB cannot be provisioned with the unsigned one by
    # forgetting to change a path.
    ln -sf "${AHAB_SIGNED_IMAGE}" "${DEPLOYDIR}/${UUU_BOOTLOADER}"
}
