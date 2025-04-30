# This needs to be in a class so it can be deferred until after the other tasks in image class are done
# It is working around the empty_var_volatile task that is injected in the image class.
fixup_var_volatile () {
    install -m 1777 -d ${IMAGE_ROOTFS}/${localstatedir}/volatile/tmp
    install -m 755 -d ${IMAGE_ROOTFS}/${localstatedir}/volatile/log
}

ROOTFS_POSTPROCESS_COMMAND:append = " fixup_var_volatile; "
