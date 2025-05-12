#!/bin/bash

set -e

qemu-system-x86_64 \
  -drive file=/images/avocado-qemux86-64/avocado-image-rootfs-avocado-qemux86-64.rootfs.wic,format=raw,if=virtio \
  -drive if=pflash,format=qcow2,readonly=on,file=/images/avocado-qemux86-64/ovmf.code.qcow2 \
  -drive if=pflash,format=qcow2,file=/images/avocado-qemux86-64/ovmf.vars.qcow2 \
  -m 256 \
  -cpu max \
  -nographic
