#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

export AVOCADO_SDK_PREFIX="/opt/_avocado/sdk"
export AVOCADO_SDK_SYSROOTS="${AVOCADO_SDK_PREFIX}/sysroots"
export DNF_SDK_HOST_PREFIX="${AVOCADO_SDK_PREFIX}"
export DNF_SDK_HOST="\
    dnf \
    --setopt=varsdir=${DNF_SDK_HOST_PREFIX}/etc/dnf/vars \
    --setopt=reposdir=${DNF_SDK_HOST_PREFIX}/etc/yum.repos.d \
    --releasever=dev \
    --best \
    --setopt=tsflags=noscripts \
"

export DNF_SDK_HOST_OPTS="\
    --setopt=cachedir=${DNF_SDK_HOST_PREFIX}/var/cache \
    --setopt=logdir=${DNF_SDK_HOST_PREFIX}/var/log \
    --setopt=persistdir=${DNF_SDK_HOST_PREFIX}/var/lib/dnf \
"

export RPM_ETCCONFIGDIR="$AVOCADO_SDK_PREFIX"
export RPM_NO_CHROOT_FOR_SCRIPTS=1

if [ -f "${AVOCADO_SDK_PREFIX}/environment-setup" ]; then
    echo "--- Avocado SDK: Found ${AVOCADO_SDK_PREFIX}/environment-setup ---"
else
    echo "--- Avocado SDK: Installing Avocado SDK packages ---"
    mkdir -p $AVOCADO_SDK_PREFIX/var/lib
cp -r /var/lib/rpm $AVOCADO_SDK_PREFIX/var/lib/
cp -r /var/cache $AVOCADO_SDK_PREFIX/var/cache/

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
sed -i 's|^%_usr[[:space:]]*/usr$|%_usr                   /opt/_avocado/sdk/usr|' $AVOCADO_SDK_PREFIX/usr/lib/rpm/macros
sed -i 's|^%_var[[:space:]]*/var$|%_var                   /opt/_avocado/sdk/var|' $AVOCADO_SDK_PREFIX/usr/lib/rpm/macros

RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
    $DNF_SDK_HOST $DNF_SDK_HOST_OPTS -y install "avocado-sdk-${AVOCADO_SDK_TARGET}"

RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
    $DNF_SDK_HOST $DNF_SDK_HOST_OPTS check-update 

RPM_CONFIGDIR="$AVOCADO_SDK_PREFIX/usr/lib/rpm" \
    $DNF_SDK_HOST $DNF_SDK_HOST_OPTS -y install avocado-sdk-toolchain

echo "--- Avocado SDK: Installing target-dev sysroot ---"
$DNF_SDK_HOST -y --installroot ${AVOCADO_SDK_SYSROOTS}/target-dev install packagegroup-core-standalone-sdk-target
echo "--- Avocado SDK: Installing rootfs sysroot ---"
$DNF_SDK_HOST -y --installroot ${AVOCADO_SDK_SYSROOTS}/rootfs install nativesdk-avocado-pkg-rootfs

echo "--- Avocado SDK: Setting up sysext|confext sysroots ---"
mkdir -p ${AVOCADO_SDK_SYSROOTS}/sysext/var/lib
mkdir -p ${AVOCADO_SDK_SYSROOTS}/confext/var/lib
cp -rf ${AVOCADO_SDK_SYSROOTS}/rootfs/var/lib/rpm ${AVOCADO_SDK_SYSROOTS}/sysext/var/lib
cp -rf ${AVOCADO_SDK_SYSROOTS}/rootfs/var/lib/rpm ${AVOCADO_SDK_SYSROOTS}/confext/var/lib
fi

echo "--- Avocado SDK: Changing working directory to /opt ---"
cd /opt

echo "--- Avocado SDK: Handing over to CMD ($@) ---"

set +e
exec "$@"
