#!/bin/sh
# Make one NVMe controller the flash target: nvme0n1, with every other NVMe
# controller unbound.
#
# Runs on the target, in the T264 flashing initramfs (pushed over adb by
# initrd-flash). NVIDIA's unified flash writes the external device by name
# (nvme0n1), and on a carrier with two NVMe slots the name is whichever
# controller's PCIe link came up first: the same flash lands on either disk.
# Pinning by PCIe address makes it the same disk every time.
#
# usage: nvme-pin-for-flash <pci-address>     e.g. 0005:01:00.0
# SYSFS overrides /sys (tests).
set -u

pci="${1:-}"
sys="${SYSFS:-/sys}"
drv="$sys/bus/pci/drivers/nvme"
dev="$sys/bus/pci/devices/$pci"

case "$pci" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f].[0-7]) ;;
  *)
    echo "nvme-pin: '$pci' is not a PCI address (dddd:bb:dd.f)" >&2
    exit 1
    ;;
esac

if [ ! -d "$dev" ]; then
  echo "nvme-pin: no PCI device $pci" >&2
  exit 1
fi

# Unbind every other NVMe controller first: the flash cannot touch a disk with
# no driver, and its nvme index is freed for the target.
for d in "$drv"/????:??:??.?; do
  [ -e "$d" ] || continue
  a="${d##*/}"
  [ "$a" = "$pci" ] && continue
  echo "$a" >"$drv/unbind" && echo "nvme-pin: unbound $a"
done

# A target that is not nvme0 is rebound so it takes the lowest free index.
if [ ! -e "$dev/nvme/nvme0" ]; then
  [ -e "$drv/$pci" ] && echo "$pci" >"$drv/unbind"
  echo "$pci" >"$drv/bind"
fi

i=0
while [ "$i" -lt "${NVME_PIN_WAIT:-30}" ]; do
  if [ -e "$dev/nvme/nvme0/nvme0n1" ]; then
    echo "NVME-PINNED $pci nvme0n1"
    exit 0
  fi
  i=$((i + 1))
  sleep 1
done
echo "nvme-pin: $pci did not come back as nvme0n1" >&2
exit 1
