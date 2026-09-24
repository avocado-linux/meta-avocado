DESCRIPTION = "Packagegroup for AMD x86-64 initramfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# avocado-extension-initrd.service verifies a pending OS update inside the
# initrd and runs its commit or rollback there, and on this machine both are
# efibootmgr slot actions. Without the tool in the initramfs they fail, the
# marker is cleared anyway, and a verified update reverts on the next reboot.
EFI_TOOLS = " \
  efibootmgr \
  efivar \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
"
