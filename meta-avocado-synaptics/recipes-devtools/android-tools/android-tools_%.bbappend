do_install:prepend:class-native() {
    # Unfortunately, meta-synaptics expects the debian directory to be there withouth it the build fails with:
    # install: cannot stat '/work/build/tmp/work/x86_64-linux/android-tools-native/5.1.1.r37/git/debian/out/system/core/simg2simg': No such file or directory
    mkdir -p ${S}/debian/out/system/core/
    touch ${S}/debian/out/system/core/simg2simg
}

# Extend to nativesdk so that img2simg is available on the SDK host for the
# stone-provision-synaimg.sh script (TOOLS:class-nativesdk includes ext4_utils
# which installs img2simg).
BBCLASSEXTEND:append = " nativesdk"

# adbd is not built for nativesdk (not in TOOLS:class-nativesdk), but the base
# recipe's PACKAGES still creates the -adbd sub-package with a dependency on
# ${PN}-conf-configfs, which doesn't exist in a nativesdk context.  Clear it.
RDEPENDS:${PN}-adbd:class-nativesdk = ""
