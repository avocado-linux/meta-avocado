SUMMARY = "Qualcomm Device Loader prebuilt host tool"
LICENSE = "CLOSED"
LIC_FILES_CHKSUM = ""

SRC_URI = "https://softwarecenter.qualcomm.com/api/download/software/tools/Qualcomm_Device_Loader/All/2.3.4/Qualcomm_Device_Loader.Core.2.3.4.All-AnyCPU-qdl_2.3.4.zip"
SRC_URI[sha256sum] = "1381b8145dd23d79997cc8dd55c39d53989af06f737b388d8fefcfb4f0aa5a92"

S = "${WORKDIR}"

BBCLASSEXTEND = "native"

DEPENDS:class-native += "unzip-native patchelf-native"

do_compile[noexec] = "1"
do_install[noexec] = "1"

inherit deploy
do_deploy[depends] += "patchelf-native:do_populate_sysroot"

do_deploy() {
    install -d ${DEPLOYDIR}
    case ${BUILD_ARCH} in
        x86_64)
            install -m 0755 ${S}/qdl_${PV}/QDL_Linux_x64/qdl ${DEPLOYDIR}/qdl
            patchelf --set-interpreter /lib/ld-linux-x86-64.so.2 ${DEPLOYDIR}/qdl
            ;;
        aarch64) install -m 0755 ${S}/qdl_${PV}/QDL_Linux_ARM/qdl ${DEPLOYDIR}/qdl ;;
    esac
}
addtask deploy after do_unpack before do_build
