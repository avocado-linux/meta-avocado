#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Get the directory where this script is located
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Source the common functions
source "${SCRIPT_DIR}/avocado-sdk-common.sh"

# Get codename from environment or os-release
if [ -n "$AVOCADO_SDK_CODENAME" ]; then
    CODENAME="$AVOCADO_SDK_CODENAME"
else
    # Read VERSION_CODENAME from os-release, defaulting to "dev" if not found
    if [ -f /etc/os-release ]; then
        CODENAME=$(grep "^VERSION_CODENAME=" /etc/os-release | cut -d= -f2 | tr -d '"')
    fi
    CODENAME=${CODENAME:-dev}
fi

export AVOCADO_PREFIX="/opt/_avocado/${AVOCADO_SDK_TARGET}"
export AVOCADO_SDK_PREFIX="${AVOCADO_PREFIX}/sdk"
export AVOCADO_EXT_SYSROOTS="${AVOCADO_PREFIX}/extensions"
export DNF_SDK_HOST_PREFIX="${AVOCADO_SDK_PREFIX}"
export DNF_SDK_TARGET_PREFIX="${AVOCADO_SDK_PREFIX}/target-repoconf"
export DNF_SDK_HOST="\
    dnf \
    --releasever="$CODENAME" \
    --best \
    --setopt=tsflags=noscripts \
"

export DNF_SDK_HOST_OPTS="\
    --setopt=cachedir=${DNF_SDK_HOST_PREFIX}/var/cache \
    --setopt=logdir=${DNF_SDK_HOST_PREFIX}/var/log \
    --setopt=persistdir=${DNF_SDK_HOST_PREFIX}/var/lib/dnf \
"

export DNF_SDK_HOST_REPO_CONF="\
    --setopt=varsdir=${DNF_SDK_HOST_PREFIX}/etc/dnf/vars \
    --setopt=reposdir=${DNF_SDK_HOST_PREFIX}/etc/yum.repos.d \
"

export DNF_SDK_REPO_CONF="\
    --setopt=varsdir=${DNF_SDK_HOST_PREFIX}/etc/dnf/vars \
    --setopt=reposdir=${DNF_SDK_TARGET_PREFIX}/etc/yum.repos.d \
"

export DNF_SDK_TARGET_REPO_CONF="\
    --setopt=varsdir=${DNF_SDK_TARGET_PREFIX}/etc/dnf/vars \
    --setopt=reposdir=${DNF_SDK_TARGET_PREFIX}/etc/yum.repos.d \
"

export RPM_ETCCONFIGDIR="$AVOCADO_SDK_PREFIX"
export RPM_NO_CHROOT_FOR_SCRIPTS=1

if [ -f "${AVOCADO_SDK_PREFIX}/environment-setup" ]; then
    echo "--- Avocado SDK: Found ${AVOCADO_SDK_PREFIX}/environment-setup ---"
else
    echo "--- Avocado SDK: Installing Avocado SDK packages ---"
    # mkdir -p $AVOCADO_SDK_PREFIX/var/lib
    # cp -r /var/lib/rpm $AVOCADO_SDK_PREFIX/var/lib/
    # cp -r /var/cache $AVOCADO_SDK_PREFIX/var/cache/

    mkdir -p $AVOCADO_SDK_PREFIX/etc
    cp /etc/rpmrc $AVOCADO_SDK_PREFIX/etc
    cp -r /etc/rpm $AVOCADO_SDK_PREFIX/etc
    cp -r /etc/dnf $AVOCADO_SDK_PREFIX/etc
    cp -r /etc/yum.repos.d $AVOCADO_SDK_PREFIX/etc

    mkdir -p $AVOCADO_SDK_PREFIX/usr/lib/rpm
    cp -r /usr/lib/rpm/* $AVOCADO_SDK_PREFIX/usr/lib/rpm/

    # Before calling DNF $AVOCADO_SDK_PREFIX/usr/lib/rpm/marcos
    #  needs to be updated to point /usr -> $AVOCADO_SDK_PREFIX/usr
    #  and /var -> $AVOCADO_SDK_PREFIX/var
    sed -i "s|^%_usr[[:space:]]*/usr$|%_usr                   $AVOCADO_SDK_PREFIX/usr|" $AVOCADO_SDK_PREFIX/usr/lib/rpm/macros
    sed -i "s|^%_var[[:space:]]*/var$|%_var                   $AVOCADO_SDK_PREFIX/var|" $AVOCADO_SDK_PREFIX/usr/lib/rpm/macros

    RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
        RPM_ETCCONFIGDIR="$AVOCADO_SDK_PREFIX" \
        $DNF_SDK_HOST $DNF_SDK_HOST_OPTS $DNF_SDK_HOST_REPO_CONF -y install "avocado-sdk-${AVOCADO_SDK_TARGET}"

    RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
        RPM_ETCCONFIGDIR="$AVOCADO_SDK_PREFIX" \
        $DNF_SDK_HOST $DNF_SDK_HOST_OPTS $DNF_SDK_REPO_CONF check-update 

    RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
        RPM_ETCCONFIGDIR="$AVOCADO_SDK_PREFIX" \
        $DNF_SDK_HOST $DNF_SDK_HOST_OPTS $DNF_SDK_REPO_CONF -y install avocado-sdk-toolchain

    echo "--- Avocado SDK: Installing sdk target sysroot ---"
      RPM_ETCCONFIGDIR="$DNF_SDK_TARGET_PREFIX" \
      $DNF_SDK_HOST $DNF_SDK_TARGET_REPO_CONF \
       -y --installroot ${AVOCADO_PREFIX}/sdk/target-sysroot install packagegroup-core-standalone-sdk-target

    echo "--- Avocado SDK: Installing rootfs sysroot ---"
      RPM_ETCCONFIGDIR="$DNF_SDK_TARGET_PREFIX" \
      $DNF_SDK_HOST $DNF_SDK_TARGET_REPO_CONF \
      -y --installroot ${AVOCADO_PREFIX}/rootfs install avocado-pkg-rootfs

    echo "--- Avocado SDK: Setting up sysext|confext sysroots ---"
    mkdir -p ${AVOCADO_PREFIX}/sysext/var/lib
    mkdir -p ${AVOCADO_PREFIX}/confext/var/lib
    cp -rf ${AVOCADO_PREFIX}/rootfs/var/lib/rpm ${AVOCADO_PREFIX}/sysext/var/lib
    cp -rf ${AVOCADO_PREFIX}/rootfs/var/lib/rpm ${AVOCADO_PREFIX}/confext/var/lib
fi

echo "--- Avocado SDK: Changing working directory to /opt/_avocado/src ---"
cd /opt/_avocado/src

exec "$@"
