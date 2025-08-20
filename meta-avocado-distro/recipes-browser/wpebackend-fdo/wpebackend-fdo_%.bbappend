do_install:append() {
  ln -s libWPEBackend-fdo-1.0.so ${D}/${libdir}/libWPEBackend-default.so
}

FILES:${PN} += "${libdir}/libWPEBackend-default.so"
