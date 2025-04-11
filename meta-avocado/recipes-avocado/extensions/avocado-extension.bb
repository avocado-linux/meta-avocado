SUMMARY = "Generic Avocado extension package"
DESCRIPTION = "Base recipe for packaging Avocado OS extensions"
LICENSE = "Apache-2.0"

# Default values that should be overridden in derived recipes
PV ?= "1.0"
EXTIMG ?= "unknown"
EXT_ID ?= "unknown"

# Dependencies
RDEPENDS:${PN} = "systemd"
do_install[depends] += "${EXTIMG}:do_image_complete"

# Paths for extension deployment
SYSEXT_DESTDIR = "/usr/lib/extensions"
CONFEXT_DESTDIR = "/usr/lib/confexts"

# Target machine - can be overridden
EXTIMG_MACHINE ??= "${MACHINE}"

# Allow overriding source image details
EXTIMG_NAME ?= "${EXTIMG}-${EXTIMG_MACHINE}.rootfs"
EXTIMG_DEPLOY_DIR ?= "${DEPLOY_DIR_IMAGE}"

# No need for compilation
do_configure[noexec] = "1"
do_compile[noexec] = "1"

# Custom do_install to copy the extension image
do_install() {
    # Create directories
    install -d ${D}${SYSEXT_DESTDIR}
    install -d ${D}${CONFEXT_DESTDIR}
    
    # Find the latest extension image by looking for a timestamp pattern
    LATEST_EXT=$(find ${EXTIMG_DEPLOY_DIR} -name "${EXTIMG_NAME}*.tar.bz2" | sort -r | head -1)
    
    if [ -z "$LATEST_EXT" ]; then
        bbfatal "Cannot find extension image: ${EXTIMG_NAME}*.tar.bz2"
    fi
    
    bbnote "Using extension image: $LATEST_EXT"
    
    # Copy the extension image to sysext location
    install -m 0644 $LATEST_EXT ${D}${SYSEXT_DESTDIR}/${EXT_ID}.tar.bz2
    
    # Check if the extension contains /etc files
    if tar -tjf $LATEST_EXT | grep -q "^etc/\|^./etc/"; then
        bbnote "Extension contains /etc files, creating confext symlink"
        # Create symlink for confext (configuration extension)
        ln -sf ${SYSEXT_DESTDIR}/${EXT_ID}.tar.bz2 ${D}${CONFEXT_DESTDIR}/${EXT_ID}.tar.bz2
    else
        bbnote "Extension does not contain /etc files, skipping confext symlink"
    fi
}

# Files packaged in the RPM
FILES:${PN} = "${SYSEXT_DESTDIR}/${EXT_ID}.tar.bz2 ${CONFEXT_DESTDIR}/${EXT_ID}.tar.bz2"

# Post-install and post-uninstall scripts
pkg_postinst:${PN}() {
    # Refresh extensions after installation
    if [ -x $D${systemd_unitdir}/systemd ]; then
        systemctl -q --root=$D restart systemd-sysext || true
        systemctl -q --root=$D restart systemd-confext || true
    fi
}

pkg_postrm:${PN}() {
    # Refresh extensions after removal
    if [ -x $D${systemd_unitdir}/systemd ]; then
        systemctl -q --root=$D restart systemd-sysext || true
        systemctl -q --root=$D restart systemd-confext || true
    fi
}

# Inhibit QA warnings about missing build dependencies - we don't need them
INSANE_SKIP:${PN} += "build-deps"

# Architecture can be target-specific since extensions might contain binaries
PACKAGE_ARCH = "${MACHINE_ARCH}"
