SUMMARY = "Thundercomm RUBIK Pi 3 boot binaries (XBL, UEFI/ABL, TZ, AOP, ...)"
DESCRIPTION = "The non-HLOS boot chain Thundercomm ships for the RUBIK Pi 3 \
(rubikpi-ai/prebuilt, branch BP-BINs): XBL, XBL config, UEFI, TZ, hypervisor, \
AOP, CPUCP, QUP firmware, devcfg, CDT and the board's config/dtso/splash images. \
Deployed for stone-provision-ufs.sh to flash over QDL with the GPT and \
rawprogram XMLs qcom-gen-partition-bins derives from firmware-qcom-partconf. \
Formerly a bbappend on meta-qcom-hwe's recipe of the same name; the HWE layer \
is scarthgap-only, so the recipe lives here now, self-contained."
LICENSE = "CLOSED"

COMPATIBLE_MACHINE = "rubikpi3"
PROVIDES += "virtual/bootbins"

SRC_URI = "git://github.com/rubikpi-ai/prebuilt;protocol=https;branch=BP-BINs"
SRCREV = "582e89422b3efd5a09aba3d584beef4083b70d14"
BB_GIT_SHALLOW = "1"
BB_GIT_SHALLOW_DEPTH = "1"
BB_GENERATE_SHALLOW_TARBALLS = "1"

BOOTBINARIES = "QCM6490_bootbinaries"
S = "${UNPACKDIR}/${BP}"
B = "${WORKDIR}/build"

DEPENDS += "unzip-native"
INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"

do_compile() {
    rm -rf ${B}/${BOOTBINARIES}
    unzip -q "${S}/${BOOTBINARIES}.zip" -d "${B}"
}

do_install() {
    install -d ${D}
    # Everything but the partition tables (firmware-qcom-partconf owns those)
    # and NHLOS packaging metadata.
    cd ${B}/${BOOTBINARIES}
    for f in *; do
        case "$f" in
            partition*.xml|contents*.xml) ;;
            *) if [ -d "$f" ]; then cp -a "$f" ${D}/; else install -m 0644 "$f" ${D}/; fi ;;
        esac
    done
}

inherit deploy
do_deploy() {
    for ext in bin elf fv mbn melf img; do
        find "${D}" -maxdepth 1 -name "*.$ext" -exec install -m 0644 {} ${DEPLOYDIR} \;
    done
}
addtask deploy before do_build after do_install

FILES:${PN} = "/*"
INSANE_SKIP:${PN} += "arch ldflags file-rdeps already-stripped staticdev"
PACKAGE_ARCH = "${MACHINE_ARCH}"
