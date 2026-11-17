#!/bin/sh
# Host test: setup-nv-boot-control writes UEFI variables through OP-TEE once
# the module EEPROM is readable. On an fTPM runtime systemd-tpm2-setup-early
# and systemd-tpm2-setup go through OP-TEE too, and the two overlapping leaves
# the fTPM command waiting forever, after which UEFI runtime calls stall. The
# wait-for-boardspec drop-in therefore has to order setup-nv-boot-control
# before both TPM setup units. Text-level: a host test cannot boot a board.
set -u
here=$(cd "$(dirname "$0")" && pwd)
top=$(cd "$here/../../../.." && pwd)
dropin=${1:-$top/meta-avocado-nvidia/recipes-bsp/tools/setup-nv-boot-control/50-avocado-wait-for-boardspec.conf}
pass=0
fail=0
ok() {
  pass=$((pass + 1))
  echo "ok - $1"
}
bad() {
  fail=$((fail + 1))
  echo "not ok - $1"
}

# Before= lines of the [Unit] section only: the same word in [Service] or in a
# comment orders nothing.
before=$(awk '
  /^\[/ { unit = ($0 == "[Unit]"); next }
  unit && /^Before=/ { sub(/^Before=/, ""); print }
' "$dropin")

for u in systemd-tpm2-setup-early.service systemd-tpm2-setup.service; do
  case " $before " in
    *" $u "*) ok "the drop-in orders the unit before $u" ;;
    *) bad "the drop-in does not order the unit before $u" ;;
  esac
done

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
