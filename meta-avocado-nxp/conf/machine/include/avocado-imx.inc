MACHINEOVERRIDES =. "avocado-imx:"

# Every u-boot-imx board (harmless where the bootloader is u-boot-compulab /
# u-boot-variscite): meta-imx wrynose-6.18.20 ships
# 2026.04, whose stock defconfigs enable EFI capsule-on-disk (needs efitools'
# cert-to-efi-sig-list, which no layer here provides) and USB DFU (no
# set_dfu_alt_info for these boards), so do_compile fails on all of them.
# meta-freescale's 2025.04 builds. disable-unused-vendor-features.cfg in the
# u-boot-imx bbappend turns the same options off for whichever version is used.
PREFERRED_VERSION_u-boot-imx = "2025.04"
