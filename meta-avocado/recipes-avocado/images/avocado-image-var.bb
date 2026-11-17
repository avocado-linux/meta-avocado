DESCRIPTION = "Avocado image var"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

inherit deploy

DEPENDS += "btrfs-tools-native"

# mkfs.btrfs -r copies everything under btrfs_root. The directory is in
# WORKDIR and outlives a do_compile run, so start each run from an empty one:
# otherwise a file that an earlier run staged there stays in the image.
do_compile[cleandirs] += "${WORKDIR}/btrfs_root"

fakeroot do_compile() {
    # Create a temporary directory for the btrfs image
    install -o root -g root -d ${WORKDIR}/btrfs_root/lib/extensions
    install -o root -g root -d ${WORKDIR}/btrfs_root/lib/confexts

    mkfs.btrfs -r ${WORKDIR}/btrfs_root --subvol rw:lib/extensions --subvol rw:lib/confexts -f ${WORKDIR}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs
}

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs ${DEPLOYDIR}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs
}

addtask deploy after do_compile
