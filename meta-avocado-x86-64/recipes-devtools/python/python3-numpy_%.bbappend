# x86-64-v4 opts out of qemu-usermode (QEMU cannot run AVX-512), so meson has
# no exe_wrapper and numpy's long double probe cannot run. Hand meson the
# answer it would have computed; it holds for every x86-64 glibc target.
do_write_config:append:intel-x86-64-v4() {
    sed -i "/^\[properties\]/a longdouble_format = 'INTEL_EXTENDED_16_BYTES_LE'" ${WORKDIR}/meson.cross
    grep -q "^longdouble_format" ${WORKDIR}/meson.cross
}
