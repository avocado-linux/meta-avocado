SUMMARY = "RB3 Gen 2 boot binaries (XBL, XBL config, UEFI, TZ, AOP, ...)"
DESCRIPTION = "The non-HLOS boot chain for the Qualcomm Robotics RB3 Gen 2, \
from the QCM6490_bootbinaries package Qualcomm publishes on its software \
center -- the same artifact meta-qcom's firmware-qcom-boot-qcs6490 fetches. \
Deployed for stone-provision-ufs.sh to flash over QDL with the GPT and \
rawprogram XMLs qcom-gen-partition-bins derives from \
firmware-qcom-partconf-rb3gen2. \
\
Unlike the RUBIK Pi 3, no vendor fork is involved: the RB3 Gen 2 is Qualcomm's \
own reference board, so the boot chain ships with the SoC's tech package."
LICENSE = "LICENSE.qcom-2"
LIC_FILES_CHKSUM = "file://LICENSE.qcom-2;md5=165287851294f2fb8ac8cbc5e24b02b0"

COMPATIBLE_MACHINE = "rb3gen2"
PROVIDES += "virtual/bootbins"

# Same URL meta-qcom's firmware-qcom-boot-qcs6490.inc uses. Fetched directly
# rather than by depending on that recipe: it deploys into a per-SoC subdirectory
# and does not do the xbl_config selection below, and avocado's provisioning
# script wants the chain packaged, not just deployed.
FW_ARTIFACTORY = "softwarecenter.qualcomm.com/nexus/generic/product/chip/tech-package/QCM6490_bootbinaries.1.0/qcm6490_bootbinaries.1.0-test-device-public"
BOOTBINARIES = "QCM6490_bootbinaries"
SRC_URI = "https://${FW_ARTIFACTORY}/${PV}/${BOOTBINARIES}_${PV}.zip;subdir=${BP}"
SRC_URI[sha256sum] = "24315170167192c63e4969d85d4b20b2bd9311f6b2a72220af571d2ebaa51e2a"

S = "${UNPACKDIR}/${BP}/${BOOTBINARIES}"

# Which XBL config to flash as xbl_config.elf. The package carries three:
# xbl_config.elf, xbl_config_gunyah.elf and xbl_config_kvm.elf, all the same
# size. Under the gunyah config Gunyah owns EL2 and /dev/kvm never appears;
# avocado-qcs6490.inc selects kvm. XBL only ever loads xbl_config.elf, so the
# choice has to be made here.
QCOM_XBL_CONFIG_VARIANT ?= "gunyah"

INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}
    # Everything but the partition tables (firmware-qcom-partconf-rb3gen2 owns
    # those) and the packaging metadata.
    cd ${S}
    for f in *; do
        case "$f" in
            partition*.xml|contents*.xml|readme.txt|LICENSE*) ;;
            *) if [ -d "$f" ]; then
                   cp -a --no-preserve=ownership "$f" ${D}/
               else
                   install -m 0644 "$f" ${D}/
               fi ;;
        esac
    done

    # Fails the build if the package ever stops shipping the variants, rather
    # than silently flashing whatever xbl_config.elf happens to be in the zip.
    if [ ! -f "${S}/xbl_config_${QCOM_XBL_CONFIG_VARIANT}.elf" ]; then
        bbfatal "no xbl_config_${QCOM_XBL_CONFIG_VARIANT}.elf in ${BOOTBINARIES}_${PV}.zip"
    fi
    install -m 0644 "${S}/xbl_config_${QCOM_XBL_CONFIG_VARIANT}.elf" ${D}/xbl_config.elf
}

FILES:${PN} = "/"
INSANE_SKIP:${PN} += "arch"
inherit deploy allarch

do_deploy() {
    install -d ${DEPLOYDIR}
    cp -a --no-preserve=ownership ${D}/. ${DEPLOYDIR}/
}
addtask deploy after do_install before do_build
