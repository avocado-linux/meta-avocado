#!/usr/bin/env bash
# Run: bash tests/test-rpi-config-include-last.sh
# Machine appends (seeed, fr200) run after the generic one that adds the include
# line; the include must still end up last so a project's boot_config wins.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bbappend="${BBAPPEND:-$here/../rpi-config_git.bbappend}"
eval "$(sed -n '/^append_config_if_missing() {/,/^}/p' "$bbappend")"

work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
CONFIG=$work/config.txt
printf 'arm_64bit=1\n' > "$CONFIG"
append_config_if_missing "include avocado-overlays.txt"
append_config_if_missing "gpio=13=pu"
append_config_if_missing "dtoverlay=i2c3,pins_4_5"
append_config_if_missing "gpio=13=pu"
append_config_if_missing 'dtparam=path=a\nb'

want=$'arm_64bit=1\ngpio=13=pu\ndtoverlay=i2c3,pins_4_5\ndtparam=path=a\\nb\ninclude avocado-overlays.txt'
if [ "$(cat "$CONFIG")" = "$want" ]; then
  echo "ok: include stays last, no duplicates"
else
  echo "FAIL: config.txt is:"; cat "$CONFIG"; exit 1
fi
