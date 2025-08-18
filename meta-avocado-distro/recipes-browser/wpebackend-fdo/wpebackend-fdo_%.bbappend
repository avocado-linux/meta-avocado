do_install:append() {
  ln -s libWPEBackend-fdo.so ${D}/${libdir}/libWPEBackend-default.so
}

FILES:${PN} += "${libdir}/libWPEBackend-default.so"
