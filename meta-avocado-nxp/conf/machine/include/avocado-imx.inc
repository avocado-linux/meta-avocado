MACHINEOVERRIDES =. "avocado-imx:"

# u-boot-imx is deliberately NOT pinned here. That is a decision, not an
# omission, and it is recorded so the next capsule-style build break gets a
# config fragment rather than another version pin.
#
# The break it would be reaching for is real: meta-imx wrynose-6.18.20 ships
# u-boot-imx 2026.04, whose stock defconfigs enable EFI capsule-on-disk (its
# ESL step shells out to efitools' cert-to-efi-sig-list, which no layer here
# provides) and USB DFU (no set_dfu_alt_info for these boards), so do_compile
# fails on imx8mp-evk and imx91/93/95-frdm alike.
#
# disable-unused-vendor-features.cfg turns both off, and the u-boot-imx
# bbappend adds it via SRC_URI:append:class-target - unconditionally, for every
# board and every version. That fragment is what fixes the build. A pin on top
# of it fixes nothing further, and it is not free:
#
#   - It makes every flash from a pinned tree a silent bootloader VERSION
#     downgrade, turning a config-only change into config-plus-version. Flashed
#     onto a board whose only recovery route lives in the bootloader being
#     replaced, that is a brick - which happened on the bench and cost a uuu
#     recovery.
#   - 2025.04 carries CONFIG_SYS_BOOTM_LEN=0x4000000 against 2026.04's
#     0x8000000, halving the bootm size budget for a FIT that already uses
#     about 60% of its address window.
#
# Both values read from real built .config files, not from the defconfigs.

# meta-imx-bsp's imx-base-extend.inc prefers libcamera 0.7.1.imx on mx95 /
# mx8mm / mx8ulp, but that recipe lives in meta-imx-sdk (needs the
# freescale-distro layer set), which we do not include -- so every parse warns
# "preferred version 0.7.1.imx of libcamera not available". Nothing in our
# images pulls libcamera; drop the preference (`=` beats the inc's `??=`) and
# let the meta-openembedded / meta-freescale 0.6.0 recipes resolve normally.
PREFERRED_VERSION_libcamera = ""
