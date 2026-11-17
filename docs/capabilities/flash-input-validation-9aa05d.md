# `flash-input-validation`: the host prerequisites drop `jq` and add `python3` 3.10 or newer, the engine directory becomes a required input, and the manifest-key contract test tracks the engine.

**Delivered by:** avocado-flash-unified-tool
**Modules touched:** other

## Delivery Note

Invocation: avocado-flash nvme --deploy <deploy> --machine avocado-jetson-orin-nano --dry-run, then the same command without --dry-run; avocado provision --runtime dev (stone runs the shim); avocado-flash boards; hardware-free staging with AVOCADO_STONE_MANIFEST=<deploy>/stone-jetson-orin-nano.json AVOCADO_STONE_DATA_DIR=<deploy> AVOCADO_STONE_BUILD_DIR=<scratch> AVOCADO_PROVISION_PROFILE=tegraflash-nvme <deploy>/stone-provision-tegraflash.sh --prepare-only
Precondition: a deploy tree built with the avocado-stone target after this change (tegraflash-engine directory deployed and named by the manifest); python3 3.10 or newer on PATH on the host and in the SDK container; root or sudo except under --prepare-only; fdtget, fdtput, cpp and lsusb on PATH; for a flash, exactly one Jetson in recovery mode (FC_REC to GND on J14, USB-C attached)
Success signal: --prepare-only exits 0 and its output ends with the work directory and ./initrd-flash --erase-nvme; a flash exits 0 and the host door prints the jumper-removal and power-cycle message; after the power cycle findmnt -no SOURCE / on the board names an nvme0n1 partition; avocado-flash boards prints one line per board with the Orin Nano showing 0955:7523
Silent failure: an image tree built before this change keeps the old 694-line script, so none of the new refusals apply and nothing says so; a parity run that passes because the stubs hide a decision the real tools take (the hardware gates are the backstop); a deploy tree whose manifest omits the engine entry fails loudly, but a hand-copied older manifest next to a new script looks fine until the shim reports the missing engine directory
