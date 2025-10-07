do_compile () {
	oe_runmake HOSTCC="${BUILD_CC}" \
		NOFORTRAN="1" \
		CC="${TARGET_PREFIX}gcc ${TOOLCHAIN_OPTIONS} ${@map_extra_options(d.getVar('TARGET_ARCH', True), d)}" \
		PREFIX=${exec_prefix} \
		CROSS=1 \
		CROSS_SUFFIX=${HOST_PREFIX} \
		NO_STATIC=1 \
		${@bb.utils.contains('PACKAGECONFIG', 'lapack', 'NO_LAPACK=0', 'NO_LAPACK=1', d)} \
		${@bb.utils.contains('PACKAGECONFIG', 'lapacke', 'NO_LAPACKE=0', 'NO_LAPACKE=1', d)} \
		${@bb.utils.contains('PACKAGECONFIG', 'cblas', 'NO_CBLAS=0', 'NO_CBLAS=1', d)} \
		${@bb.utils.contains('PACKAGECONFIG', 'affinity', 'NO_AFFINITY=0', 'NO_AFFINITY=1', d)} \
		${@bb.utils.contains('PACKAGECONFIG', 'openmp', 'USE_OPENMP=1', 'USE_OPENMP=0', d)} \
		${@bb.utils.contains('PACKAGECONFIG', 'dynarch', 'DYNAMIC_ARCH=1', 'DYNAMIC_ARCH=0', d)} \
		BINARY='${@map_bits(d.getVar('TARGET_ARCH', True), d)}' \
		TARGET='${@map_arch(d.getVar('TARGET_ARCH', True), d)}' \
		EXTRALIB="-lgfortran" \
		libs netlib shared
}

