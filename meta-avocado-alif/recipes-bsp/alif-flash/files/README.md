# nativesdk-alif-flash

Wrapper scripts and ATOC JSON templates that drive Alif SETOOLS to program
the DevKit-E8 OSPI flash with TF-A + xipImage + DTB at first-boot.

## What this package ships

- `avocado-alif-flash` (built from `flash-alif.sh`) — entry point invoked by
  `stone-provision-serial.sh`. Resolves the ATOC JSON template against the
  actual artifact paths from the stone bundle, then shells out to the Alif
  flash tool.
- `atoc-alif-e8-devkit.json` — ATOC layout template for the Alif Ensemble
  E8 DevKit OSPI map. Addresses match the defaults from `meta-alif-ensemble`'s
  `conf/machine/devkit-e8.conf` (TF-A at 0x80000000, DTB at 0x80010000,
  xipImage at 0x80020000).

## What this package does NOT ship

The Alif SETOOLS / `app-write-mram` binary itself. SETOOLS is closed-source
and its license precludes redistribution; the user must install it into the
SDK container.

## Installing SETOOLS into the SDK container

1. Obtain SETOOLS from Alif Semiconductor (developer portal, dev kit
   delivery, or per Alif support).
2. Launch the avocado SDK container with USB passthrough:
   ```
   avocado sdk run -E
   ```
3. Inside the container, extract SETOOLS to a stable path and add the
   `app-write-mram` (or equivalent) entry point to `PATH`. The wrapper
   resolves the tool by name; override via
   `AVOCADO_ALIF_FLASH_TOOL=/path/to/binary` if it's named differently in
   your SETOOLS distribution.

## Running

`stone-provision-serial.sh` is invoked by `avocado provision alif-e8-devkit
--profile serial` and calls `avocado-alif-flash`. The host must have USB
passthrough into the SDK container so SETOOLS can talk to the DevKit's
USB CDC interface (or the SWD probe, depending on the SETOOLS variant).
