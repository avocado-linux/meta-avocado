DESCRIPTION = "Packagegroup for arm64 UEFI base rootfs packages (loaded before extensions)"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup nospdx

PACKAGES = "${PN}"

# EFI boot management - required for A/B slot activation via efibootmgr
EFI_TOOLS = " \
  efibootmgr \
  efivar \
"

# Login on the monitor: getty@tty1 (the bare-template preset never yields one)
CONSOLE_TOOLS = " \
  systemd-vt-console-preset \
"

RDEPENDS:${PN} = " \
  ${EFI_TOOLS} \
  ${CONSOLE_TOOLS} \
"
