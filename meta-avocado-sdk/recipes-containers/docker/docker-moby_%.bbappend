# Enable nativesdk build for docker (CLI + daemon) in the SDK
BBCLASSEXTEND = "nativesdk"

# Disable seccomp for nativesdk - not needed on the SDK host
PACKAGECONFIG:remove:class-nativesdk = "seccomp docker-init"

# Strip target-specific dependencies that don't apply to the SDK host
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
    ln -sf ../../../.. .gopath/src/"${DOCKER_PKG}"

    mkdir -p .gopath/src/github.com/docker
    ln -sf ${WORKDIR}/git/libnetwork .gopath/src/github.com/docker/libnetwork
    ln -sf ${WORKDIR}/git/cli .gopath/src/github.com/docker/cli

    export GOPATH="${S}/src/import/.gopath:${S}/src/import/vendor"
    export GOROOT="${STAGING_DIR_TARGET}${libdir}/go"

    export GOARCH=${TARGET_GOARCH}
    export CGO_ENABLED="1"
    export CGO_CFLAGS="${CFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export CGO_LDFLAGS="${LDFLAGS} --sysroot=${STAGING_DIR_TARGET}"
    export DOCKER_BUILDTAGS='${BUILD_TAGS} ${PACKAGECONFIG_CONFARGS}'
    export GO111MODULE=off

    export DISABLE_WARN_OUTSIDE_CONTAINER=1

    cd ${S}/src/import/

    VERSION="${DOCKER_VERSION}" DOCKER_GITCOMMIT="${DOCKER_COMMIT}" ./hack/make.sh dynbinary

    # build the cli - use the real source directory (not the GOPATH symlink)
    # so Go finds the CLI's own go.mod correctly in module-aware mode
    cd ${WORKDIR}/git/cli
    export CFLAGS=""
    export LDFLAGS=""
    export DOCKER_VERSION=${DOCKER_VERSION}
    export GO111MODULE=auto
    VERSION="${DOCKER_VERSION}" DOCKER_GITCOMMIT="${DOCKER_COMMIT}" make dynbinary

    # build the proxy
    cd ${S}/src/import/.gopath/src/github.com/docker/libnetwork
    oe_runmake cross-local
}
