FILESEXTRAPATHS:prepend := "${THISDIR}/linux-raspberrypi-6.6:"

# The generated consolemap_deftbl.c names its input by absolute path, which
# ships in the -src package once kernel debug sources do.
# Fixed upstream in v6.11; the 6.12 kernel already has it.
SRC_URI += "file://0001-tty-vt-conmakehash-remove-non-portable-code-printing.patch"
