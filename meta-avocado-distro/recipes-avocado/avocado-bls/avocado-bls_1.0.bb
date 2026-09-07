SUMMARY = "Boot Loader Specification entry management for OS updates"
DESCRIPTION = "\
Clears and sets systemd-boot's automatic-boot-assessment counters from the \
running system, for boards whose firmware exposes no writable EFI variables \
and so cannot run systemd-bless-boot. Invoked from a stone manifest's \
update.commit and update.rollback actions."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-bls"

S = "${UNPACKDIR}"

do_install() {
    install -Dm 0755 ${S}/avocado-bls ${D}${bindir}/avocado-bls
}

# grep -a over the entry files and readlink; both are in the base image, but
# name them so a slimmer image does not silently lose the update path.
RDEPENDS:${PN} += "grep coreutils util-linux-mount"
