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
do_compile[depends] += "virtual/bootloader:do_deploy"
