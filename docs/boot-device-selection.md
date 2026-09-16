# Selecting the boot device

On a board carrying more than one bootable disk, "where the image was written"
and "which disk the board boots" are two separate decisions, and only the first
one is made at provision time.

`avocado provision --profile tegraflash-nvme` writes a complete, bootable NVMe
and reports success. If the board also has a provisioned SD card, it keeps
booting the SD card, because the firmware picks the boot device and nothing in
the provisioning flow tells it to prefer the disk that was just written. A
Jetson makes this vivid: its UEFI creates a `UEFI SD Device` entry on its own
and places it at the front of `BootOrder`.

`avocado-set-boot-device` is the runtime half of that decision. It moves no
data. It tells the firmware which of the disks already present to prefer.

## Using it

The tool ships as the `avocado-boot-device` package. Add it to a runtime
extension in `avocado.yaml`:

```yaml
extensions:
  boot-device:
    types:
      - sysext
    version: "1.0.0"
    packages:
      avocado-boot-device: "*"

runtimes:
  dev:
    extensions:
      - boot-device
```

Then, on the board:

```console
# avocado-set-boot-device --list
Current boot order, first entry wins:

  Boot0001* UEFI SD Device  VenHw(...)/SD(0)
  Boot0003* UEFI Samsung SSD 960 EVO 250GB  PciRoot(0x0)/.../NVMe(0x1,...)

Recognised device classes on this board:
  nvme  0003
  sd    0001
  emmc  -
  usb   -

# avocado-set-boot-device nvme
Boot device: nvme (entry 0003)
  before: 0001,0003,0000,0002
  after:  0003,0001,0000,0002
BootOrder=0003,0001,0000,0002
```

The device classes are `nvme`, `sd`, `emmc` and `usb`.

## Test with `--once` first

`--once` writes `BootNext` instead of `BootOrder`, so the selection applies to
the next boot and then reverts on its own:

```console
# avocado-set-boot-device --once nvme
Next boot only: 0003 (nvme)
BootNext=0003
```

Prefer this while you are finding out whether a disk boots at all. A permanent
`BootOrder` pointing at a disk that turns out not to boot needs someone at the
board with a console; a `BootNext` that fails is undone by the power cycle that
follows it.

`--dry-run` prints the order that would be written and changes nothing.

## What it will not do

**It will not create a boot entry.** The firmware creates an entry for a disk
it can see and boot, so a disk that was provisioned but never booted may have
no entry yet. Reboot once so the firmware enumerates it, then run the tool
again. `--list` shows what exists.

**It will not guess.** If two entries match a class it says so and uses the
first; if none match it fails and prints the entries it did find, rather than
picking something and reporting success.

**It will not report a write it cannot confirm.** Both paths read the variable
back after writing and fail if it does not hold the expected value. efivarfs
can accept a write that the firmware then discards, and a boot selection that
silently did not take is the failure this tool exists to prevent.

## The other half

Choosing the boot device only settles which kernel the firmware loads. Which
rootfs that kernel then mounts is decided separately, by the PARTUUID the
provisioning flow writes into the kernel command line. Both halves have to
agree, or a board can boot one disk's kernel against another disk's rootfs.

If your board predates that change, the initrd finds its rootfs by PARTLABEL
instead - and on a board with two provisioned disks both carry a partition
labelled `APP`, so it takes whichever the kernel enumerated first. Reordering
`BootOrder` alone will not fix that; the kernel will come from the disk you
chose and the rootfs from whichever won the probe race.
