# Intel x86-64 boards

How to pick an Intel target and prepare a board's firmware for Avocado OS.

## Which target

The three machines differ only in the instruction set the packages are built
for. Pick the highest level the CPU runs; a package built above it dies with
SIGILL.

| Machine | Needs | Typical CPUs |
|---|---|---|
| `intel-x86-64-v2` | SSE4.2, POPCNT | Atom, Celeron/Pentium J and N (N5105, N100, N200), Jasper/Elkhart Lake, Alder Lake-N |
| `intel-x86-64-v3` | AVX2, BMI2, FMA | Core from Haswell on, including Raptor Lake |
| `intel-x86-64-v4` | AVX-512 | Xeon, some Core (Ice/Tiger Lake mobile) |

Check on a running Linux: `grep -o -w -E 'avx2|avx512bw' /proc/cpuinfo | sort -u`.
No `avx2` means v2.

## Firmware (BIOS) settings

- **UEFI only.** Turn CSM/legacy boot off.
- **Boot order:** the internal disk first, network (PXE IPv4) second. A disk
  that will not boot then falls back to PXE instead of stopping. Avocado adds
  its own `boot-a`/`boot-b` entries on first boot and puts them first.
- **PXE:** turn on the network stack and IPv4 PXE, and turn Fast Boot off.
  The PXE entry only appears after a save and reboot.
- **TPM:** turn on Intel PTT (firmware TPM), or fit a discrete TPM. Needed
  for `var.encrypt` with `hardware: tpm2`.
- **Serial console:** turn on console redirection on the COM port at 115200 to
  see the firmware and the systemd-boot menu on serial. Avocado's kernel
  console is `ttyS0,115200n8`, last, so the serial port is `/dev/console`.
- **Restore on AC power loss: Power On**, for boards driven by a power relay.
- **RTC:** fit the coin cell, or the clock resets at every power cut.

## Boot

systemd-boot loads a Boot Loader Specification entry
(`loader/entries/avocado.conf`) on each of the two ESPs. The CPU microcode
(`intel-ucode.cpio`) is passed as the first initrd, so it is applied early.
Project kernel arguments come from `kernel.cmdline` and
`kernel.cmdline_extra` in avocado.yaml: the build hook rewrites the entry's
`options` line, and an OS update carries the new line to the other slot.

## Encrypted /var

`var.encrypt: true` with `hardware: tpm2` works on PTT and discrete TPMs. The
first boot encrypts `/var` in place and seals a key to PCR 7; later boots
unlock through the TPM. The recovery key is derived from the serial of the
disk holding `/var` (eMMC CID, NVMe or SCSI serial) and the DMI product UUID
when it is real. Many AMI boards ship the same placeholder UUID
(`03000200-0400-0500-0006-000700080009`) on every unit, so the UUID alone is
never used.

## Board extensions

Board support (NIC, Wi-Fi and Bluetooth firmware, audio codecs, platform
drivers) goes in a `bsp-<board>` extension. Since kernel 6.17 each HD Audio
codec is its own module (`kernel-module-snd-hda-codec-alc269`,
`-intelhdmi`, ...); without them `snd_hda_intel` binds and creates no card.
On Atom and Celeron boards the header I2C, SPI and UART controllers are LPSS
PCI functions that create platform devices: list `intel-lpss-pci`,
`i2c-designware-platform`, `spi-pxa2xx-platform`, `8250-dw` and `idma64`.
