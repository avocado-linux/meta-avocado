# Enable nativesdk build for containerd in the SDK
BBCLASSEXTEND = "nativesdk"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
# wazero (vendored by containerd 2.2.x) uses //go:linkname from
# wazevo/entrypoint_{amd64,arm64}.go to wire to asm-defined entrypoints
# in a peer package. Go 1.23+ requires the receiving side to opt in
# with `//go:linkname`, otherwise DCE drops the asm symbol and the
# external linker fails with "undefined reference to ...amd64.entrypoint".
# `-checklinkname=0` only relaxes parsing — doesn't keep the symbol
# alive. This patch adds the opt-in directive on the receiving side.
SRC_URI:append:class-nativesdk = " file://0001-wazero-Add-go-linkname-opt-in-for-DCE-safety.patch"

# Strip target-specific runtime dependencies for nativesdk
RDEPENDS:${PN}:class-nativesdk = ""

# nativesdk-containerd is only used to back avocado-cli's nativesdk-docker
# (image pull + /var pre-seed). It never actually runs containers on
# the SDK host, so the CNI networking plugin subpackage and its
# dependency on nativesdk-cni are dead weight. Drop the -cni subpackage
# from the nativesdk variant entirely.
PACKAGES:remove:class-nativesdk = "${PN}-cni"
RDEPENDS:${PN}-cni:class-nativesdk = ""
FILES:${PN}-cni:class-nativesdk = ""

# Disable systemd service installation for nativesdk
SYSTEMD_PACKAGES:class-nativesdk = ""

# Fix GOROOT for nativesdk: the recipe hardcodes GOROOT using
# STAGING_DIR_NATIVE/HOST_SYS which is wrong for nativesdk.
# go.bbclass defines GOROOT:class-nativesdk = "${STAGING_DIR_TARGET}${libdir}/go"
do_compile:class-nativesdk() {
    export GOARCH="${TARGET_GOARCH}"

    export GOPATH="${S}/src/import/.gopath:${S}/src/import/vendor:${STAGING_DIR_TARGET}/${prefix}/local/go:${UNPACKDIR}/git/"
    export GOROOT="${STAGING_DIR_TARGET}${libdir}/go"

    export CGO_ENABLED="1"
    export CGO_CFLAGS="${CFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export CGO_LDFLAGS="${@d.getVar('LDFLAGS').replace('-pie', '')} --sysroot=${STAGING_DIR_TARGET}"
    # Drop static_build for nativesdk: it conflicts with wazero's
    # amd64 assembly entrypoints (used by containerd 2.2.x for the
    # WASM runtime), causing "undefined reference to ...entrypoint"
    # link failures. Static linking adds nothing on the SDK host
    # (we have a runtime sysroot) and breaks cgo+native-asm builds.
    export BUILDTAGS="no_btrfs netgo"

    export CFLAGS="${CFLAGS}"
    # wazero's amd64 asm has text relocations which conflict with -pie
    # ("creating DT_TEXTREL in a PIE" -> ld rejects -> undefined refs).
    # Strip -pie from the external-linker LDFLAGS for the nativesdk
    # build (the SDK toolchain pulls -pie in via security_flags.inc).
    export LDFLAGS="${@d.getVar('LDFLAGS').replace('-pie', '')} -no-pie"
    export SHIM_CGO_ENABLED="${CGO_ENABLED}"
    # Tell Go to produce a non-PIE executable. Default cgo+linux buildmode
    # is `pie`, which adds `-pie` to the external (gcc) link step
    # regardless of what we put in LDFLAGS.
    export GO_BUILD_FLAGS="-trimpath -a -pkgdir dontusecurrentpkgs -buildmode=exe"
    export GO111MODULE=off
    export VERSION="${CONTAINERD_VERSION}"

    # OE's go.bbclass sets GODEBUG=gocachehash=1 (Go runtime cache-trace
    # var). containerd's Makefile mis-uses `ifndef GODEBUG ... else
    # DEBUG_TAGS := static_build endif` and treats ANY non-empty GODEBUG
    # as "user wants debug build", which forces `static_build` into
    # BUILDTAGS. Unset to keep us out of the static_build path.
    unset GODEBUG

    # wazero uses `//go:linkname entrypoint .../amd64.entrypoint` to wire
    # its wazevo engine to amd64 asm in a peer package. Go 1.23+ tightened
    # `//go:linkname` rules — by default the linker rejects cross-package
    # references like this unless the target package also annotates with
    # `//go:linkname`, which wazero hasn't done. Wrynose ships Go 1.26.1
    # which strictly enforces the check, so the daemon link fails with
    # "undefined reference to ...amd64.entrypoint" cascades. Pass
    # `-checklinkname=0` to relax the check (containerd's Makefile threads
    # EXTRA_LDFLAGS into the go build's `-ldflags`).
    export EXTRA_LDFLAGS="-checklinkname=0"

    cd ${S}

    oe_runmake binaries
}
