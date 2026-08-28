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
# `install -d` once, then `-t`, rather than a trailing `-D` per line. GNU
# install permutes options, so a trailing `-D` does parse -- but `-D` with a
# *single* source treats the destination as a file path, so a glob that happens
# to match exactly one file would write a file named after ${DEPLOYDIR} if the
# directory did not already exist. `-t` always means "into this directory",
# whatever the glob matches.
do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 -t ${DEPLOYDIR} ${B}/gpt_backup*.bin
    install -m 0644 -t ${DEPLOYDIR} ${B}/gpt_both*.bin
    install -m 0644 -t ${DEPLOYDIR} ${B}/gpt_empty*.bin
    install -m 0644 -t ${DEPLOYDIR} ${B}/gpt_main*.bin
    install -m 0644 -t ${DEPLOYDIR} ${B}/patch*.xml
    install -m 0644 -t ${DEPLOYDIR} ${B}/rawprogram*.xml
    install -m 0644 -t ${DEPLOYDIR} ${B}/zeros_*.bin
    install -m 0644 -t ${DEPLOYDIR} ${B}/wipe_rawprogram_PHY*.xml
}
addtask deploy before do_build after do_compile
PACKAGE_ARCH = "${MACHINE_ARCH}"
