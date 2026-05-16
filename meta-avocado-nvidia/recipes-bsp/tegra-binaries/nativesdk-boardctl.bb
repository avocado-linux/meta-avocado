DESCRIPTION = "NVIDIA board automation tools (boardctl) for SDK"
LICENSE = "CLOSED"
LIC_FILES_CHKSUM = ""

PV = "${L4T_VERSION}"

inherit l4t_bsp nativesdk

S = "${UNPACKDIR}"

# Ensure the L4T BSP tarball is unpacked before we install
do_install[depends] += "tegra-binaries:do_preconfigure"

RDEPENDS:${PN} = "\
    nativesdk-python3 \
"

BOARDCTL_BINDIR = "${SDKPATHNATIVE}${bindir_nativesdk}/board_automation"
L4T_BSP_TOOLS = "${L4T_BSP_SHARED_SOURCE_DIR}/tools/board_automation"

do_install() {
    install -d ${D}${BOARDCTL_BINDIR}

    # Python scripts
    install -m 0755 ${L4T_BSP_TOOLS}/boardctl ${D}${BOARDCTL_BINDIR}/
    install -m 0755 ${L4T_BSP_TOOLS}/nvtopo.py ${D}${BOARDCTL_BINDIR}/
    install -m 0644 ${L4T_BSP_TOOLS}/libnvtopo_wrapper.py ${D}${BOARDCTL_BINDIR}/
    install -m 0644 ${L4T_BSP_TOOLS}/supported_targets.py ${D}${BOARDCTL_BINDIR}/

    # Native shared library (x86_64)
    install -m 0755 ${L4T_BSP_TOOLS}/libnvtopo.so ${D}${BOARDCTL_BINDIR}/

    # Symlink boardctl into PATH
    install -d ${D}${SDKPATHNATIVE}${bindir_nativesdk}
    ln -sf board_automation/boardctl ${D}${SDKPATHNATIVE}${bindir_nativesdk}/boardctl
}

FILES:${PN} = "${BOARDCTL_BINDIR} ${SDKPATHNATIVE}${bindir_nativesdk}/boardctl"

# Skip QA for pre-built NVIDIA x86_64 binary
INSANE_SKIP:${PN} = "already-stripped arch file-rdeps ldflags libdir"

# Prebuilt x86_64 ELFs ship inside this package and are executed on aarch64 SDK
# hosts via host-kernel binfmt_misc + qemu-user-static (configured on the build
# host, not the SDK container). Suppress auto-generated dependency Requires so
# rpmdeps doesn't emit unsatisfiable libc.so.6 symbol-version Requires -- the
# ELFs' GLIBC_2.2.5 / GLIBC_2.3 / libm.so.6 needs don't exist on aarch64, which
# only ships GLIBC_2.17+.
#
# EXCLUDE_FROM_SHLIBS disables the shlibs scanner; SKIP_FILEDEPS disables the
# per-file rpmdeps ELF scan (FILERDEPENDS) -- both paths emit Requires.
EXCLUDE_FROM_SHLIBS = "1"
SKIP_FILEDEPS:${PN} = "1"

INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"
