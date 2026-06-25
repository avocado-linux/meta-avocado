DESCRIPTION = "Packagegroup for TPM2 runtime on TPM2-enabled Avocado targets"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    tpm2-tss \
    tpm2-tools \
"
