SUMMARY = "UEFI Secure Boot and FIT image signing key generation recipe"
DESCRIPTION = "Generates the PK/KEK/db/dbx key chain for UEFI Secure Boot, plus \
a separate FIT key used to sign FIT images for verified boot. \
Self-signed RSA 2048 / SHA256 certificates produced at build time. \
Private keys are never installed to the target."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# openssl-native mints the keys and is needed on every machine. The other two
# serve the UEFI variable seed only - sbsiglist builds the EFI signature lists,
# python3-native packs them into U-Boot's variable-store container - so they are
# pulled in only where that seed is actually built.
#
# That conditional is not tidiness. sbsigntool exists ONLY in vendor BSP layers
# (meta-imx/meta-imx-bsp and meta-tegra); meta-openembedded carries no such
# recipe. This recipe lives in machine-agnostic meta-avocado and has no
# COMPATIBLE_MACHINE, so an unconditional DEPENDS breaks `bitbake sb-keys` on
# every non-NXP, non-Tegra target - qemu, raspberrypi, rockchip, stm, renesas,
# alif, qcom, synaptics, x86-64 - with `Nothing PROVIDES 'sbsigntool-native'`,
# for a seed those boards never consume. The active dm-verity and sysext-signing
# work targets rpi and x86-64 and would hit exactly this.
#
# The upstream fix is for sbsigntool and efitools to live in meta-oe rather than
# in each vendor layer; until they do, gate rather than assume. The alternative
# pattern - the layer that needs the tool carries its own recipe, which is what
# meta-secure-core does - is the fallback if the gate ever has to go.
DEPENDS = "openssl-native"
DEPENDS:append = "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', ' sbsigntool-native python3-native', '', d)}"

SRC_URI = "file://gen-sbkeys.sh file://gen-efi-seed.sh"

# file://-only recipe: sources land in UNPACKDIR on wrynose, and the default
# S (${UNPACKDIR}/${BP}) never exists, which do_unpack warns about on every
# build. Point S at where the files actually are, as avocado-users does.
S = "${UNPACKDIR}"

# Output directory for generated keys (override per-developer to a stable path
# outside the build tree; excluded from sstate hashing via BB_BASEHASH_IGNORE_VARS
# in avocado-security.inc).
AVOCADO_SB_KEYS_DIR ?= "${WORKDIR}/sb-keys"

# Run do_install on every build so callers always have fresh cert references,
# even when the keys already exist (idempotency is enforced inside gen-sbkeys.sh).
do_install[nostamp] = "1"

do_compile() {
    install -d "${AVOCADO_SB_KEYS_DIR}"
    chmod +x "${UNPACKDIR}/gen-sbkeys.sh"
    SBKEYS_DIR="${AVOCADO_SB_KEYS_DIR}" "${UNPACKDIR}/gen-sbkeys.sh"
}

# Runs after gen-sbkeys.sh so PK/KEK/db certificates already exist. Produces the
# UEFI variable seed that CONFIG_EFI_VARIABLES_PRESEED compiles into U-Boot, so
# the board leaves setup mode with no first-boot enrolment window.
# Gated on the same token as the DEPENDS above: without sbsigntool-native on the
# sysroot this cannot run at all, so the two must agree or the recipe fails on
# the boards the gate exists to spare.
do_compile:append() {
    if [ "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', '1', '0', d)}" = "1" ]; then
        chmod +x "${UNPACKDIR}/gen-efi-seed.sh"
        SBKEYS_DIR="${AVOCADO_SB_KEYS_DIR}" "${UNPACKDIR}/gen-efi-seed.sh"
    fi
}

do_install() {
    install -d "${D}${datadir}/avocado/sb-keys"

    for cert in PK KEK db dbx FIT; do
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" \
                "${D}${datadir}/avocado/sb-keys/${cert}.crt"
        fi
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.der" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.der" \
                "${D}${datadir}/avocado/sb-keys/${cert}.der"
        fi
        # Private .key files are intentionally NOT installed.
    done
}

inherit deploy

do_deploy() {
    install -d "${DEPLOYDIR}/sb-keys"

    for cert in PK KEK db dbx FIT; do
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" \
                "${DEPLOYDIR}/sb-keys/${cert}.crt"
        fi
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.der" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.der" \
                "${DEPLOYDIR}/sb-keys/${cert}.der"
        fi
    done

    # The UEFI variable seed. Deployed, never installed: it is consumed by the
    # U-Boot build, not shipped to the rootfs.
    #
    # Guarded like the five cert installs above, and for a sharper reason than
    # symmetry: do_compile only writes this file under the boot-integrity-poc
    # token, and AVOCADO_SB_KEYS_DIR defaults outside tmp/ (avocado-security.inc)
    # so emptying it to rotate keys does not invalidate do_compile's stamp. An
    # unguarded install therefore fails with `cannot stat .../ubootefi.var`,
    # pointing at the deploy step rather than at the generator that was skipped.
    if [ -f "${AVOCADO_SB_KEYS_DIR}/ubootefi.var" ]; then
        install -m 0644 "${AVOCADO_SB_KEYS_DIR}/ubootefi.var" \
            "${DEPLOYDIR}/sb-keys/ubootefi.var"
    fi

    # The manifest travels WITH the seed, and both consumers read it rather than
    # re-hashing this directory: u-boot's do_deploy for the db.fingerprint it
    # publishes, and boot-integrity for the on-device corroboration reference.
    # Deploying one without the other would leave a consumer silently falling
    # back to the live key directory, which is the divergence the manifest
    # exists to remove.
    if [ -f "${AVOCADO_SB_KEYS_DIR}/ubootefi.var.manifest" ]; then
        install -m 0644 "${AVOCADO_SB_KEYS_DIR}/ubootefi.var.manifest" \
            "${DEPLOYDIR}/sb-keys/ubootefi.var.manifest"
    fi

    # The rival variable store, for the HITL precedence test. Deployed, never
    # installed, and never compiled into anything - avocado-stone stages it onto
    # the ESP under a distinct name so the harness can substitute it for the real
    # store and confirm the compiled-in seed still wins.
    #
    # Guarded like the seed above because gen-efi-seed.sh only writes it under
    # the boot-integrity-poc token.
    if [ -f "${AVOCADO_SB_KEYS_DIR}/ubootefi.var.adversarial" ]; then
        install -m 0644 "${AVOCADO_SB_KEYS_DIR}/ubootefi.var.adversarial" \
            "${DEPLOYDIR}/sb-keys/ubootefi.var.adversarial"
    fi
}

addtask deploy after do_install before do_build

# Only public certificates and DER-encoded certs ship to the target.
# Private .key files must never appear here.
FILES:${PN} = " \
    ${datadir}/avocado/sb-keys/PK.crt \
    ${datadir}/avocado/sb-keys/PK.der \
    ${datadir}/avocado/sb-keys/KEK.crt \
    ${datadir}/avocado/sb-keys/KEK.der \
    ${datadir}/avocado/sb-keys/db.crt \
    ${datadir}/avocado/sb-keys/db.der \
    ${datadir}/avocado/sb-keys/dbx.crt \
    ${datadir}/avocado/sb-keys/dbx.der \
    ${datadir}/avocado/sb-keys/FIT.crt \
    ${datadir}/avocado/sb-keys/FIT.der \
"
