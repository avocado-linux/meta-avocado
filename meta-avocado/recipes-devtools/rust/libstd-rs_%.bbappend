# Fix for Rust 1.90.0: deps directory now contains subdirectories
# that need to be copied recursively during install
do_install () {
    mkdir -p ${D}${rustlibdir}

    # With the incremental build support added in 1.24, the libstd deps directory also includes dependency
    # files that get installed. Those are really only needed to incrementally rebuild the libstd library
    # itself and don't need to be installed.
    rm -f ${B}/target/${RUST_TARGET_SYS}/${BUILD_DIR}/deps/*.d
    cp -r ${B}/target/${RUST_TARGET_SYS}/${BUILD_DIR}/deps/* ${D}${rustlibdir}
}

# Include rmeta subdirectories added in Rust 1.90.0
FILES:${PN} += "${rustlibdir}/*"

