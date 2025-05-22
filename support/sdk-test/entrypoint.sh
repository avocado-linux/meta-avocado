#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# avocado sdk install --config <avocado-config-file-path>

export AVOCADO_SDK_PREFIX="/opt/avocado/sdk"
export AVOCADO_SDK_SYSROOTS="${AVOCADO_SDK_PREFIX}/sysroots"
export DNF_SDK_HOST_PREFIX="${AVOCADO_SDK_PREFIX}"
export AVOCADO_SDK_MACHINE_TYPE="${AVOCADO_SDK_MACHINE_TYPE:-qemux86-64}"

export DNF_SDK_HOST_OPTS="\
    --setopt=cachedir=${DNF_SDK_HOST_PREFIX}/var/cache \
    --setopt=logdir=${DNF_SDK_HOST_PREFIX}/var/log \
    --setopt=varsdir=${DNF_SDK_HOST_PREFIX}/etc/dnf/vars \
    --setopt=persistdir=${DNF_SDK_HOST_PREFIX}/var/lib/dnf \
    --setopt=reposdir=${DNF_SDK_HOST_PREFIX}/etc/yum.repos.d \
"

export DNF_SDK_TARGET_OPTS="\
    --setopt=varsdir=${DNF_SDK_HOST_PREFIX}/etc/dnf/vars \
    --setopt=reposdir=${DNF_SDK_HOST_PREFIX}/etc/yum.repos.d \
    --setopt=tsflags=noscripts \
"

echo "--- Entrypoint: Installing Avocado SDK packages ---"
dnf check-update
dnf install -y "avocado-sdk-${AVOCADO_SDK_MACHINE_TYPE}"

echo "--- Entrypoint: Installing Avocado SDK toolchain ---"
dnf check-update $DNF_SDK_HOST_OPTS
dnf install -y --setopt=tsflags=noscripts $DNF_SDK_HOST_OPTS avocado-sdk-toolchain

source ${AVOCADO_SDK_PREFIX}/environment-setup

dnf install -y $DNF_SDK_TARGET_OPTS --installroot ${AVOCADO_SDK_SYSROOTS}/target-dev packagegroup-core-standalone-sdk-target
dnf install -y $DNF_SDK_TARGET_OPTS --installroot ${AVOCADO_SDK_SYSROOTS}/rootfs packagegroup-avocado-rootfs

mkdir -p ${AVOCADO_SDK_SYSROOTS}/sysext/${AVOCADO_SDK_PREFIX}/var/lib
mkdir -p ${AVOCADO_SDK_SYSROOTS}/confext/${AVOCADO_SDK_PREFIX}/var/lib
cp -rf ${AVOCADO_SDK_SYSROOTS}/rootfs/${AVOCADO_SDK_PREFIX}/var/lib/rpm ${AVOCADO_SDK_SYSROOTS}/sysext/${AVOCADO_SDK_PREFIX}/var/lib
cp -rf ${AVOCADO_SDK_SYSROOTS}/rootfs/${AVOCADO_SDK_PREFIX}/var/lib/rpm ${AVOCADO_SDK_SYSROOTS}/confext/${AVOCADO_SDK_PREFIX}/var/lib

echo "--- Entrypoint: Handing over to CMD ($@) ---"
# Execute the command passed into the entrypoint (the original CMD or command:)

set +e
exec "$@"
