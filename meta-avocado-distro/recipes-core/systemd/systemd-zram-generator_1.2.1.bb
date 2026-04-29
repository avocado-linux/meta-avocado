inherit cargo cargo-update-recipe-crates pkgconfig systemd

SUMMARY = "Systemd unit generator for zram devices"
HOMEPAGE = "https://github.com/systemd/zram-generator"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=3fced11d6df719b47505837a51c16ae5"

DEPENDS = "systemd"
RRECOMMENDS:${PN} = "kernel-module-zram kernel-module-lz4 kernel-module-lz4-compress"

PV = "1.2.1"
SRCREV = "7855941d1a06257075e7f5a268b1f7bb702d5466"
SRC_URI = "git://github.com/systemd/zram-generator.git;protocol=https;branch=main"

require ${BPN}-crates.inc

B = "${S}"

CARGO_SRC_DIR = ""

# Substitute 'frozen' with 'offline'
CARGO_BUILD_FLAGS = "-v --offline --target ${RUST_HOST_SYS} ${BUILD_MODE} --manifest-path=${CARGO_MANIFEST_PATH}"
do_update_crates[depends] = "cargo-native:do_populate_sysroot"
do_update_crates:prepend() {
	${CARGO} fetch --manifest-path ${CARGO_MANIFEST_PATH}
}

do_compile() {
	# Work around panic = "abort" errors, see https://github.com/meta-rust/meta-rust/issues/343
	sed -i /panic/d Cargo.toml
	export RUSTFLAGS="${RUSTFLAGS}"
	oe_runmake build NOMAN=true CARGO="${CARGO}" CARGOFLAGS="${CARGO_BUILD_FLAGS}" BUILDTYPE="OpenEmbedded"
}

do_install() {
	oe_runmake install NOBUILD=true NOMAN=true BUILDTYPE="${RUST_HOST_SYS}/release" DESTDIR="${D}" PREFIX="${prefix}"
}

FILES:${PN} += "${systemd_unitdir}"
