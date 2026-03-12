do_install:prepend:class-native() {
    # Unfortunately, meta-synaptics expects the debian directory to be there withouth it the build fails with:
    # install: cannot stat '/work/build/tmp/work/x86_64-linux/android-tools-native/5.1.1.r37/git/debian/out/system/core/simg2simg': No such file or directory
    mkdir -p ${S}/debian/out/system/core/
    touch ${S}/debian/out/system/core/simg2simg
}
