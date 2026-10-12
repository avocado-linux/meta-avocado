#!/usr/bin/env bash
#
# The flash makes the medium it targets the firmware's first boot choice.
#
# The flash resets the UEFI variable store, and on an empty store the firmware
# sorts BootOrder once by DefaultBootPriority from L4TConfiguration.dtbo. The
# stock value puts usb and nvme ahead of sd, so stone-provision-tegraflash.sh
# moves the target class to the front of that list before flashing.
#
# This lifts the real block out of the script and runs it against a dtbo built
# here with the stock L4T value.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

echo "test-default-boot-priority: $PROVISION"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

awk '/^l4t_conf_dtbo=/{f=1} f{print} f&&/^echo "UEFI DefaultBootPriority/{exit}' \
  "$PROVISION" >"$work/priority.sh"
if ! grep -q 'fdtput' "$work/priority.sh" || ! grep -q '^echo "UEFI DefaultBootPriority' "$work/priority.sh"; then
  fail "could not extract the DefaultBootPriority block"
  echo "test-default-boot-priority: FAIL (1)"
  exit 1
fi

NODE=/fragment@0/__overlay__/firmware/uefi/variables/gNVIDIATokenSpaceGuid/DefaultBootPriority

# make_dtbo <file> [priority]: the L4TConfiguration overlay shape; no priority
# leaves the node out.
make_dtbo() {
  local prop=""
  [ -n "${2:-}" ] && prop="DefaultBootPriority { data = \"$2\"; locked; };"
  dtc -q -@ -I dts -O dtb -o "$1" - <<DTS
/dts-v1/;
/plugin/;
/ { fragment@0 { target-path = "/"; __overlay__ { firmware { uefi { variables {
  gNVIDIATokenSpaceGuid { $prop };
}; }; }; }; }; };
DTS
}

# run_block <build_dir> <boot_media>
run_block() {
  # shellcheck disable=SC2034  # read by the sourced block
  # shellcheck source=/dev/null
  (build_dir="$1" boot_media="$2" && . "$work/priority.sh") >"$work/out" 2>&1
}

STOCK="usb,nvme,emmc,sd,ufs"
for case in "nvme nvme,usb,emmc,sd,ufs" "sd sd,usb,nvme,emmc,ufs" \
  "emmc emmc,usb,nvme,sd,ufs" "usb usb,nvme,emmc,sd,ufs"; do
  read -r media want <<<"$case"
  set -- "$media" "$want"
  d="$work/$1"
  mkdir -p "$d"
  make_dtbo "$d/L4TConfiguration.dtbo" "$STOCK"
  if run_block "$d" "$1" && [ "$(fdtget -t s "$d/L4TConfiguration.dtbo" "$NODE" data)" = "$2" ]; then
    pass "$1 flash: DefaultBootPriority is $2"
  else
    fail "$1 flash: got '$(fdtget -t s "$d/L4TConfiguration.dtbo" "$NODE" data 2>&1)' ($(cat "$work/out"))"
  fi
done

# A linked dtbo is replaced by an edited copy; the staged original keeps the
# stock value for the next flash.
d="$work/link"
mkdir -p "$d"
make_dtbo "$work/staged.dtbo" "$STOCK"
ln -s "$work/staged.dtbo" "$d/L4TConfiguration.dtbo"
if run_block "$d" sd && [ ! -L "$d/L4TConfiguration.dtbo" ] &&
  [ "$(fdtget -t s "$work/staged.dtbo" "$NODE" data)" = "$STOCK" ] &&
  [ "$(fdtget -t s "$d/L4TConfiguration.dtbo" "$NODE" data)" = "sd,usb,nvme,emmc,ufs" ]; then
  pass "a linked dtbo is edited as a copy; the staged one stays stock"
else
  fail "linked dtbo: $(cat "$work/out")"
fi

# No DefaultBootPriority to edit: refuse instead of flashing a medium the
# firmware may not pick.
d="$work/missing"
mkdir -p "$d"
make_dtbo "$d/L4TConfiguration.dtbo"
if (run_block "$d" sd); then
  fail "a dtbo without DefaultBootPriority was accepted"
else
  pass "a dtbo without DefaultBootPriority stops the flash"
fi

if [ "$failures" -eq 0 ]; then
  echo "test-default-boot-priority: PASS"
else
  echo "test-default-boot-priority: FAIL ($failures)"
  exit 1
fi
