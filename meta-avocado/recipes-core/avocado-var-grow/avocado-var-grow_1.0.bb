SUMMARY = "Grow the var partition to its disk in the initramfs, when provisioning marked it"
DESCRIPTION = "Reads GPT attribute bit 56 on the var partition (set by stone/fwup from the \
manifest's expand: true) and extends the partition to the end of the disk before \
cryptsetup-var opens it or var.mount mounts it. Idempotent from the partition table alone."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-var-grow file://avocado-var-grow.service"
S = "${UNPACKDIR}"

# sgdisk (gptfdisk), partx and blkid (util-linux); util-linux is already in the
# initramfs, gptfdisk is what this recipe adds.
RDEPENDS:${PN} = "gptfdisk util-linux-partx util-linux-blkid"

inherit systemd
SYSTEMD_SERVICE:${PN} = "avocado-var-grow.service"

# The var partition this machine grows, and its systemd device unit. Only a
# GPT partition found by label can carry the grow attribute; the initramfs
# packagegroup installs this recipe on such machines only (Raspberry Pi's MBR
# node and Jetson's "none" never do), so the unit's Requires= on the device
# unit is always satisfiable where it is installed.
AVOCADO_VAR_PART_DEV ??= ""
python __anonymous() {
    dev = d.getVar('AVOCADO_VAR_PART_DEV') or ''
    if not dev.startswith('/dev/disk/by-partlabel/'):
        raise bb.parse.SkipRecipe("AVOCADO_VAR_PART_DEV is '%s', not a /dev/disk/by-partlabel/ path: no GPT var partition to grow on this machine" % dev)
}
def avocado_var_device_unit(d):
    """systemd-escape --path of AVOCADO_VAR_PART_DEV: leading '/' dropped,
    '-' escaped as \\x2d, '/' -> '-'. The backslash is doubled on the way out
    because the only consumer is a sed replacement, where a lone \\x is an
    escape sequence and would be eaten - which is how imx8mp-evk ended up
    waiting for `/dev/disk/by/partlabel/var` and dropping to emergency."""
    dev = d.getVar('AVOCADO_VAR_PART_DEV') or ''
    escaped = dev.lstrip('/').replace('-', '\\x2d').replace('/', '-') + '.device'
    return escaped.replace('\\', '\\\\')

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${UNPACKDIR}/avocado-var-grow ${D}${libexecdir}/avocado-var-grow
    install -d ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants
    install -m 0644 ${UNPACKDIR}/avocado-var-grow.service ${D}${systemd_system_unitdir}/
    sed -i -e 's|@AVOCADO_VAR_PART_DEV@|${AVOCADO_VAR_PART_DEV}|g' \
           -e 's|@AVOCADO_VAR_DEVICE_UNIT@|${@avocado_var_device_unit(d)}|g' \
        ${D}${libexecdir}/avocado-var-grow ${D}${systemd_system_unitdir}/avocado-var-grow.service
    # Same as cryptsetup-var: the initramfs image applies no preset for
    # initrd-root-fs.target units, so stage the .wants symlink by hand.
    ln -sf ../avocado-var-grow.service ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants/avocado-var-grow.service
}

FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/avocado-var-grow.service"
