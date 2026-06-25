FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'secureboot', ' file://dm-verity.cfg', '', d)}"
SRC_URI:append = "${@bb.utils.contains('DISTRO_FEATURES', 'security', ' file://modsign.cfg', '', d)}"
