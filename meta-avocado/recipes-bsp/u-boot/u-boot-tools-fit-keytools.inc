# fdt_add_pubkey injects a FIT public key into a U-Boot control DTB without
# rebuilding U-Boot - the step that lets a project (avocado build, SDK
# container) make a prebuilt imx-boot enforce its OWN signing key instead of
# the distro's sb-keys one. The tools-only build already produces it
# (tools/Makefile: hostprogs-$(CONFIG_TOOLS_LIBCRYPTO) += fdt_add_pubkey,
# TOOLS_LIBCRYPTO defaults on) alongside fit_info; oe-core's do_install just
# never picks either up. Same uboot-<name> + symlink convention as the
# installs in u-boot-tools.inc. Shared by the u-boot-tools and u-boot-imx-tools
# bbappends; both recipes require the same u-boot-tools.inc install list.
do_install:append() {
    install -m 0755 tools/fdt_add_pubkey ${D}${bindir}/uboot-fdt_add_pubkey
    ln -sf uboot-fdt_add_pubkey ${D}${bindir}/fdt_add_pubkey
    install -m 0755 tools/fit_info ${D}${bindir}/uboot-fit_info
    ln -sf uboot-fit_info ${D}${bindir}/fit_info
}

FILES:${PN}-mkimage += " \
    ${bindir}/uboot-fdt_add_pubkey ${bindir}/fdt_add_pubkey \
    ${bindir}/uboot-fit_info ${bindir}/fit_info \
"
