SUMMARY = "RUBIK Pi 3 UFS partition table (partition.xml) for qcom-gen-partition-bins"
DESCRIPTION = "Avocado's UFS partition layout for the RUBIK Pi 3 (files/ \
partition_ufs.xml: efi, system, avocado var, and Thundercomm's boot partitions). \
Deployed as partition.xml; qcom-gen-partition-bins turns it into GPT binaries \
and rawprogram/patch XMLs. Formerly a bbappend on meta-qcom-hwe's recipe."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_MACHINE = "rubikpi3"
PROVIDES += "virtual/partconf"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI = "file://partition_ufs.xml"
S = "${UNPACKDIR}"

INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

inherit deploy allarch
do_deploy() {
    install -m 0644 ${S}/partition_ufs.xml ${DEPLOYDIR}/partition.xml
}
addtask deploy before do_build after do_compile
