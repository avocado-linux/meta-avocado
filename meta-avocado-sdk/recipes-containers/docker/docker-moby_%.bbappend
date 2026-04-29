# Enable nativesdk build for docker (CLI + daemon) in the SDK
BBCLASSEXTEND = "nativesdk"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
# Same wazero //go:linkname / DCE issue as nativesdk-containerd
# (docker vendors the same wazero). Patch adds receiving-side
# `//go:linkname` opt-in directives so Go's linker keeps the asm
# entrypoints alive across DCE. patchdir=src/import because docker's
# vendor tree lives one level deeper than the recipe S.
SRC_URI:append:class-nativesdk = " file://0001-wazero-Add-go-linkname-opt-in-for-DCE-safety.patch;patchdir=src/import"

# Disable seccomp for nativesdk - not needed on the SDK host
PACKAGECONFIG:remove:class-nativesdk = "seccomp docker-init"

# wrynose: bitbake.conf filters nativesdk DISTRO_FEATURES down to
# "acl x11 ipv6 xattr". Upstream docker.inc declares
# REQUIRED_DISTRO_FEATURES ?= "seccomp ipv6" + inherits features_check,
# so the nativesdk variant gets silently skipped (seccomp missing) and
# nothing PROVIDES nativesdk-docker. We disable seccomp for the SDK
# build via PACKAGECONFIG above anyway, so drop the requirement here.
REQUIRED_DISTRO_FEATURES:class-nativesdk = "ipv6"

# Strip lvm2 from nativesdk DEPENDS — we don't run lvm storage driver
# in the SDK build. nftables/libnftnl stay: docker's libnetwork has
# cgo bindings (`daemon/libnetwork/internal/nftables/...`) that need
# `libnftables.pc` and headers at compile time, even though the
# resulting daemon won't actually manage host firewall on the SDK.
DEPENDS:remove:class-nativesdk = "lvm2"
# Keep containerd and runc as RDEPENDS (matching target behavior), but remove
# target-only runtime deps (iptables, util-linux, bridge-utils, etc.)
RDEPENDS:${PN}:class-nativesdk = "${PN}-cli virtual-containerd ${VIRTUAL-RUNTIME_container_runtime}"
RRECOMMENDS:${PN}:class-nativesdk = ""

# Disable systemd/sysvinit service installation for nativesdk
SYSTEMD_PACKAGES:class-nativesdk = ""
INITSCRIPT_PACKAGES:class-nativesdk = ""

# Disable useradd for nativesdk
USERADD_PACKAGES:class-nativesdk = ""

# Fix GOROOT for nativesdk: docker.inc hardcodes GOROOT using
# STAGING_DIR_NATIVE/HOST_SYS which is wrong for nativesdk.
# go.bbclass defines GOROOT:class-nativesdk = "${STAGING_DIR_TARGET}${libdir}/go"
# Override do_compile to use the correct GOROOT for nativesdk.
do_compile:class-nativesdk() {
    cd ${S}/src/import
    rm -rf .gopath
    mkdir -p .gopath/src/"$(dirname "${DOCKER_PKG}")"
    ln -sf ../../../../.. .gopath/src/"${DOCKER_PKG}"

    mkdir -p .gopath/src/github.com/docker
    ln -sf ${S}/cli .gopath/src/github.com/docker/cli

    export GOPATH="${S}/src/import/.gopath:${S}/src/import/vendor"
    export GOROOT="${STAGING_DIR_TARGET}${libdir}/go"

    export GOARCH=${TARGET_GOARCH}
    export CGO_ENABLED="1"
    export CGO_CFLAGS="${CFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export CGO_LDFLAGS="${LDFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export DOCKER_BUILDTAGS='${BUILD_TAGS} ${PACKAGECONFIG_CONFARGS}'
    export GO111MODULE=off

    export DISABLE_WARN_OUTSIDE_CONTAINER=1
    export BUILDFLAGS="-trimpath"

    cd ${S}/src/import/

    VERSION="${DOCKER_VERSION}" DOCKER_GITCOMMIT="${DOCKER_COMMIT}" ./hack/make.sh dynbinary

    # build the cli - use the real source directory (not the GOPATH symlink)
    # so Go finds the CLI's own go.mod correctly in module-aware mode
    cd ${S}/cli
    export CFLAGS=""
    export LDFLAGS=""
    export DOCKER_VERSION=${DOCKER_VERSION}
    export GO111MODULE=auto
    export BUILDFLAGS="-trimpath"
    VERSION="${DOCKER_VERSION}" DOCKER_GITCOMMIT="${DOCKER_COMMIT}" make dynbinary
}
