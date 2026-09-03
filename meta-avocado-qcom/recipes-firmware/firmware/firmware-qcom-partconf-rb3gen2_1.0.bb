SUMMARY = "RB3 Gen 2 UFS partition table (partition.xml) for qcom-gen-partition-bins"
DESCRIPTION = "Avocado's UFS partition layout for the Qualcomm Robotics RB3 \
Gen 2: Qualcomm's stock table with the single `rootfs` partition replaced by \
avocado's OS layout (efi, system_a, system_b, avocado var). Deployed as \
partition.xml; qcom-gen-partition-bins turns it into GPT binaries and \
rawprogram/patch XMLs."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_MACHINE = "rb3gen2"
PROVIDES += "virtual/partconf"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI = "file://partition_ufs_rb3gen2.xml"
S = "${UNPACKDIR}"

INHIBIT_DEFAULT_DEPS = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

inherit deploy allarch

do_deploy() {
    install -m 0644 ${S}/partition_ufs_rb3gen2.xml ${DEPLOYDIR}/partition.xml
}
addtask deploy after do_install before do_build
