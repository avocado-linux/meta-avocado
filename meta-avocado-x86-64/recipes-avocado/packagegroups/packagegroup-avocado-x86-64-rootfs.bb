DESCRIPTION = "Packagegroup for Intel x86-64 base rootfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# A/B slot activation: avocadoctl's efibootmgr slot action runs efibootmgr
# from the rootfs and looks the target slot up by an entry label (boot-a,
# boot-b) that avocado-efi-slot-entries creates at boot. Without it an OS
# update cannot activate the new slot. The AMD machine already ships it.
EFI_TOOLS = " \
  efibootmgr \
  efivar \
  avocado-efi-slot-entries \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
"
