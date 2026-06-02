SUMMARY = "QEMU user-mode emulation binaries for binfmt_misc"
DESCRIPTION = "QEMU user-mode emulation binaries that can be \
registered with binfmt_misc to transparently run binaries built for other \
architectures. Similar to the qemu-user-static package in Debian/Ubuntu."
HOMEPAGE = "http://qemu.org"
LICENSE = "GPL-2.0-only & LGPL-2.1-only"

# Build on top of oe-core's qemu. Requiring qemu.inc (resolved via BBPATH from
# openembedded-core) reuses its SRC_URI, patch set, sha256sum and PACKAGECONFIG
# definitions instead of carrying a forward-ported copy. PV comes from this
# recipe's filename, so keep it in lockstep with oe-core's qemu_<PV>.bb — bump
# the filename when oe-core bumps qemu, or the sha256sum/patches won't match.
require recipes-devtools/qemu/qemu.inc

# qemu.inc references its patches and aux files with bare file:// entries; they
# live in oe-core's qemu/ files dir, which isn't on our FILESPATH. Add it, plus
# our own files/ for the USB-passthrough patch below.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:${COREBASE}/meta/recipes-devtools/qemu/qemu:"

# Avocado addition: fix USBDEVFS_CONTROL/BULK ioctls in user-mode emulation so
# foreign-arch binaries that use libusb work (USB device passthrough).
SRC_URI += "file://0001-linux-user-Fix-USBDEVFS-ioctls.patch"

# BPN here is "qemu-user-static", so qemu.inc's ${BPN}-${PV} tarball URL and the
# default S point at a nonexistent qemu-user-static tarball. Redirect both at the
# real qemu tarball (the sha256sum from qemu.inc still applies, same tarball).
SRC_URI:remove = "https://download.qemu.org/${BPN}-${PV}.tar.xz"
SRC_URI:prepend = "https://download.qemu.org/qemu-${PV}.tar.xz "
S = "${UNPACKDIR}/qemu-${PV}"

# qemu.inc's per-version DEPENDS live in qemu_${PV}.bb, which we don't require.
# Pull in what user-mode static linking needs (libpcre2 = static glib; libusb1
# comes via PACKAGECONFIG below).
DEPENDS += "glib-2.0 glib-2.0-native zlib libpcre2"

# User-mode only; enable libusb for USB device passthrough.
PACKAGECONFIG = "libusb"

# Architectures to emulate.
QEMU_TARGETS = "aarch64 arm i386 x86_64 mips mipsel mips64 mips64el ppc ppc64 ppc64le riscv32 riscv64"

def qemu_target_list(d):
    targets = d.getVar('QEMU_TARGETS').split()
    return ','.join([t + '-linux-user' for t in targets])

# Statically linked user-mode binaries only — no system emulation, tools, guest
# agent, vhost or plugins.
EXTRA_OECONF += " \
    --target-list=${@qemu_target_list(d)} \
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

# no-static-libs.inc appends "--disable-static" to EXTRA_OECONF for every recipe,
# but qemu's configure aborts on unrecognised options (it's not autotools). oe-core
# opts its own qemu PNs out (DISABLE_STATIC:pn-qemu = "" etc.); this recipe's PN is
# qemu-user-static, so it must opt out too — and we link --static here anyway.
DISABLE_STATIC = ""

PTEST_ENABLED = "0"

do_install() {
    install -d ${D}${bindir}

    # Install statically-linked user-mode binaries with a -static suffix, like
    # Debian's qemu-user-static package.
    for arch in ${QEMU_TARGETS}; do
        if [ -f "${B}/qemu-$arch" ]; then
            install -m 0755 ${B}/qemu-$arch ${D}${bindir}/qemu-$arch-static
        fi
    done

    # binfmt_misc registration files for systemd-binfmt.
    # Format: :name:type:offset:magic:mask:interpreter:flags
    # The 'F' flag (fix binary) pre-captures the interpreter so it works across
    # mount namespaces / chroots (e.g. inside the SDK container).
    install -d ${D}${sysconfdir}/binfmt.d

    # Skip the native architecture: registering binfmt for it would route every
    # binary (systemctl, qemu itself, ...) through qemu and loop infinitely.
    native_arch=""
    case "${TARGET_ARCH}" in
        x86_64)      native_arch="x86_64" ;;
        i686|i586)   native_arch="i386" ;;
        aarch64)     native_arch="aarch64" ;;
        arm)         native_arch="arm" ;;
        mips)        native_arch="mips" ;;
        mipsel)      native_arch="mipsel" ;;
        mips64)      native_arch="mips64" ;;
        mips64el)    native_arch="mips64el" ;;
        powerpc)     native_arch="ppc" ;;
        powerpc64)   native_arch="ppc64" ;;
        powerpc64le) native_arch="ppc64le" ;;
        riscv32)     native_arch="riscv32" ;;
        riscv64)     native_arch="riscv64" ;;
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

# Our own packaging: the static binaries, the binfmt configs, and debug symbols.
# Replaces qemu.inc's per-arch dynamic split.
PACKAGES = "${PN}-dbg ${PN} ${PN}-binfmt"

FILES:${PN} = "${bindir}/qemu-*-static"
FILES:${PN}-binfmt = "${sysconfdir}/binfmt.d"
FILES:${PN}-dbg = "${bindir}/.debug"

RDEPENDS:${PN} = ""
RDEPENDS:${PN}-binfmt = "${PN}"

SUMMARY:${PN}-binfmt = "binfmt_misc configuration for QEMU user-mode emulation binaries"
DESCRIPTION:${PN}-binfmt = "Configuration files to register QEMU binaries with binfmt_misc \
for transparent execution of foreign architecture binaries."

# Static user-mode emulators have no detectable runtime deps.
INSANE_SKIP:${PN} = "file-rdeps"

# Don't collide with / shadow oe-core's qemu recipe, and disable its dynamic
# per-arch package splitting and guest-agent service wiring.
PROVIDES = ""
PACKAGES_DYNAMIC = ""
PACKAGESPLITFUNCS:remove = "split_qemu_packages"
SYSTEMD_PACKAGES = ""
INITSCRIPT_PACKAGES = ""
