# Enable nativesdk build for containerd in the SDK
BBCLASSEXTEND = "nativesdk"

# Strip target-specific runtime dependencies for nativesdk
RDEPENDS:${PN}:class-nativesdk = ""

# Disable systemd service installation for nativesdk
SYSTEMD_PACKAGES:class-nativesdk = ""

# Fix GOROOT for nativesdk: the recipe hardcodes GOROOT using
# STAGING_DIR_NATIVE/HOST_SYS which is wrong for nativesdk.
# go.bbclass defines GOROOT:class-nativesdk = "${STAGING_DIR_TARGET}${libdir}/go"
do_compile:class-nativesdk() {
    export GOARCH="${TARGET_GOARCH}"

    export GOPATH="${S}/src/import/.gopath:${S}/src/import/vendor:${STAGING_DIR_TARGET}/${prefix}/local/go:${WORKDIR}/git/"
    export GOROOT="${STAGING_DIR_TARGET}${libdir}/go"

    export CGO_ENABLED="1"
    export CGO_CFLAGS="${CFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export CGO_LDFLAGS="${LDFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export BUILDTAGS="no_btrfs static_build netgo"
    export CFLAGS="${CFLAGS}"
    export LDFLAGS="${LDFLAGS}"
    export SHIM_CGO_ENABLED="${CGO_ENABLED}"
    export GO_BUILD_FLAGS="-trimpath -a -pkgdir dontusecurrentpkgs"
    export GO111MODULE=off
    export VERSION="${CONTAINERD_VERSION}"

    cd ${S}

    oe_runmake binaries
}
