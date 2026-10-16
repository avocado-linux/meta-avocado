SUMMARY = "NATS messaging server with JetStream"
DESCRIPTION = "High-performance message broker. JetStream adds persistent streams and key-value buckets."
HOMEPAGE = "https://github.com/nats-io/nats-server"
SECTION = "net"

LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://src/${GO_IMPORT}/LICENSE;md5=86d3f3a95c324c9479bd8986968f4327"
require ${BPN}-licenses.inc

SRC_URI = "git://github.com/nats-io/nats-server.git;protocol=https;branch=release/v${PV};destsuffix=${GO_SRCURI_DESTSUFFIX}"
SRCREV = "b2fd3efc7456b11b06a54877ad6f6ccfb911edb4"
require ${BPN}-go-mods.inc

GO_IMPORT = "github.com/nats-io/nats-server/v2"
GO_INSTALL = "${GO_IMPORT}"
GO_LINKSHARED = ""

# go.mod names toolchain go1.26.8 while the tree builds with go 1.26.5. Left to
# itself, go downloads the newer toolchain into the module cache, which fails
# in do_compile (no network) and breaks do_update_modules, whose package list
# then carries no module data. The "go" line (1.26.0) is what the code needs.
export GOTOOLCHAIN = "local"

inherit go-mod go-mod-update-modules

# The unit and the configuration belong to whatever runs the broker, so this
# package ships the binary only. go.bbclass installs into ${bindir}; the
# server is a daemon, so it goes in ${sbindir}.
do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${B}/${GO_BUILD_BINDIR}/nats-server ${D}${sbindir}/nats-server
}

# Go sources land here and QA flags the scripts they carry.
FILES:${PN}-src += "${libdir}/go/src"
