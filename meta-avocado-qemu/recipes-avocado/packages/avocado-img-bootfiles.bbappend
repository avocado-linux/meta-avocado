# Bundle the bootloader artifact (u-boot.rom for qemux86-64, etc.) into the
# avocado-img-bootfiles RPM and ensure this recipe's task signatures flow
# through to bootloader changes, so a u-boot rebuild forces a rebuild of
# this RPM rather than letting sstate restore a stale prior version.
#
# Surfaced during the wrynose U-Boot bump (2024.01 → 2026.01) when a
# Kconfig rename in env-mmc.cfg required a u-boot rebuild but the
# resulting fresh u-boot.rom never made it into the staged RPM —
# avocado-img-bootfiles' do_compile[depends] only listed avocado-stone
# and virtual/kernel, so its task hashes didn't change when u-boot
# rebuilt and sstate served the prior package output. See
# docs/migrations/scarthgap-to-wrynose.md #46 for the diagnosis.
#
# A UEFI target stages systemd-boot into the ESP through stone rather than
# bundling a bootloader artifact here, and declares no virtual/bootloader at all -
# so gate the dep on AVOCADO_BOOTLOADER (a machine property, not the machine name;
# varflags take no :append:<override>). Ungated, the dep has nothing to resolve
# against once qemux86-64 moves to UEFI with the encrypted-/var work, and the
# build stops on "Nothing PROVIDES virtual/bootloader".
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'virtual/bootloader:do_deploy', '', d)}"
