# The raw var partition and its systemd device unit, for the initramfs units
# that must wait for it (avocado-var-grow, cryptsetup-var). /var itself mounts
# /dev/disk/by-avocado/var (base-files), which stops naming the raw partition
# once it carries a LUKS header, so these units need the partition's own path.
#
# A GPT label path (/dev/disk/by-partlabel/<name>) or a PARTUUID is resolved
# through /dev/disk/by-avocado/var-partition, which base-files' 61-avocado-var
# rule gives that partition only on the disk the root comes from: two Avocado
# disks in one machine both carry the label. A raw node (/dev/mmcblk0p3 on
# Raspberry Pi's MBR disk) already names one disk and is used as is. Anything
# else - "none" (Jetson, where avocado-tegra-init mounts /var), unset - falls
# back to the label every GPT layout gives its var partition.

AVOCADO_VAR_PART_DEV ??= ""

def avocado_var_device(d):
    dev = d.getVar('AVOCADO_VAR_PART_DEV') or ''
    if dev.startswith('/dev/disk/by-partlabel/') or dev.startswith('/dev/disk/by-partuuid/') or dev.startswith('PARTUUID='):
        return '/dev/disk/by-avocado/var-partition'
    if dev.startswith('/dev/') and '/' not in dev[len('/dev/'):]:
        return dev
    return '/dev/disk/by-partlabel/var'

def avocado_var_device_unit(d):
    """systemd-escape --path of avocado_var_device(): leading '/' dropped,
    '-' escaped as \\x2d, '/' -> '-'. The backslash is doubled on the way out
    because the only consumer is a sed replacement, where a lone \\x is an
    escape sequence and would be eaten - which is how imx8mp-evk ended up
    waiting for `/dev/disk/by/partlabel/var` and dropping to emergency."""
    dev = avocado_var_device(d)
    escaped = dev.lstrip('/').replace('-', '\\x2d').replace('/', '-') + '.device'
    return escaped.replace('\\', '\\\\')

AVOCADO_VAR_DEVICE = "${@avocado_var_device(d)}"
AVOCADO_VAR_DEVICE_UNIT = "${@avocado_var_device_unit(d)}"

# Both values are baked into units by sed at do_install: the signature must
# follow the variable, or sstate hands back a unit for the old partition.
do_install[vardeps] += "AVOCADO_VAR_PART_DEV"

# A machine value baked into the package makes the package machine-specific:
# at the tune arch, two machines sharing a tune (Raspberry Pi Zero 2 W and
# i.MX8M Plus are both cortexa53) would build one NEVRA with different units,
# and a shared feed would hand one machine the other's.
PACKAGE_ARCH = "${MACHINE_ARCH}"
