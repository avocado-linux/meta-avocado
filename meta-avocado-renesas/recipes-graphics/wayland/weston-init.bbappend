# meta-rz-distro's weston-init append pins Weston to --drm-device=card0
# --additional-devices=card1, assuming card0 is the display. With the
# upstream Mali driver (panfrost, enabled by this layer) the render-only GPU
# probes first as card0, so Weston exits with "card0 is not a KMS device".
# Unpinned, Weston picks the KMS device itself. A postfunc, so it runs after
# every do_install append whatever the layer order.
do_install[postfuncs] += "${@bb.utils.contains('MACHINE_FEATURES', 'mali-g31', 'avocado_weston_unpin_drm_device', '', d)}"

avocado_weston_unpin_drm_device() {
    sed -i -e 's/ --drm-device=card0//' -e 's/ --additional-devices=card1//' \
        ${D}${systemd_system_unitdir}/weston.service
}
