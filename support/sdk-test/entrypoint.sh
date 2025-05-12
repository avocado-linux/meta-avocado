#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

echo "--- Entrypoint: Installing Avocado SDK packages ---"
dnf update
dnf install -y avocado-sdk-qemux86-64 

echo "--- Entrypoint: Installing Avocado SDK toolchain ---"
dnf update
dnf install -y --setopt=tsflags=noscripts avocado-sdk-toolchain

mkdir -p /opt/avocado/sdk/avocado-qemux86-64/0.1.0/sysroots/core2-64-avocado-linux/var
dnf -y --setopt=tsflags=noscripts --installroot /opt/avocado/sdk/avocado-qemux86-64/0.1.0/sysroots/core2-64-avocado-linux/ install packagegroup-core-standalone-sdk-target

echo "--- Entrypoint: Handing over to CMD ($@) ---"
# Execute the command passed into the entrypoint (the original CMD or command:)

source /opt/avocado/sdk/avocado-qemux86-64/0.1.0/environment-setup-core2-64-avocado-linux
exec "$@" 
