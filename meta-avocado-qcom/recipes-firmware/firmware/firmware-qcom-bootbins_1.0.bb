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

# Which of Thundercomm's XBL configs to flash as xbl_config.elf. The prebuilt
# zip carries three: xbl_config.elf (byte-identical to xbl_config_gunyah.elf),
# xbl_config_gunyah.elf and xbl_config_kvm.elf. Under the gunyah config the
# Gunyah hypervisor (hyp_a / hypvm.mbn) owns EL2 and Linux is booted at EL1,
# so KVM cannot initialise no matter how CONFIG_KVM is set. The kvm config
# leaves EL2 to Linux. rawprogram1/2.xml only ever flash the file named
# xbl_config.elf, so the choice has to be made here.
QCOM_XBL_CONFIG_VARIANT ?= "gunyah"
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
            # --no-preserve=ownership: do_compile unzips as the build user, so
            # a plain 'cp -a' would ship those ids and break do_package's
            # getpwuid() on hosts with no passwd entry for them.
            *) if [ -d "$f" ]; then cp -a --no-preserve=ownership "$f" ${D}/; else install -m 0644 "$f" ${D}/; fi ;;
        esac
    done

    # Overwrite the generic name with the selected variant (see
    # QCOM_XBL_CONFIG_VARIANT above). Fails the build if the zip ever stops
    # shipping the variant, rather than silently flashing the stock config.
    install -m 0644 "xbl_config_${QCOM_XBL_CONFIG_VARIANT}.elf" ${D}/xbl_config.elf
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
