DESCRIPTION = "Avocado image var"
LICENSE = "Apache-2.0"

inherit deploy

DEPENDS += "btrfs-tools-native"

fakeroot do_compile() {
    # Create a temporary directory for the btrfs image
    install -o root -g root -d ${WORKDIR}/btrfs_root/lib/extensions
    install -o root -g root -d ${WORKDIR}/btrfs_root/lib/confexts

    mkfs.btrfs -r ${WORKDIR}/btrfs_root --subvol rw:lib/extensions --subvol rw:lib/confexts -f ${WORKDIR}/avocado-image-var-${MACHINE}.btrfs
}

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/avocado-image-var-${MACHINE}.btrfs ${DEPLOYDIR}/avocado-image-var-${MACHINE}.btrfs
}

addtask deploy after do_compile
