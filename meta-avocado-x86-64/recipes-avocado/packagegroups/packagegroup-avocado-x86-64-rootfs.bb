DESCRIPTION = "Packagegroup for Intel x86-64 base rootfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# EFI boot management - required for A/B slot activation via efibootmgr.
# avocadoctl's efibootmgr slot action looks the target slot up by an entry
# label that avocado-efi-slot-entries creates.
EFI_TOOLS = " \
  efibootmgr \
  efivar \
  avocado-efi-slot-entries \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
"
