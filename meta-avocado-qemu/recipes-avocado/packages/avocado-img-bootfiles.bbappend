# A U-Boot target bundles the bootloader artifact (u-boot.rom, etc.) into the
# avocado-img-bootfiles RPM and flows the bootloader's task signatures through, so
# a u-boot rebuild forces this RPM to rebuild rather than letting sstate restore a
# stale prior version.
#
# Surfaced during the wrynose U-Boot bump (2024.01 -> 2026.01) when a Kconfig
# rename in env-mmc.cfg required a u-boot rebuild but the fresh u-boot.rom never
# made it into the staged RPM: do_compile[depends] only listed avocado-stone and
# virtual/kernel, so its task hashes didn't change when u-boot rebuilt and sstate
# served the prior package output. See docs/migrations/scarthgap-to-wrynose.md #46.
#
# UEFI targets stage systemd-boot into the ESP via stone, not here, and declare no
# virtual/bootloader - so this dep is gated on AVOCADO_BOOTLOADER (a machine
# property, not the machine name; varflags take no :append:<override>).
do_compile[depends] += "${@bb.utils.contains('AVOCADO_BOOTLOADER', 'uboot', 'virtual/bootloader:do_deploy', '', d)}"
