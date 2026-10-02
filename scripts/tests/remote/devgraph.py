"""A scriptable fake of the block-device graph the root-backing guard walks.

The guard reads three things through the ops layer's read-only filesystem
seam: ``realpath`` of a node, the ``partition`` attribute of a sysfs entry
(absent for a whole device) and the ``slaves`` directory of a whole device.
``Graph.script()`` returns the RecordingOps script lines that answer those
reads, so a test can describe a device graph the way sysfs would.
"""

from __future__ import annotations

SYS = "/sys/class/block"


class Graph:
    def __init__(self):
        self._s: dict = {}

    def disk(self, name, slaves=(), sysnode=None):
        """A whole device. ``sysnode`` mimics where sysfs really keeps it (nvme is not under .../block)."""
        real = sysnode or f"/sys/devices/virtual/block/{name}"
        self._s[f"realpath /dev/{name}"] = f"/dev/{name}\n"
        self._s[f"realpath {SYS}/{name}"] = real + "\n"
        self._s[f"read_file {SYS}/{name}/partition"] = FileNotFoundError(f"{SYS}/{name}/partition")
        self._s[f"listdir {SYS}/{name}/slaves"] = "".join(f"{s}\n" for s in slaves)
        self._s[f"__real__{name}"] = real
        return self

    def part(self, disk, name, number):
        """A partition of ``disk``; sysfs nests it under the disk's own directory."""
        real = self._s[f"__real__{disk}"] + f"/{name}"
        self._s[f"realpath /dev/{name}"] = f"/dev/{name}\n"
        self._s[f"realpath {SYS}/{name}"] = real + "\n"
        self._s[f"read_file {SYS}/{name}/partition"] = f"{number}\n"
        return self

    def link(self, path, target_name):
        """A symlink node (/dev/root, /dev/disk/by-uuid/...) that resolves to /dev/<target_name>."""
        self._s[f"realpath {path}"] = f"/dev/{target_name}\n"
        return self

    def script(self) -> dict:
        return {k: v for k, v in self._s.items() if not k.startswith("__real__")}


def standard() -> Graph:
    """The boards the existing tests describe: an eMMC, an NVMe SSD, a SATA disk and a virtio disk."""
    g = Graph()
    g.disk("mmcblk0", sysnode="/sys/devices/platform/3460000.mmc/mmc_host/mmc0/mmc0:0001/block/mmcblk0")
    for n in range(1, 17):
        g.part("mmcblk0", f"mmcblk0p{n}", n)
    g.disk("nvme0n1", sysnode="/sys/devices/pci0000:00/0000:00:01.0/nvme/nvme0/nvme0n1")
    for n in (1, 2):
        g.part("nvme0n1", f"nvme0n1p{n}", n)
    g.disk("sda", sysnode="/sys/devices/pci0000:00/ata1/host0/target0:0:0/0:0:0:0/block/sda")
    g.part("sda", "sda1", 1)
    g.disk("vdz", sysnode="/sys/devices/pci0000:00/virtio1/block/vdz")
    for n in range(1, 4):
        g.part("vdz", f"vdz{n}", n)
    return g


def standard_script() -> dict:
    return standard().script()
