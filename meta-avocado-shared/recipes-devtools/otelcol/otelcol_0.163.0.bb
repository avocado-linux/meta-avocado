SUMMARY = "Minimal OpenTelemetry Collector for shipping journal logs"
DESCRIPTION = "An OpenTelemetry Collector distribution built with ocb from otelcol/manifest.yaml. It carries only the components a journal-to-OTLP log pipeline uses, in place of the several hundred in otelcol-contrib."
HOMEPAGE = "https://github.com/open-telemetry/opentelemetry-collector"
SECTION = "net"

LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"
require ${BPN}-licenses.inc

# components.go, main*.go, go.mod and go.sum are the output of
#   ocb --config manifest.yaml --skip-compilation
# with ocb v0.163.0 (go install go.opentelemetry.io/collector/cmd/builder@v0.163.0).
# Regenerate them and the -go-mods.inc and -licenses.inc files together when the
# manifest changes or the collector version moves.
SRC_URI = " \
    file://manifest.yaml;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://components.go;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://main.go;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://main_others.go;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://main_windows.go;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://go.mod;subdir=${GO_SRCURI_DESTSUFFIX} \
    file://go.sum;subdir=${GO_SRCURI_DESTSUFFIX} \
"
require ${BPN}-go-mods.inc

GO_IMPORT = "github.com/avocado-linux/otelcol"
GO_INSTALL = "${GO_IMPORT}"
GO_LINKSHARED = ""
GOBUILDFLAGS:append = " -tags=grpcnotrace"

inherit go-mod go-mod-update-modules

# go.mod asks for go 1.26.0, which the tree's Go satisfies; this keeps Go from
# fetching a newer toolchain, which has no network in do_compile.
export GOTOOLCHAIN = "local"

# The unit and the configuration belong to whatever runs the collector, so this
# package ships the binary only. The journald receiver runs journalctl.
RDEPENDS:${PN} += "systemd"

FILES:${PN}-src += "${libdir}/go/src"
