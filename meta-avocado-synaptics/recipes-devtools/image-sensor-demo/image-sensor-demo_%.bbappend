COMPATIBLE_MACHINE:append = " avocado-grinn-astra-1680-sbc "

SRC_URI:remove = " \
	file://image-sensor-start.sh.${MACHINE} \
"

SRC_URI:append = " \
	file://image-sensor-start.sh.${GRINN_MACHINE} \
"

do_install() {
	install -d ${D}${bindir}
	install -m 0755 ${WORKDIR}/image-sensor-start.sh.${GRINN_MACHINE} \
		${D}${bindir}/image-sensor-start.sh
}
