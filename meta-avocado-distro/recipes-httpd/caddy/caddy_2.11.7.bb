SUMMARY = "Caddy web server"
DESCRIPTION = "Caddy is an extensible HTTP server with automatic HTTPS."
HOMEPAGE = "https://caddyserver.com"
SECTION = "net"

LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://src/${GO_IMPORT}/LICENSE;md5=3b83ef96387f14655fc854ddc3c6bd57"
require ${BPN}-licenses.inc

SRC_URI = "git://github.com/caddyserver/caddy.git;protocol=https;branch=master;destsuffix=${GO_SRCURI_DESTSUFFIX}"
# tag v2.11.7
SRCREV = "72dd0fb067f6d7826c7f79907670ba4a713bfe37"
require ${BPN}-go-mods.inc

GO_IMPORT = "github.com/caddyserver/caddy/v2"
GO_INSTALL = "${GO_IMPORT}/cmd/caddy"
GO_LINKSHARED = ""
# Without this the binary reports "(devel)" because the module is built from
# a source tree rather than fetched by version.
GO_EXTRA_LDFLAGS = "-X ${GO_IMPORT}.CustomVersion=v${PV}"

inherit go-mod go-mod-update-modules

FILES:${PN}-src += "${libdir}/go/src"
