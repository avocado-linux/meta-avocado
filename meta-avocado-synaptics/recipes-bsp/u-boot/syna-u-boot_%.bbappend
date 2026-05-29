# meta-grinn-astra-bsp's bbappend adds file://${MACHINE}.dts to SRC_URI, which
# resolves to avocado-grinn-astra-1680-sbc.dts — a file that doesn't exist
# upstream. Swap it for the unprefixed Grinn name and copy it back under the
# MACHINE name so upstream's do_configure:append:grinn-astra-1680-platform
# (which references ${WORKDIR}/${MACHINE}.dts) keeps working.
SRC_URI:remove:grinn-astra-platform = "file://${MACHINE}.dts"
SRC_URI:append:grinn-astra-platform = " file://${GRINN_MACHINE}.dts"

do_configure:prepend:grinn-astra-1680-platform() {
	cp ${WORKDIR}/${GRINN_MACHINE}.dts ${WORKDIR}/${MACHINE}.dts
}

# meta-grinn-astra-bsp/recipes-rescue/astra-rescue/syna-u-boot_git.bbappend uses
# a python __anonymous() to map MACHINE → MACHINE_NAME via a hardcoded dict
# that only knows the unprefixed Grinn names. With our avocado- prefix the
# lookup misses and MACHINE_NAME ends up empty, so the rescue's
# do_compile:prepend bbfatals trying to open
# ${S}/boot/u-boot/configs/_suboot_defconfig.
#
# Fighting the anon via override-variants doesn't work — BitBake resolves
# overrides before anon functions run, so d.setVar("MACHINE_NAME", "") in the
# upstream anon clobbers any resolved override value at the end of parse.
# Instead, materialise a file at the broken path during do_configure so the
# existence check passes. The file is never read by the actual U-Boot build
# (which uses ${WORKDIR}/.config built from the CM3 config merge), so any
# sed/echo the rescue bbappend does to it is inert.
do_configure:append:grinn-astra-1680-platform() {
	cp ${S}/boot/u-boot/configs/dolphin_suboot_defconfig \
	   ${S}/boot/u-boot/configs/${MACHINE_NAME}_suboot_defconfig
}
