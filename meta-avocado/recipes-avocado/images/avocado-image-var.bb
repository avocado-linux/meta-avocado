DESCRIPTION = "Avocado image var"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

inherit deploy

DEPENDS += "btrfs-tools-native"

# Wrynose's OE-core switched pseudo to an allowlist (PSEUDO_INCLUDE_PATHS)
# scoped to ${WORKDIR}/{image,package,rootfs,...}. Our btrfs source tree
# lives outside that set, so the install -o root -g root calls below
# fall through to the real syscall and fail. Extend the allowlist.
PSEUDO_INCLUDE_PATHS .= ",${WORKDIR}/btrfs_root"

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
