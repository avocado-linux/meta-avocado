DESCRIPTION = "Packagegroup for Intel x86-64 initramfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# EFI boot management - required for A/B slot activation during early boot
EFI_TOOLS = " \
  efibootmgr \
  efivar \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
"
