FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

PACKAGECONFIG += "egl kmsro panfrost"

SRC_URI += "file://mesa_add_rzg2l_du_entrypoint.patch"
