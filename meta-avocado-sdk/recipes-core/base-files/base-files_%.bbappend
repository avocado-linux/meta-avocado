do_install:append() {
    ln -s lib ${D}/lib64
}

FILES:${PN} += "/lib64"
