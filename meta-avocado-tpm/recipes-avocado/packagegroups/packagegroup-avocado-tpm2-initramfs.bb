DESCRIPTION = "Packagegroup for TPM2 unseal support in initramfs (no D-Bus, daemon-free)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    tpm2-tools \
"
