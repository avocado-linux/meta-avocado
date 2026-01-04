SUMMARY = "QEMU user-mode emulation binaries for binfmt_misc"
DESCRIPTION = "QEMU user-mode emulation binaries that can be \
registered with binfmt_misc to transparently run binaries built for other \
architectures. Similar to the qemu-user-static package in Debian/Ubuntu."
HOMEPAGE = "http://qemu.org"
LICENSE = "GPL-2.0-only & LGPL-2.1-only"

# Add meta-avocado qemu recipe's files directory to search path for patches and support files
# Also add local files directory for qemu-user-static specific patches
FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../qemu/qemu:"

# Reuse the qemu.inc from meta-avocado which has all the proper setup for 9.2.0
require recipes-devtools/qemu/qemu.inc

# QEMU uses a custom configure script, not autotools - prevent --disable-static from being added
DISABLE_STATIC = ""

# Fix SRC_URI to fetch qemu tarball (qemu.inc uses ${BPN} which would be qemu-user-static)
SRC_URI = "https://download.qemu.org/qemu-${PV}.tar.xz \
           file://powerpc_rom.bin \
           file://run-ptest \
           file://fix-strerrorname_np.patch \
           file://0001-qemu-Add-addition-environment-space-to-boot-loader-q.patch \
           file://0002-apic-fixup-fallthrough-to-PIC.patch \
           file://0004-qemu-Do-not-include-file-if-not-exists.patch \
           file://0005-qemu-Add-some-user-space-mmap-tweaks-to-address-musl.patch \
           file://0006-qemu-Determinism-fixes.patch \
           file://0007-tests-meson.build-use-relative-path-to-refer-to-file.patch \
           file://0008-Define-MAP_SYNC-and-MAP_SHARED_VALIDATE-on-needed-li.patch \
           file://0010-configure-lookup-meson-exutable-from-PATH.patch \
           file://0011-qemu-Ensure-pip-and-the-python-venv-aren-t-used-for-.patch \
           file://0001-sched_attr-Do-not-define-for-glibc-2.41.patch \
           file://0001-linux-user-Fix-USBDEVFS-ioctls.patch \
           "
SRC_URI[sha256sum] = "f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894"

# Set S to match the extracted directory name
S = "${WORKDIR}/qemu-${PV}"

# Need both target and native glib - native is used for build-time tools
# libpcre2 is required by glib-2.0 for static linking
DEPENDS += "glib-2.0 zlib libpcre2 glib-2.0-native linux-libc-headers"

# Override the default PACKAGECONFIG to minimal set for user-mode only
# Enable libusb for USB device passthrough support
PACKAGECONFIG = "libusb"

# List of architectures we want to build for
QEMU_TARGETS = "aarch64 arm i386 x86_64 mips mipsel mips64 mips64el ppc ppc64 ppc64le riscv32 riscv64"

# Build the --target-list argument from QEMU_TARGETS
# Format: arch1-linux-user,arch2-linux-user,...
def qemu_target_list(d):
    targets = d.getVar('QEMU_TARGETS').split()
    return ','.join([t + '-linux-user' for t in targets])

QEMU_TARGET_LIST = "${@qemu_target_list(d)}"

# Disable system emulation, only build user-mode
# Also disable vhost-user, tests, and other unnecessary components
# Enable static linking for true qemu-user-static binaries
EXTRA_OECONF += " \
    --target-list=${QEMU_TARGET_LIST} \
    --disable-system \
    --enable-linux-user \
    --static \
    --disable-tools \
    --disable-guest-agent \
    --disable-vhost-user \
    --disable-vhost-kernel \
    --disable-vhost-vdpa \
    --disable-vhost-crypto \
    --disable-vhost-net \
    --disable-plugins \
    --disable-tcg-interpreter \
"

# Disable ptest to avoid test-related builds that cause cross-compilation issues
PTEST_ENABLED = "0"
RDEPENDS:${PN}-ptest = ""

# Prepend to do_configure to fix meson shebang issue
# The meson wrapper script has a broken shebang, so we create a working wrapper
do_configure:prepend() {
    # Create a working meson wrapper that uses the correct python
    mkdir -p ${WORKDIR}/meson-wrapper
    cat > ${WORKDIR}/meson-wrapper/meson << 'EOF'
#!/bin/sh
exec python3 -m mesonbuild.mesonmain "$@"
EOF
    chmod +x ${WORKDIR}/meson-wrapper/meson
    
    # Add our wrapper to the front of PATH
    export PATH="${WORKDIR}/meson-wrapper:$PATH"
}

do_install() {
    install -d ${D}${bindir}
    
    # Install statically-linked user-mode binaries with -static suffix
    # These are truly static, like Debian's qemu-user-static package
    for arch in ${QEMU_TARGETS}; do
        if [ -f "${B}/qemu-$arch" ]; then
            install -m 0755 ${B}/qemu-$arch ${D}${bindir}/qemu-$arch-static
        fi
    done
    
    # Install binfmt configuration files for systemd-binfmt
    install -d ${D}${sysconfdir}/binfmt.d
    
    # Generate binfmt configuration for each architecture
    # Format: :name:type:offset:magic:mask:interpreter:flags
    # Using 'F' flag for fix binary (preserves interpreter across chroot)
    #
    # IMPORTANT: We skip the native architecture to avoid infinite loops!
    # If we register binfmt for the native arch, all binaries (including
    # systemctl, qemu itself, etc.) would be run through qemu, causing
    # "Too many levels of symbolic links" errors.
    
    # Determine native architecture to skip
    # Map TARGET_ARCH to qemu architecture names
    native_arch=""
    case "${TARGET_ARCH}" in
        x86_64)     native_arch="x86_64" ;;
        i686|i586)  native_arch="i386" ;;
        aarch64)    native_arch="aarch64" ;;
        arm)        native_arch="arm" ;;
        mips)       native_arch="mips" ;;
        mipsel)     native_arch="mipsel" ;;
        mips64)     native_arch="mips64" ;;
        mips64el)   native_arch="mips64el" ;;
        powerpc)    native_arch="ppc" ;;
        powerpc64)  native_arch="ppc64" ;;
        powerpc64le) native_arch="ppc64le" ;;
        riscv32)    native_arch="riscv32" ;;
        riscv64)    native_arch="riscv64" ;;
    esac
    
    bbnote "Native architecture is ${TARGET_ARCH} (qemu: $native_arch) - skipping binfmt registration for it"
    
    # x86_64
    if [ "$native_arch" != "x86_64" ]; then
        echo ':qemu-x86_64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x3e\x00:\xff\xff\xff\xff\xff\xfe\xfe\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-x86_64-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-x86_64-static.conf
    fi
    
    # i386
    if [ "$native_arch" != "i386" ]; then
        echo ':qemu-i386:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x03\x00:\xff\xff\xff\xff\xff\xfe\xfe\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-i386-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-i386-static.conf
    fi
    
    # aarch64
    if [ "$native_arch" != "aarch64" ]; then
        echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-aarch64-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-aarch64-static.conf
    fi
    
    # arm
    if [ "$native_arch" != "arm" ]; then
        echo ':qemu-arm:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-arm-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-arm-static.conf
    fi
    
    # mips (big endian)
    if [ "$native_arch" != "mips" ]; then
        echo ':qemu-mips:M::\x7fELF\x01\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x08:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff:${bindir}/qemu-mips-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-mips-static.conf
    fi
    
    # mipsel (little endian)
    if [ "$native_arch" != "mipsel" ]; then
        echo ':qemu-mipsel:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x08\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-mipsel-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-mipsel-static.conf
    fi
    
    # mips64 (big endian)
    if [ "$native_arch" != "mips64" ]; then
        echo ':qemu-mips64:M::\x7fELF\x02\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x08:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff:${bindir}/qemu-mips64-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-mips64-static.conf
    fi
    
    # mips64el (little endian)
    if [ "$native_arch" != "mips64el" ]; then
        echo ':qemu-mips64el:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x08\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-mips64el-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-mips64el-static.conf
    fi
    
    # ppc (big endian)
    if [ "$native_arch" != "ppc" ]; then
        echo ':qemu-ppc:M::\x7fELF\x01\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x14:\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff:${bindir}/qemu-ppc-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-ppc-static.conf
    fi
    
    # ppc64 (big endian)
    if [ "$native_arch" != "ppc64" ]; then
        echo ':qemu-ppc64:M::\x7fELF\x02\x02\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x15:\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff:${bindir}/qemu-ppc64-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-ppc64-static.conf
    fi
    
    # ppc64le (little endian)
    if [ "$native_arch" != "ppc64le" ]; then
        echo ':qemu-ppc64le:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x15\x00:\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-ppc64le-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-ppc64le-static.conf
    fi
    
    # riscv32
    if [ "$native_arch" != "riscv32" ]; then
        echo ':qemu-riscv32:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xf3\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-riscv32-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-riscv32-static.conf
    fi
    
    # riscv64
    if [ "$native_arch" != "riscv64" ]; then
        echo ':qemu-riscv64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xf3\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:${bindir}/qemu-riscv64-static:F' \
            > ${D}${sysconfdir}/binfmt.d/qemu-riscv64-static.conf
    fi
}

# Override package definitions from qemu.inc
# We want: main package, binfmt configs, and debug symbols
PACKAGES = "${PN}-dbg ${PN} ${PN}-binfmt"

# Override FILES and RDEPENDS from qemu.inc
FILES:${PN} = "${bindir}/qemu-*-static"
FILES:${PN}-binfmt = "${sysconfdir}/binfmt.d"
FILES:${PN}-dbg = "${bindir}/.debug"

# Clear inherited RDEPENDS (qemu.inc adds ${PN}-common which we don't have)
RDEPENDS:${PN} = ""
RDEPENDS:${PN}-binfmt = "${PN}"

SUMMARY:${PN}-binfmt = "binfmt_misc configuration for QEMU user-mode emulation binaries"
DESCRIPTION:${PN}-binfmt = "Configuration files to register QEMU binaries with binfmt_misc \
for transparent execution of foreign architecture binaries."

# Skip file-rdeps check since these are user-mode emulators
INSANE_SKIP:${PN} = "file-rdeps"

# Don't provide the same packages as the main qemu recipe
PROVIDES = ""

# Disable the dynamic package splitting from qemu.inc since we handle our own packages
PACKAGES_DYNAMIC = ""

# Remove qemu.inc's package split function - we define our own PACKAGES
PACKAGESPLITFUNCS:remove = "split_qemu_packages"

# Disable guest agent related settings from qemu.inc (we don't build the guest agent)
SYSTEMD_PACKAGES = ""
SYSTEMD_SERVICE:${PN}-guest-agent = ""
INITSCRIPT_PACKAGES = ""

