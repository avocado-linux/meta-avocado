#!/bin/bash

set -e

qemu-system-x86_64 \
  -drive file=/opt/_avocado/images/avocado-image-rootfs-avocado-qemux86-64.rootfs.wic,format=raw,if=virtio \
  -drive if=pflash,format=qcow2,readonly=on,file=/opt/_avocado/bootfiles/ovmf.code.qcow2 \
  -drive if=pflash,format=qcow2,file=/opt/_avocado/bootfiles/ovmf.vars.qcow2 \
  -m 256 \
  -cpu max \
  -nographic
