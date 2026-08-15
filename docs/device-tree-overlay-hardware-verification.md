# Device-tree overlay hardware verification

How to confirm on real hardware that a declared device-tree overlay reaches the
running kernel, on Raspberry Pi 5 and on Jetson Orin. A build that succeeds
proves nothing here: on both platforms an overlay can be compiled, claimed, and
shipped without ever taking effect, and every stage before the running board
reports success either way. Only `/proc/device-tree` on a booted board settles
it.

Read the recovery section first. Every later step puts a new image on a board,
and on Jetson a bad device tree can leave it unable to boot.

## Recovery, before you touch a board

Know how to get each board back before you change anything on it.

### Jetson Orin: recovery-mode reimage

The Orin cannot be bricked by a bad device tree. The boot ROM always accepts
USB recovery, independently of anything on the storage medium, so a board that
will not boot is always recoverable:

1. Power the board off.
2. Hold the FORCE_RECOVERY button, apply power, then release. On the developer
   kit carrier this is also reachable by shorting J14 pins 9 and 10 during
   power-on - but remove that jumper afterwards, or the board re-enters recovery
   on every reset and never boots.
3. Confirm the host sees it: `lsusb` shows `0955:7523 NVIDIA Corp. APX`.
4. Re-run the same provisioning command used to put the bad image there.

If `lsusb` shows nothing, the host cannot open the device rather than the board
being dead - see the udev prerequisite below.

### Raspberry Pi 5: SD reimage

Power off, remove the card, and rewrite a known-good image to it from the host.
The Pi holds no state that survives this, so a card rewrite is a full reset.

Keep one card with a known-good image that is not the card under test. Being
able to boot a board you believe is broken is what distinguishes a bad overlay
from a bad image.

## Host prerequisites

### Jetson: USB recovery access

A Jetson in Force Recovery enumerates as vendor `0955`, which the stock
`51-android.rules` assigns `GROUP="adbusers" MODE="0660"`. A user outside that
group cannot open the device, and the tooling then blocks on the USB read
emitting nothing at all. Either join `adbusers`, or grant the logged-in user
access by ACL:

```udev
# /etc/udev/rules.d/60-jetson-recovery.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="0955", TAG+="uaccess"
```

`uaccess` is preferable - it applies on device add and needs no group
membership and no re-login.

### Jetson: serial console

The developer kit has no on-board USB-serial bridge. The console needs an
external 3.3V adapter on the J14 button header:

| J14 pin | Signal | Connect to |
|---------|--------|------------|
| 3 | `UART2_RXD` (board input) | adapter TX |
| 4 | `UART2_TXD` (board output) | adapter RX |
| 7 | GND | adapter GND |

J14 is a dual-row 2x6, not a single row of 12: odd pins run along one row and
even pins along the other, so pins 3 and 4 sit opposite each other rather than
side by side. Counting linearly along one row lands six pins away, on the
`FORCE_RECOVERY` pair.

Attach the console with logging, so a boot can be re-read afterwards instead of
living in scrollback:

```bash
tio -b 115200 -t -L --log-directory <dir> --log-strip \
    /dev/serial/by-id/usb-<your-adapter>
```

Run exactly one `tio` against a port. Two processes on the same tty split the
incoming bytes between them, and the result looks like a wiring fault rather
than contention.

The console is the only place a target-side failure appears. The host cannot
recover it: when the target refuses to export its storage, it stops
re-enumerating and never re-exports the device the host reads logs from.

### Raspberry Pi 5: serial console

The Pi's console is on the 40-pin header (GPIO14/15) at 115200, or over the
debug UART connector on later carriers. Same `tio` invocation.

## The paired build

One build proves nothing. A node found under `/proc/device-tree` may have been
in the base device tree all along, in which case an overlay that never applied
looks identical to one that did. Always run both halves:

- **Positive**: the project declares the overlay. The node must be present.
- **Negative**: the same project with the declaration removed, rebuilt and
  reimaged. The node must be absent.

The negative half is the control. A positive result recorded without it is not
evidence.

Use an overlay that adds a node not present in any base tree for either board,
so the two halves cannot be confused. A property with an unmistakable value is
easier to grep for than a node name that might collide.

## Running it

### Build

Build the project twice, once per half, keeping the two output bundles
distinct. The declaration lives under the project's `device_tree_overlays`.

Confirm the build-path markers before going near a board - they are cheaper to
read than a boot:

- the SDK wrapper compiled the `.dtbo`
- the BSP hook delivered and claimed it

An overlay that compiled but was not claimed never reached the image, and
booting a board will only tell you the same thing more slowly.

### Put the image on the board

**Jetson Orin.** Provisioning must run as root: the flow mounts the board's
exported USB storage and does not elevate on its own. Put the board in recovery
as described above, then run the project's provisioning command under
`sudo -E`.

Watch the console through the run. A target-side refusal appears there and
nowhere else.

**Raspberry Pi 5.** Write the image to the card from the host, reinsert, and
power on.

### Read the live device tree

On the booted board:

```bash
# Is the node there at all?
ls /proc/device-tree/<your-node>

# Read a property value (device-tree properties are NUL-terminated)
tr -d '\0' < /proc/device-tree/<your-node>/<property>; echo
```

`/proc/device-tree` is the tree the kernel is actually running, after every
overlay the bootloader applied. That is the point: it reflects what happened,
not what was intended.

Repeat for the negative half and confirm the node is gone.

## Evidence to record

Record both halves for each board, in a form that makes a missing control
obvious:

```text
BOARD: <variant, e.g. Jetson Orin Nano Developer Kit P3767-0005>
POSITIVE: pass|fail   - node present, property value observed
NEGATIVE: pass|fail   - node absent after removing the declaration
```

State the board variant explicitly. Orin variants differ in module and carrier,
and a result that does not name one cannot be attributed later.

Also record, once per platform, whether updating an overlay needs a full
reimage or an ordinary image update. The two platforms differ, and it is the
fact most likely to be asked about after the work lands.

## When the node is absent on the positive half

Work outwards from the board:

1. Did the build claim the overlay? An unclaimed overlay never reached the
   image.
2. Did the image on the board actually change? Compare against the negative
   half - if both boot identically, the new image may not have been applied.
3. On Jetson, is the device tree the board booted the merged one? The overlays
   are merged into the base DTB at build time, so a stale or shadowed DTB
   produces a clean boot with no overlays applied and no error anywhere.
4. Does the overlay target a node that exists in the base tree? An overlay
   whose target is missing is a no-op on some platforms rather than an error.
