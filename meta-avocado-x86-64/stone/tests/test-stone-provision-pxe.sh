#!/usr/bin/env bash
# Host test for stone-provision-pxe.sh: it serves the target only to its MAC,
# points iPXE at the installer and the disk image, and exits with the
# installer's report (ok -> 0, fail -> 1, no report -> 1 at the timeout).
# dnsmasq and ip are stubbed; the HTTP server and the /done handshake are real.
# The server answers only a client whose ARP entry carries the target MAC; the
# test points it at a fake ARP table for 127.0.0.1.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts
set -u
here=$(cd "$(dirname "$0")" && pwd)
w=$(mktemp -d)
pids=()
cleanup() {
  local p
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
  rm -rf "$w"
}
trap cleanup EXIT
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

for t in jq python3; do
  command -v "$t" >/dev/null || {
    echo "$t not installed"
    exit 2
  }
done

# The three machines carry one script; a drifted copy is a bug.
v3="$here/../intel-x86-64-v3/stone-provision-pxe.sh"
for v in v2 v4; do
  cmp -s "$v3" "$here/../intel-x86-64-$v/stone-provision-pxe.sh" \
    && ok "intel-x86-64-$v copy matches v3" \
    || bad "intel-x86-64-$v/stone-provision-pxe.sh differs from v3"
done

mkdir -p "$w/bin" "$w/payload" "$w/build" "$w/data"
cat >"$w/bin/dnsmasq" <<'EOF'
#!/bin/sh
exec sleep 600
EOF
cat >"$w/bin/ip" <<'EOF'
#!/bin/sh
case "$*" in
  *"route show default"*) echo "default via 192.0.2.1 dev eth9 proto dhcp" ;;
  *"addr show dev eth9"*) echo "2: eth9    inet 192.0.2.10/24 brd 192.0.2.255 scope global eth9" ;;
esac
EOF
chmod +x "$w/bin/dnsmasq" "$w/bin/ip"
for f in snponly.efi vmlinuz initrd; do echo "$f" >"$w/payload/$f"; done
echo 'apkovl=@BASE@/installer.apkovl.tar.gz' >"$w/payload/cmdline"
echo '{"runtime": {"platform": "intel-x86-64-v3"}}' >"$w/manifest.json"
echo disk-image-bytes >"$w/build/avocado-os-intel-x86-64-v3.img"
# arp <mac>: the ARP table the server reads, with 127.0.0.1 at <mac>.
arp() { printf 'IP address HW type Flags HW address Mask Device\n127.0.0.1 0x1 0x2 %s * lo\n' "$1" >"$w/arp"; }
arp 78:d0:04:38:3b:25

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1])'; }
get() { python3 -c 'import sys, urllib.request; sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode())' "$1" 2>/dev/null; }

# start <log> [env...]: run the script in the background on a free port.
start() {
  local log=$1
  shift
  port=$(free_port)
  env PATH="$w/bin:$PATH" AVOCADO_STONE_MANIFEST="$w/manifest.json" \
    AVOCADO_STONE_BUILD_DIR="$w/build" AVOCADO_STONE_DATA_DIR="$w/data" \
    AVOCADO_PROVISION_PXE_PAYLOAD="$w/payload" AVOCADO_PROVISION_PXE_PORT="$port" \
    AVOCADO_PROVISION_PXE_ADDR=127.0.0.1 PXE_ARP_TABLE="$w/arp" "$@" bash "$v3" >"$log" 2>&1 &
  pid=$!
  pids+=("$pid")
  for _ in $(seq 1 50); do
    grep -q '^Serving\.' "$log" && return 0
    kill -0 "$pid" 2>/dev/null || return 1
    sleep 0.2
  done
  return 1
}

# 1. Serving: proxyDHCP for the MAC only, iPXE script, image over HTTP; ok -> 0.
if start "$w/ok.log" AVOCADO_PROVISION_PXE_MAC=78-D0-04-38-3B-25 AVOCADO_PROVISION_DEVICE=/dev/nvme0n1; then
  conf="$w/build/pxe/dnsmasq.conf"
  grep -qx 'dhcp-host=78:d0:04:38:3b:25,set:target' "$conf" && grep -qx 'dhcp-ignore=tag:!target' "$conf" \
    && grep -qx 'dhcp-range=192.0.2.0,proxy' "$conf" \
    && ok "proxyDHCP answers only the normalised MAC on the default-route subnet" \
    || bad "dnsmasq.conf: $(tr '\n' ' ' <"$conf")"
  ipxe="$w/build/pxe/tftp/boot.ipxe"
  grep -q "avocado.install.url=http://127.0.0.1:$port " "$ipxe" && grep -q 'avocado.install.disk=/dev/nvme0n1' "$ipxe" \
    && grep -q "apkovl=http://127.0.0.1:$port/installer.apkovl.tar.gz" "$ipxe" \
    && ok "boot.ipxe carries the install URL, the disk and the payload cmdline" \
    || bad "boot.ipxe: $(tr '\n' ' ' <"$ipxe")"
  [ "$(get "http://127.0.0.1:$port/disk.img")" = disk-image-bytes ] && [ "$(get "http://127.0.0.1:$port/vmlinuz")" = vmlinuz ] \
    && ok "HTTP serves the disk image and the installer kernel" \
    || bad "HTTP did not serve disk.img and vmlinuz"
  get "http://127.0.0.1:$port/done?status=ok&disk=/dev/nvme0n1&msg=written" >/dev/null
  wait "$pid"
  rc=$?
  [ "$rc" = 0 ] && grep -q 'Installer reported: status=ok disk=/dev/nvme0n1' "$w/ok.log" \
    && ok "an ok report ends the run with 0" \
    || bad "ok report: exit $rc, $(tail -n 2 "$w/ok.log")"
else
  bad "the script never started serving: $(tail -n 3 "$w/ok.log")"
fi

# 2. A fail report fails the run.
if start "$w/fail.log" AVOCADO_PROVISION_PXE_MAC=78:d0:04:38:3b:25; then
  grep -q 'avocado.install.disk' "$w/build/pxe/tftp/boot.ipxe" \
    && bad "boot.ipxe names a disk when none was set" \
    || ok "no AVOCADO_PROVISION_DEVICE leaves the disk to the installer"
  get "http://127.0.0.1:$port/done?status=fail&disk=&msg=two%20disks" >/dev/null
  wait "$pid"
  rc=$?
  [ "$rc" = 1 ] && ok "a fail report ends the run with 1" || bad "fail report: exit $rc"
else
  bad "the script never started serving: $(tail -n 3 "$w/fail.log")"
fi

# 3. Another host on the LAN is refused: no image, and its report is ignored.
arp 02:00:00:00:00:99
if start "$w/foreign.log" AVOCADO_PROVISION_PXE_MAC=78:d0:04:38:3b:25; then
  [ -z "$(get "http://127.0.0.1:$port/disk.img")" ] \
    && ok "a client without the target MAC cannot fetch the image" \
    || bad "disk.img was served to a client without the target MAC"
  get "http://127.0.0.1:$port/done?status=ok&disk=/dev/sda" >/dev/null
  sleep 6
  kill -0 "$pid" 2>/dev/null && [ ! -f "$w/build/pxe/done" ] \
    && ok "a report from another client does not end the run" \
    || bad "a forged report ended the run: $(tail -n 2 "$w/foreign.log")"
  kill "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
else
  bad "the script never started serving: $(tail -n 3 "$w/foreign.log")"
fi
arp 78:d0:04:38:3b:25

# 4. No report before the timeout fails the run.
if start "$w/timeout.log" AVOCADO_PROVISION_PXE_MAC=78:d0:04:38:3b:25 AVOCADO_PROVISION_PXE_TIMEOUT=1; then
  wait "$pid"
  rc=$?
  [ "$rc" = 1 ] && grep -q 'no report from the installer' "$w/timeout.log" \
    && ok "no report by the timeout ends the run with 1" || bad "timeout: exit $rc"
else
  bad "the script never started serving: $(tail -n 3 "$w/timeout.log")"
fi

# 5. No MAC refuses before serving anything.
env AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_BUILD_DIR="$w/build" \
  AVOCADO_STONE_DATA_DIR="$w/data" PATH="$w/bin:$PATH" bash "$v3" >"$w/nomac.log" 2>&1
rc=$?
[ "$rc" = 1 ] && grep -q 'set AVOCADO_PROVISION_PXE_MAC' "$w/nomac.log" \
  && ok "a missing MAC is refused" || bad "no MAC: exit $rc"

echo "test-stone-provision-pxe: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
