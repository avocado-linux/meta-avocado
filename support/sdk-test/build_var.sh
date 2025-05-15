#!/bin/bash

set -e

mkdir -p ~/avocado-qemux86-64/rootfs/var

dnf -y install avocado-extension-debug-tweaks \
    --setopt=tsflags=noscripts \
    --installroot ~/avocado-qemux86-64/rootfs/

rm -f /images/avocado-qemux86-64/avocado-image-var-avocado-qemux86-64.btrfs

mkfs.btrfs -r ~/avocado-qemux86-64/rootfs/var \
    --subvol rw:lib/extensions --subvol rw:lib/confexts \
    -f /images/avocado-qemux86-64/avocado-image-var-avocado-qemux86-64.btrfs

sync
