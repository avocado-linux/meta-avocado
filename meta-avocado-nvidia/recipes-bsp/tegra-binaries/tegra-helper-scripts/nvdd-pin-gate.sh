#!/bin/sh
# Stand-in for NVIDIA's nvdd while initrd-flash pins the NVMe flash target
# (ROOTFS_NVME_PCI). bootburn pushes it as /tmp/nvdd and runs every partition
# write and erase through it, for every device at once. It holds each call
# until the pin has made the named controller nvme0n1, then runs the real
# nvdd, which initrd-flash pushes as /tmp/nvdd.real before pinning. A failed
# pin, or none within NVDD_GATE_WAIT seconds, refuses the write.
#
# NVDD_GATE_DIR overrides /tmp (tests).
d="${NVDD_GATE_DIR:-/tmp}"
i=0
until [ -e "$d/nvme-pinned" ]; do
  if [ -e "$d/nvme-pin-failed" ] || [ "$i" -ge "${NVDD_GATE_WAIT:-900}" ]; then
    echo "nvdd-gate: the NVMe flash target was not pinned; refusing to write" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 1
done
exec "$d/nvdd.real" "$@"
