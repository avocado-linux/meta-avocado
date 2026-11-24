FILESEXTRAPATHS:prepend := "${THISDIR}/linux-raspberrypi-6.6:"

# The generated consolemap_deftbl.c names its input by absolute path, which
# the -src package's buildpaths QA rejects once kernel debug sources ship.
# Fixed upstream in v6.11; the 6.12 kernel already has it.
SRC_URI += "file://0001-tty-vt-conmakehash-remove-non-portable-code-printing.patch"
