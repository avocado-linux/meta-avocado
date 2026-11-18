#!/bin/sh
# Host test: on Jetson, systemd's TPM setup units are gated on a file that
# optee-ftpm-setup.sh writes once the fTPM store is up. If the script stops
# writing that path, or writes it after it loads tpm_ftpm_tee, the units stop
# running on opt-in runtimes and nothing else notices. Text-level: a host test
# cannot build the packages.
set -u
here=$(cd "$(dirname "$0")" && pwd)
top=$(cd "$here/../../../.." && pwd)
masks=$top/meta-avocado-nvidia/recipes-core/systemd/systemd-jetson-masks_1.0.bb
init=$top/meta-avocado-nvidia/recipes-core/avocado-tegra-init/avocado-tegra-init.bb
setup=$top/meta-avocado/recipes-security/optee-ftpm-init/files/optee-ftpm-setup.sh
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

# Read each recipe's own gate. Collapsing both with sort -u would still show
# one /run path after either recipe lost its ConditionPathExists=.
masks_gate=$(sed -n 's/^ConditionPathExists=//p' "$masks")
init_gate=$(sed -n 's/^ConditionPathExists=//p' "$init")
gate=$masks_gate
for pair in "systemd-jetson-masks_1.0.bb:$masks_gate" "avocado-tegra-init.bb:$init_gate"; do
  case ${pair#*:} in
    /run/*) ok "${pair%%:*} gates on ${pair#*:}" ;;
    *) bad "${pair%%:*} has no /run gate" ;;
  esac
done
if [ -n "$masks_gate" ] && [ "$masks_gate" = "$init_gate" ]; then
  ok "both recipes gate on the same file: $gate"
else
  bad "the recipes gate on different files: masks='$masks_gate' init='$init_gate'"
  [ -n "$gate" ] || gate=/nonexistent/gate
fi

# First non-comment line that redirects into the gate file, and the driver load.
w=$(grep -nF "$gate" "$setup" | grep -vE '^[0-9]+:[[:space:]]*#' \
  | grep -E '>[[:space:]]*/run/' | head -n 1 | cut -d: -f1)
m=$(grep -nE '^[[:space:]]*modprobe tpm_ftpm_tee' "$setup" | head -n 1 | cut -d: -f1)
if [ -n "$w" ]; then
  ok "optee-ftpm-setup.sh writes the gate file (line $w)"
else
  bad "optee-ftpm-setup.sh never writes $gate"
fi
if [ -n "$w" ] && [ -n "$m" ] && [ "$w" -lt "$m" ]; then
  ok "the gate file is written before tpm_ftpm_tee loads"
else
  bad "the gate file is not written before modprobe tpm_ftpm_tee (write=$w modprobe=$m)"
fi

for f in "$masks" "$init"; do
  if grep -qE '^TimeoutSec=[0-9]+s$' "$f"; then
    ok "$(basename "$f") bounds the unit"
  else
    bad "$(basename "$f") sets no TimeoutSec"
  fi
done

echo "checks: $((pass + fail)) run, $fail failed"
[ "$fail" -eq 0 ]
