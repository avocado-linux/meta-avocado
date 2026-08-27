SUMMARY = "GPT binaries and QDL rawprogram/patch XMLs from partition.xml"
DESCRIPTION = "Runs qcom-ptool over the partition.xml virtual/partconf deploys \
and deploys the resulting gpt_*.bin, rawprogram*.xml, patch*.xml and zeros_*.bin \
that stone-provision-ufs.sh hands to qdl. Formerly meta-qcom-hwe's recipe; the \
tool is meta-qcom's qcom-ptool-native (CLI: qcom-ptool <subcommand>)."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_MACHINE = "rubikpi3"
DEPENDS += "qcom-ptool-native"
INHIBIT_DEFAULT_DEPS = "1"

do_configure[noexec] = "1"
do_install[noexec] = "1"
do_compile[depends] += "virtual/partconf:do_deploy"
do_compile[cleandirs] += "${B}"

do_compile() {
    cd ${B}
    qcom-ptool ptool -x ${DEPLOY_DIR_IMAGE}/partition.xml
}

inherit deploy
do_deploy() {
    install -m 0644 ${B}/gpt_backup*.bin -D ${DEPLOYDIR}
    install -m 0644 ${B}/gpt_both*.bin -D ${DEPLOYDIR}
    install -m 0644 ${B}/gpt_empty*.bin -D ${DEPLOYDIR}
    install -m 0644 ${B}/gpt_main*.bin -D ${DEPLOYDIR}
    install -m 0644 ${B}/patch*.xml -D ${DEPLOYDIR}
    install -m 0644 ${B}/rawprogram*.xml -D ${DEPLOYDIR}
    install -m 0644 ${B}/zeros_*.bin -D ${DEPLOYDIR}
    install -m 0644 ${B}/wipe_rawprogram_PHY*.xml -D ${DEPLOYDIR}
}
addtask deploy before do_build after do_compile
PACKAGE_ARCH = "${MACHINE_ARCH}"
