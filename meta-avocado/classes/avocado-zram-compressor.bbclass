# Ship zram's default compressor when this kernel builds it as a module.
#
# The distro leaves the zram algorithm to the kernel default
# (zram-generator.conf, #434). From 6.12 zram carries its own backends, built
# into zram.ko, so the default is always there. Before 6.12 zram reaches the
# compressor through the crypto API, and on kernels that build it =m (L4T 6.8:
# CRYPTO_LZO=m, default lzo-rle) nothing pulled the module in. zram-generator
# sets the device up in the initramfs, where the module was missing, and 6.8
# oopses in zcomp_stream_get() on the first write from mkswap: every boot
# panicked.
#
# Read from the kernel's own .config, so no kernel has to be named here.
# Inherited by avocado-kernel-modules-packagegroup.inc; it lives in the base
# layer because every target has that one and not every kas target pulls in
# meta-avocado-distro.
#
# Only the kernel default is covered. A project that sets its own algorithm in
# a zram-generator config installs that compressor's module itself (an
# extension).

# Crypto API name -> config symbol. The module is named after the algorithm.
AVOCADO_ZRAM_CRYPTO_SYMBOLS = "lzo:CRYPTO_LZO lzo-rle:CRYPTO_LZO lz4:CRYPTO_LZ4 lz4hc:CRYPTO_LZ4HC zstd:CRYPTO_ZSTD 842:CRYPTO_842 deflate:CRYPTO_DEFLATE"

def avocado_zram_compressor_module(config):
    """The module to ship for zram's default compressor, or None."""
    import re
    if re.search(r'^CONFIG_ZRAM_BACKEND_\w+=y$', config, re.M):
        return None  # 6.12+: zram's own backends, built into zram.ko
    alg = re.search(r'^CONFIG_ZRAM_DEF_COMP="([^"]+)"$', config, re.M)
    if not alg:
        return None
    return alg.group(1)

def avocado_zram_compressor_rdepends(d):
    import os, re
    if not bb.utils.contains('DISTRO_FEATURES', 'zram', True, False, d):
        return
    path = os.path.join(d.getVar('B'), '.config')
    if not os.path.exists(path):
        return
    config = open(path).read()
    alg = avocado_zram_compressor_module(config)
    if not alg:
        return
    symbols = dict(e.split(':') for e in d.getVar('AVOCADO_ZRAM_CRYPTO_SYMBOLS').split())
    symbol = symbols.get(alg)
    if not symbol:
        bb.fatal("zram default compressor '%s' has no entry in AVOCADO_ZRAM_CRYPTO_SYMBOLS" % alg)
    if not re.search(r'^CONFIG_%s=m$' % symbol, config, re.M):
        return  # built in (or absent, which zram's Kconfig does not allow)
    module = 'kernel-module-%s-%s' % (alg, d.getVar('KERNEL_VERSION'))
    for pg in ('packagegroup-avocado-rootfs-modules', 'packagegroup-avocado-initramfs-modules'):
        d.appendVar('RDEPENDS:' + pg, ' ' + module)
    bb.note("zram default compressor %s is a module: %s" % (alg, module))

# A function of its own: a :prepend is pasted into populate_packages' body, so
# an early return there would skip the kernel's whole package split.
python populate_packages:prepend() {
    avocado_zram_compressor_rdepends(d)
}
