#!/usr/bin/env bash
# Host test: avocado-tegra-init finds the rootfs by PARTLABEL=APP, and `blkid -l` returns whichever disk
# matches first. With a second disk that carries its own APP partition (a vendor system on an NVMe), the
# initrd can mount that one. An `avocado.root=` pin on the command line must win over the label scan, must
# never fall back to it, and must refuse a PARTLABEL or LABEL, which can match on two disks.
#
# The script's discovery section (from its first line to the `mount` of the root) runs under sh -e with
# /proc/cmdline pointed at a temp file and stub blkid, lsblk and sleep first on PATH.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-tegra-init
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

mkdir -p "$w/bin"
# blkid stub. Two disks both carry PARTLABEL=APP, the vendor NVMe first, as a bare `blkid -l` would find it.
# The eMMC partition is also known by its PARTUUID.
cat > "$w/bin/blkid" << 'STUB'
#!/bin/sh
case "$*" in
  *--probe*) exit 0 ;;
  *"PARTLABEL=APP_b"*) echo "/dev/mmcblk0p2: PARTLABEL=\"APP_b\""; exit 0 ;;
  *"-t PARTLABEL=APP"*"-l"*|*"-l -t PARTLABEL=APP"*) echo "/dev/nvme0n1p1: PARTLABEL=\"APP\""; exit 0 ;;
  *"PARTUUID=1111-abcd"*) echo "/dev/mmcblk0p1: PARTUUID=\"1111-abcd\""; exit 0 ;;
esac
exit 2
STUB
# hexdump stub for the BootChainOsCurrent EFI variable: prints $HEXOUT (like " 7 1", attributes then slot) when
# the test sets it, and fails without output, as hexdump does on a missing file, when it does not.
# shellcheck disable=SC2016 # the stub's own variables, expanded when the stub runs
printf '#!/bin/sh\n[ -n "${HEXOUT:-}" ] || exit 1\ncat "$HEXOUT"\n' > "$w/bin/hexdump"
printf '#!/bin/sh\necho /dev/mmcblk0\necho /dev/nvme0n1\n' > "$w/bin/lsblk"
printf '#!/bin/sh\nexit 0\n' > "$w/bin/sleep"
chmod +x "$w/bin/"*

# The discovery section: everything before the line that mounts the root device.
section=$(awk '/^mount "\$rootdev" \/sysroot/{exit} {print}' "$script")
if [ -n "$section" ]; then ok "found the discovery section"; else bad "section not found in $script"; echo "$pass passed, $fail failed"; exit 1; fi
# If the mount line moved, the awk above would capture the whole script and run it, mount included.
# shellcheck disable=SC2016 # the pattern is the script's literal text, not an expansion
case "$section" in *'mount "$rootdev"'*) bad "the section reaches the root mount; fix the marker"; echo "$pass passed, $fail failed"; exit 1 ;; *) ok "the section stops before the root mount" ;; esac

# run <cmdline> [<hexdump output>] -> prints "rc=<n>" and, on success, "rootdev=<dev>"
run() {
    printf '%s\n' "$1" > "$w/cmdline"
    rm -f "$w/hexout"
    [ -z "${2:-}" ] || printf '%s\n' "$2" > "$w/hexout"
    # shellcheck disable=SC2016 # the echo is a literal line for the generated script
    { printf '%s\n' "$section" | sed "s|/proc/cmdline|$w/cmdline|g"; echo 'echo "rootdev=$rootdev"'; } > "$w/section.sh"
    PATH="$w/bin:$PATH" HEXOUT="$([ -f "$w/hexout" ] && echo "$w/hexout")" sh -e "$w/section.sh" 2>&1
    echo "rc=$?"
}

out=$(run "console=ttyTCU0 rootwait")
case "$out" in *"rootdev=/dev/nvme0n1p1"*) ok "without a pin the label scan is unchanged (the first APP wins)" ;; *) bad "no-pin result changed: $out" ;; esac

# Slot selection, which the discovery section must keep doing exactly as before.
out=$(run "console=ttyTCU0 boot.slot_suffix=_b")
case "$out" in *"rootdev=/dev/mmcblk0p2"*) ok "boot.slot_suffix=_b scans for APP_b" ;; *) bad "slot suffix ignored: $out" ;; esac
out=$(run "console=ttyTCU0" " 7 1")
case "$out" in *"rootdev=/dev/mmcblk0p2"*) ok "BootChainOsCurrent slot 1 (attributes 7) scans for APP_b" ;; *) bad "BootChain slot 1 ignored: $out" ;; esac
out=$(run "console=ttyTCU0" " 6 0")
case "$out" in *"rootdev=/dev/nvme0n1p1"*) ok "BootChainOsCurrent slot 0 (attributes 6) scans for APP" ;; *) bad "BootChain slot 0 changed: $out" ;; esac
out=$(run "console=ttyTCU0" " 3 1")
case "$out" in *"rootdev=/dev/nvme0n1p1"*) ok "BootChainOsCurrent with other attributes is ignored" ;; *) bad "BootChain attributes 3 honoured: $out" ;; esac

out=$(run "console=ttyTCU0 avocado.root=PARTUUID=1111-abcd")
case "$out" in *"rootdev=/dev/mmcblk0p1"*) ok "a PARTUUID pin selects its partition although another disk has APP" ;; *) bad "pin ignored: $out" ;; esac

# blkid reports a PARTUUID in lower case and compares it exactly; a profile that spells the GUID in upper case
# (as sfdisk scripts often do) must still find its root, not stop every boot in the initrd.
out=$(run "console=ttyTCU0 avocado.root=PARTUUID=1111-ABCD")
case "$out" in *"rootdev=/dev/mmcblk0p1"*) ok "an upper-case PARTUUID pin is matched in lower case" ;; *) bad "upper-case pin not found: $out" ;; esac

out=$(run "console=ttyTCU0 avocado.root=PARTUUID=9999-NONE")
case "$out" in *"rc=0"*) bad "an unresolvable pin did not stop the initrd: $out" ;; *) ok "an unresolvable pin stops the initrd" ;; esac
case "$out" in *"rootdev=/dev/nvme0n1p1"*) bad "an unresolvable pin fell back to the label scan: $out" ;; *) ok "an unresolvable pin never falls back to the label scan" ;; esac
case "$out" in *"avocado.root=PARTUUID=9999-NONE"*) ok "the failure names the pin" ;; *) bad "failure does not name the pin: $out" ;; esac

out=$(run "console=ttyTCU0 avocado.root=PARTLABEL=APP")
case "$out" in *"rc=0"*) bad "a PARTLABEL pin was accepted: $out" ;; *) ok "a PARTLABEL pin is refused (it can match on two disks)" ;; esac

out=$(run "console=ttyTCU0 avocado.root=LABEL=rootfs")
case "$out" in *"rc=0"*) bad "a LABEL pin was accepted: $out" ;; *) ok "a LABEL pin is refused" ;; esac

echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
