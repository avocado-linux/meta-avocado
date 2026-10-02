SUMMARY = "Mount the ESP from the disk the system booted from"
DESCRIPTION = "A systemd generator that retargets boot-efi.mount at the esp \
partition on the booted disk. The unit setup-nv-boot-control ships names its \
device by PARTLABEL, which on a board provisioned to more than one medium \
resolves to whichever disk udev happened to process first."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-tegra-esp-generator"

COMPATIBLE_MACHINE = "(tegra)"

# allarch: the payload is a POSIX shell script with no compiled content,
# matching avocado-slot-root-generator.
inherit allarch

do_install() {
    install -d ${D}${systemd_unitdir}/system-generators
    install -m 0755 ${WORKDIR}/avocado-tegra-esp-generator \
        ${D}${systemd_unitdir}/system-generators/avocado-tegra-esp-generator
}

FILES:${PN} = "${systemd_unitdir}/system-generators/avocado-tegra-esp-generator"

# Deliberately no RDEPENDS on setup-nv-boot-control. The generator writes a
# drop-in for boot-efi.mount and does nothing harmful when that unit is absent,
# and tying the two together would force the whole redundant-boot chain into
# any image that wants this correctness fix. The dependency runs the other way
# in practice: the fix matters only once something ships that unit.
