# `flash-input-validation`: the build outputs that must exist before a write, how they are located from the machine's manifest template, and how a missing one is reported.

**Delivered by:** avocado-flash-nvme-rcm
**Modules touched:** other

## Delivery Note

Invocation: avocado-flash nvme --deploy <deploy> --machine avocado-jetson-orin-nano --dry-run, then the same command without --dry-run
Precondition: a deploy tree built with the avocado-stone target (manifest template, provisioning script, var image, ESP image, TOS image and host tools present), exactly one Orin Nano in RCM (FC_REC to GND on J14, USB-C attached, lsusb shows 0955:7523), root or sudo, python3 3.10 or newer, fdtget, fdtput, cpp and lsusb on PATH, and free space in the work directory
Success signal: exit 0 with the "remove the jumper and power-cycle" message and the work directory removed; after the power cycle, findmnt -no SOURCE / on the board names an nvme0n1 partition
Silent failure: a flash that exits 0 while the firmware boots another disk, or a recovery jumper left in place so the board re-enters RCM instead of booting
