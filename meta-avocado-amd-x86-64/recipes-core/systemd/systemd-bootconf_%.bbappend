# AMD boot entry. meta-avocado-x86-64's bbappend installs its own
# avocado-boot.conf for every machine that carries that layer, this one
# included; its console=ttyS0 points at a legacy UART this board's header is
# not wired to. A distinct filename, so which layer's files/ wins the FILESPATH
# search never decides which entry ships - this one replaces it after install.
# Every hook is machine-scoped, so an Intel build that stacks this layer keeps
# its own entry.
FILESEXTRAPATHS:prepend:avocado-amd-x86-64 := "${THISDIR}/files:"

SRC_URI:append:avocado-amd-x86-64 = " file://avocado-boot-amd.conf"

do_install:append:avocado-amd-x86-64() {
    install -m 0644 ${S}/avocado-boot-amd.conf ${D}/boot/loader/entries/avocado.conf
}

do_deploy:append:avocado-amd-x86-64() {
    install -D ${S}/avocado-boot-amd.conf ${DEPLOYDIR}/avocado.conf
}
