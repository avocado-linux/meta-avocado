FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:remove = "file://0001-linux-dri-skip-check-for-mali.patch"
SRC_URI:append = " file://0001-linux-dri-skip-check-for-mali-fix.patch"
