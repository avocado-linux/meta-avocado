#!/usr/bin/env bash
# Host test for nvpmodel_conf_for() in nvpmodel-select.sh: every P3767 module
# DTB must map to the conf NVIDIA's nvpower.sh links for it, so an 8GB Orin NX
# stops getting the 16GB power model and a non-super DTB gets a non-super
# table. The inputs are the root compatibles of the L4T 39.2 DTBs, joined the
# way the script reads /proc/device-tree/compatible (NULs dropped).

# ok and bad only echo and increment, so `cond && ok || bad` cannot run both.
# shellcheck disable=SC2015
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../tegra-nvpmodel-base/nvpmodel-select.sh
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

eval "$(awk '/^nvpmodel_conf_for\(\) \{/,/^\}/' "$script")"
if ! declare -f nvpmodel_conf_for >/dev/null; then
  echo "FAIL - could not extract nvpmodel_conf_for from $script"
  exit 1
fi

check() {
  local got
  got=$(nvpmodel_conf_for "$1")
  [ "$got" = "$2" ] && ok "'$1' -> '$2'" || bad "'$1' -> '$got', want '$2'"
}

check 'nvidia,p3768-0000+p3767-0000-supernvidia,p3767-0000nvidia,tegra234' nvpmodel_p3767_0000_super
check 'nvidia,p3768-0000+p3767-0000nvidia,p3767-0000nvidia,tegra234' nvpmodel_p3767_0000
check 'nvidia,p3768-0000+p3767-0001-supernvidia,p3767-0001nvidia,tegra234' nvpmodel_p3767_0001_super
check 'nvidia,p3768-0000+p3767-0001nvidia,p3767-0001nvidia,tegra234' nvpmodel_p3767_0001
check 'nvidia,p3768-0000+p3767-0003-supernvidia,p3767-0003nvidia,tegra234' nvpmodel_p3767_0003_super
check 'nvidia,p3768-0000+p3767-0003nvidia,p3767-0003nvidia,tegra234' nvpmodel_p3767_0003
check 'nvidia,p3768-0000+p3767-0004-supernvidia,p3767-0004nvidia,tegra234' nvpmodel_p3767_0004_super
check 'nvidia,p3768-0000+p3767-0004nvidia,p3767-0004nvidia,tegra234' nvpmodel_p3767_0004
check 'nvidia,p3768-0000+p3767-0005-supernvidia,p3767-0005nvidia,tegra234' nvpmodel_p3767_0003_super
check 'nvidia,p3768-0000+p3767-0005nvidia,p3767-0005nvidia,tegra234' nvpmodel_p3767_0003
# Not a P3767 board, or no compatible read: no pick, so the script keeps the
# machine default.
check 'nvidia,p3737-0000+p3701-0000nvidia,p3701-0000nvidia,tegra234' ''
check '' ''

echo "checks: $((pass + fail)) run, $pass passed, $fail failed"
[ "$fail" -eq 0 ]
