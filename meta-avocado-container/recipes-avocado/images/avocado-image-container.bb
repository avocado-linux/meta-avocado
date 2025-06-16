DESCRIPTION = "Avocado SDK Container image"
LICENSE = "Apache-2.0"

inherit image
inherit image-oci
IMGCLASSES += " image-container-post-processing"
inherit_defer ${IMGCLASSES}

IMAGE_INSTALL = "packagegroup-avocado-container"
IMAGE_FEATURES = "package-management"
IMAGE_LINGUAS = ""

IMAGE_FSTYPES = "container oci"
NO_RECOMMENDATIONS = "1"

IMAGE_CONTAINER_NO_DUMMY = "0"

OCI_IMAGE_ENTRYPOINT = "entrypoint"

RPM_PREPROCESS_COMMANDS += "update_alternatives; rootfs_fixup_var_volatile; "

update_alternatives () {
    # Configure DNF to be friendly to update-alternatives
    mv ${IMAGE_ROOTFS}/etc/dnf/dnf.conf ${IMAGE_ROOTFS}/etc/dnf/dnf.conf.dnf
    ln -s ${IMAGE_ROOTFS}/etc/dnf/dnf.conf.dnf ${IMAGE_ROOTFS}/etc/dnf/dnf.conf

    mv ${IMAGE_ROOTFS}/etc/dnf/vars/arch ${IMAGE_ROOTFS}/etc/dnf/vars/arch.dnf
    ln -s ${IMAGE_ROOTFS}/etc/dnf/vars/arch.dnf ${IMAGE_ROOTFS}/etc/dnf/vars/arch

    # Configure RPM to be friendly to update-alternatives
    mv ${IMAGE_ROOTFS}/etc/rpm/platform ${IMAGE_ROOTFS}/etc/rpm/platform.dnf
    ln -s ${IMAGE_ROOTFS}/etc/rpm/platform.dnf ${IMAGE_ROOTFS}/etc/rpm/platform

    mv ${IMAGE_ROOTFS}/etc/rpmrc ${IMAGE_ROOTFS}/etc/rpmrc.dnf
    ln -s ${IMAGE_ROOTFS}/etc/rpmrc.dnf ${IMAGE_ROOTFS}/etc/rpmrc
}

rootfs_fixup_var_volatile () {
    install -m 1777 -d ${IMAGE_ROOTFS}/${localstatedir}/volatile/tmp
    install -m 755 -d ${IMAGE_ROOTFS}/${localstatedir}/volatile/log
}
