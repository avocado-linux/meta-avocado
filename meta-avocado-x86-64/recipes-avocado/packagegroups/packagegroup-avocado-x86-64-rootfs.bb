DESCRIPTION = "Packagegroup for Intel x86-64 base rootfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# EFI boot management - required for A/B slot activation via efibootmgr
EFI_TOOLS = " \
  efibootmgr \
  efivar \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
"
