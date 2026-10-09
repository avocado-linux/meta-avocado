#!/usr/bin/env bash
# shellcheck disable=SC2015,SC2016 # `check && ok || bad`: ok only echoes and counts; the single-quoted greps match literal ${...} on purpose
# Host test with a fake /sys: the fTPM store is resolved on the boot disk only,
# never from another disk that carries the same partition label.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/optee-ftpm-setup.sh
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
part(){ mkdir -p "$w/sys/block/$1/$2"; printf 'DEVNAME=%s\nPARTNAME=%s\n' "$2" "$3" > "$w/sys/block/$1/$2/uevent"; }
part mmcblk0 mmcblk0p1 APP; part mmcblk0 mmcblk0p15 reserved
part nvme0n1 nvme0n1p1 APP; part nvme0n1 nvme0n1p15 reserved; part nvme0n1 nvme0n1p14 reserved_b
part sda sda1 data
res(){ OPTEE_FTPM_SETUP_LIB=1 AVOCADO_SYSFS="$w/sys" bash -c '. "$1"; store_on_disk "$2" "$3"' _ "$script" "$1" "$2"; }

[ "$(res mmcblk0 /dev/disk/by-partlabel/reserved)" = /dev/mmcblk0p15 ] && ok "eMMC boot takes the eMMC store" || bad "emmc: $(res mmcblk0 /dev/disk/by-partlabel/reserved)"
[ "$(res nvme0n1 /dev/disk/by-partlabel/reserved)" = /dev/nvme0n1p15 ] && ok "NVMe boot takes the NVMe store, not reserved_b" || bad "nvme: $(res nvme0n1 /dev/disk/by-partlabel/reserved)"
[ -z "$(res sda /dev/disk/by-partlabel/reserved)" ] && ok "a boot disk without the label resolves to nothing, not another disk" || bad "sda: $(res sda /dev/disk/by-partlabel/reserved)"
[ -z "$(res nvme1n1 /dev/disk/by-partlabel/reserved)" ] && ok "an unknown disk resolves to nothing" || bad "unknown"

# The store is btrfs. A mount without -t probes every filesystem on a blank
# partition, and the 6.18 erofs probe double-frees in put_fs_context (oops).
untyped=$(grep -nE '(^|[^a-z])mount +"\$TEE_DEV"' "$script")
[ -z "$untyped" ] && ok "the store is mounted with its type, never probed" || bad "untyped mount: $untyped"

# The supplicant must outlive the switch to the real root. At that switch systemd (pid 1) sends SIGTERM to every process
# still alive in the initrd, except one whose argv[0] starts with '@'; and it stops the unit that started the daemon, which
# kills what is left in that unit's cgroup. So it is started from a oneshot unit with an '@' argv[0] (its main process, the
# `-d` parent, exits at once) and the daemon is moved out of the unit's cgroup.
unit=$here/../files/tee-supplicant-initrd.service
[ -f "$unit" ] && grep -qx 'Type=oneshot' "$unit" && grep -qx 'RemainAfterExit=yes' "$unit" \
    && ok "the initrd supplicant unit is a oneshot that stays active" || bad "supplicant unit missing or not a oneshot"
[ -f "$unit" ] && grep -qx 'ExecStart=@/usr/sbin/tee-supplicant @tee-supplicant -d' "$unit" \
    && ok "the unit starts the daemon with argv[0] '@tee-supplicant'" || bad "supplicant unit lacks the '@' argv[0] ExecStart"

# Static checks look at code lines only: a comment must not satisfy them.
code=$(grep -vE '^[[:space:]]*#' "$script")
first_mode=$(printf '%s\n' "$code" | grep -n 'supplicant_mode /sysroot' | head -1 | cut -d: -f1)
first_start=$(printf '%s\n' "$code" | grep -n 'moved=$(start_supplicant)' | head -1 | cut -d: -f1)
first_modprobe=$(printf '%s\n' "$code" | grep -n 'modprobe tpm_ftpm_tee' | head -1 | cut -d: -f1)
[ -n "$first_mode" ] && [ -n "$first_start" ] && [ -n "$first_modprobe" ] \
    && [ "$first_mode" -lt "$first_start" ] && [ "$first_start" -lt "$first_modprobe" ] \
    && ok "the main flow picks the mode, starts the supplicant, then loads the fTPM driver" \
    || bad "mode line '$first_mode', start line '$first_start', modprobe line '$first_modprobe'"

# supplicant_mode: keep the daemon alive across the switch only when the real root is visible and ships no supplicant.
mode() { OPTEE_FTPM_SETUP_LIB=1 bash -c '. "$1"; supplicant_mode "$2"' _ "$script" "$1"; }
[ "$(mode "$w/no-root")" = legacy ] && ok "a real root that is not mounted yet keeps the plain daemon" || bad "unmounted root: $(mode "$w/no-root")"
mkdir -p "$w/root-a/usr/lib/systemd/system"
[ "$(mode "$w/root-a")" = survive ] && ok "a visible real root without a supplicant unit gets the surviving daemon" || bad "root-a: $(mode "$w/root-a")"
mkdir -p "$w/root-b/usr/lib/systemd/system"; : > "$w/root-b/usr/lib/systemd/system/tee-supplicant.service"
[ "$(mode "$w/root-b")" = legacy ] && ok "a real root that ships tee-supplicant.service keeps the plain daemon" || bad "root-b: $(mode "$w/root-b")"
mkdir -p "$w/root-c/usr/lib/systemd/system"; : > "$w/root-c/usr/lib/systemd/system/tee-supplicant@.service"
[ "$(mode "$w/root-c")" = legacy ] && ok "a real root that ships the tee-supplicant@.service template keeps the plain daemon" || bad "root-c: $(mode "$w/root-c")"
mkdir -p "$w/root-d/usr/lib/systemd/system" "$w/root-d/etc/systemd/system"; : > "$w/root-d/etc/systemd/system/tee-supplicant.service"
[ "$(mode "$w/root-d")" = legacy ] && ok "a supplicant unit under /etc counts too" || bad "root-d: $(mode "$w/root-d")"

# Behavior of start_supplicant and its parts with a fake /proc, a fake cgroup.procs and a fake systemctl.
mkdir -p "$w/bin"
cat > "$w/bin/systemctl" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_SYSTEMCTL_LOG"
exit "${FAKE_SYSTEMCTL_RC:-0}"
EOF
chmod +x "$w/bin/systemctl"
# run_start <systemctl-rc> <proc> <cgroup.procs>: prints "<rc>|<stdout>"
run_start() {
    out=$(PATH="$w/bin:$PATH" FAKE_SYSTEMCTL_LOG="$w/systemctl.log" FAKE_SYSTEMCTL_RC="$1" OPTEE_FTPM_SETUP_LIB=1 \
        bash -c '. "$1"; start_supplicant "$2" "$3"' _ "$script" "$2" "$3" 2>/dev/null); rc=$?; echo "$rc|$(printf '%s' "$out" | tr '\n' ' ' | sed 's/ $//')"
}
# fakeproc pid:comm[:argv0] ... ; argv0 defaults to "@<comm>" (what the unit's ExecStart gives the daemon)
fakeproc() {
    rm -rf "$w/proc"; mkdir -p "$w/proc"
    for spec in "$@"; do
        IFS=: read -r pid comm argv0 <<EOF
$spec
EOF
        mkdir -p "$w/proc/$pid"; echo "$comm" > "$w/proc/$pid/comm"
        printf '%s\0-d\0' "${argv0:-@$comm}" > "$w/proc/$pid/cmdline"
    done
}

fakeproc 101:tee-supplicant 102:sleep 103:tee-supplicant-x; : > "$w/cgroup.procs"; : > "$w/systemctl.log"
r=$(run_start 0 "$w/proc" "$w/cgroup.procs")
[ "$r" = "0|101" ] && [ "$(cat "$w/cgroup.procs")" = 101 ] && [ "$(cat "$w/systemctl.log")" = "start tee-supplicant-initrd.service" ] \
    && ok "the unit is started, then only the tee-supplicant process is moved to the root cgroup" || bad "start+move: '$r' cgroup='$(cat "$w/cgroup.procs")' log='$(cat "$w/systemctl.log")'"

fakeproc 101:tee-supplicant 1010:tee-supplicant 102:sleep; : > "$w/cgroup.procs"
r=$(run_start 0 "$w/proc" "$w/cgroup.procs")
# Glob order of 101 and 1010 depends on the locale's collation, so compare the sorted list. The function's own list is what
# is asserted: the fake cgroup.procs is a plain file that each write truncates, where the real cgroupfs takes every write.
moved_sorted=$(printf '%s\n' "${r#0|}" | tr ' ' '\n' | sort | tr '\n' ' ')
[ "${r%%|*}" = 0 ] && [ "$moved_sorted" = "101 1010 " ] \
    && ok "every tee-supplicant pid is moved (101 and 1010 are different pids)" || bad "two pids: '$r'"

fakeproc 101:tee-supplicant; : > "$w/cgroup.procs"
r=$(run_start 1 "$w/proc" "$w/cgroup.procs")
[ "$r" = "2|" ] && [ ! -s "$w/cgroup.procs" ] \
    && ok "a failed unit start returns 2 and moves nothing" || bad "systemctl fails: '$r' cgroup='$(cat "$w/cgroup.procs")'"

fakeproc 102:sleep; : > "$w/cgroup.procs"
r=$(run_start 0 "$w/proc" "$w/cgroup.procs")
[ "$r" = "1|" ] && [ ! -s "$w/cgroup.procs" ] \
    && ok "no tee-supplicant process after a successful start returns 1" || bad "none found: '$r'"

fakeproc 101:tee-supplicant:tee-supplicant; : > "$w/cgroup.procs"
r=$(run_start 0 "$w/proc" "$w/cgroup.procs")
[ "$r" = "1|" ] && [ ! -s "$w/cgroup.procs" ] \
    && ok "a supplicant without the '@' argv[0] is not moved (systemd kills it at the switch anyway)" || bad "no-@ supplicant: '$r' cgroup='$(cat "$w/cgroup.procs")'"

fakeproc 101:tee-supplicant; mkdir -p "$w/cgroup-dir"
r=$(run_start 0 "$w/proc" "$w/cgroup-dir")
[ "$r" = "1|" ] && ok "a cgroup path that cannot be written is reported, not counted as moved" || bad "unwritable cgroup: '$r'"

fakeproc 101:tee-supplicant; rm -f "$w/no-such-cgroup.procs"
r=$(run_start 0 "$w/proc" "$w/no-such-cgroup.procs")
[ "$r" = "1|" ] && [ ! -e "$w/no-such-cgroup.procs" ] \
    && ok "a missing cgroup.procs (cgroup v1) is reported and is not created" || bad "missing cgroup.procs: '$r'"

recipe=$here/../optee-ftpm-init.bb
rcode=$(grep -vE '^[[:space:]]*#' "$recipe")
printf '%s\n' "$rcode" | grep -q 'file://tee-supplicant-initrd.service' \
    && printf '%s\n' "$rcode" | grep -q 'install -m 0644 ${UNPACKDIR}/tee-supplicant-initrd.service' \
    && printf '%s\n' "$rcode" | grep -q 'FILES:${PN} += "${systemd_system_unitdir}/tee-supplicant-initrd.service"' \
    && ok "the recipe fetches, installs and packages the supplicant unit" || bad "recipe does not ship tee-supplicant-initrd.service"

echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
