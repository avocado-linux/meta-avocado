DESCRIPTION = "Deploy the avocado_tegraflash flash engine for stone provisioning"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

COMPATIBLE_MACHINE = "(tegra)"

FILESEXTRAPATHS:prepend := "${THISDIR}/../../stone/tegra:"

# The package directory is fetched as-is; BitBake copies a directory
# file:// entry into UNPACKDIR. wrynose no longer auto-creates ${S}, so
# set it explicitly to UNPACKDIR.
SRC_URI = "file://avocado_tegraflash"

S = "${UNPACKDIR}"

inherit deploy

# This recipe just deploys files, no compilation needed
do_compile[noexec] = "1"
do_install[noexec] = "1"

# Deploy the engine package so the stone output directory stays
# self-contained. Bytecode is removed so the deployed tree is source only.
do_deploy() {
    install -d ${DEPLOYDIR}/tegraflash-engine
    cp -R --no-preserve=ownership ${UNPACKDIR}/avocado_tegraflash ${DEPLOYDIR}/tegraflash-engine/
    find ${DEPLOYDIR}/tegraflash-engine -name __pycache__ -prune -exec rm -rf {} +
    find ${DEPLOYDIR}/tegraflash-engine -name '*.pyc' -delete
}

addtask deploy before do_build after do_compile

PACKAGE_ARCH = "${MACHINE_ARCH}"
