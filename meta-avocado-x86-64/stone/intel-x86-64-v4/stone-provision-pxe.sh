#!/usr/bin/env bash

# PXE Provisioning Script for Intel x86-64
#
# Installs Avocado OS on a target over the network. Serves the target from
# inside the provision container until its installer reports back:
#
#   UEFI PXE -> proxyDHCP + TFTP (dnsmasq) -> iPXE -> boot.ipxe (HTTP)
#   -> installer kernel + initrd -> streams the disk image to the target disk
#   -> GET /done -> this script stops serving and exits.
#
# Your DHCP server keeps handing out addresses: dnsmasq answers as a proxy
# with only the boot information, and only to the target's MAC. The HTTP
# server binds to the serving address and answers only a client whose ARP
# entry carries that MAC, so another host on the LAN can neither fetch the
# image nor end the run with a forged report. The installer must therefore
# use the NIC that PXE booted. The container
# needs the host's network (container_args: --network=host, and NET_ADMIN +
# NET_RAW or --privileged), so it works on a Linux host, not Docker Desktop.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory
#
# Set with `avocado provision --env NAME=value`:
# AVOCADO_PROVISION_PXE_MAC     - (required) the target's PXE NIC MAC
# AVOCADO_PROVISION_DEVICE      - target disk, e.g. /dev/nvme0n1 (default:
#                                 the installer picks the only internal disk)
# AVOCADO_PROVISION_PXE_IFACE   - interface to serve on (default: the one
#                                 holding the default route)
# AVOCADO_PROVISION_PXE_ADDR    - address the target fetches from (default:
#                                 the interface's IPv4 address)
# AVOCADO_PROVISION_PXE_PORT    - HTTP port (default 8470)
# AVOCADO_PROVISION_PXE_TIMEOUT - seconds to wait for the installer (default 1800)
# AVOCADO_PROVISION_PXE_PAYLOAD - directory with snponly.efi, vmlinuz, initrd
#                                 and an optional `cmdline` file (default:
#                                 ${AVOCADO_STONE_DATA_DIR}/pxe)

set -euo pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

MAC="${AVOCADO_PROVISION_PXE_MAC:-}"
DISK="${AVOCADO_PROVISION_DEVICE:-}"
PORT="${AVOCADO_PROVISION_PXE_PORT:-8470}"
TIMEOUT="${AVOCADO_PROVISION_PXE_TIMEOUT:-1800}"
PAYLOAD="${AVOCADO_PROVISION_PXE_PAYLOAD:-${DATA_DIR}/pxe}"

if [ -z "$MAC" ]; then
    echo "ERROR: set AVOCADO_PROVISION_PXE_MAC to the target's PXE NIC MAC"
    echo "  (avocado provision ... --profile pxe --env AVOCADO_PROVISION_PXE_MAC=aa:bb:cc:dd:ee:ff)"
    exit 1
fi
MAC=$(echo "$MAC" | tr 'A-F-' 'a-f:')

IFACE="${AVOCADO_PROVISION_PXE_IFACE:-$(ip -4 route show default | awk '{print $5; exit}')}"
ADDR="${AVOCADO_PROVISION_PXE_ADDR:-$(ip -4 -o addr show dev "$IFACE" | awk '{split($4, a, "/"); print a[1]; exit}')}"
CIDR=$(ip -4 -o addr show dev "$IFACE" | awk '{print $4; exit}')
if [ -z "$IFACE" ] || [ -z "$ADDR" ] || [ -z "$CIDR" ]; then
    echo "ERROR: no IPv4 interface to serve on (is the container on the host network?)"
    echo "  Set AVOCADO_PROVISION_PXE_IFACE and AVOCADO_PROVISION_PXE_ADDR."
    exit 1
fi
SUBNET=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network.network_address)" "$CIDR")

for f in snponly.efi vmlinuz initrd; do
    if [ ! -f "${PAYLOAD}/${f}" ]; then
        echo "ERROR: PXE payload file missing: ${PAYLOAD}/${f}"
        exit 1
    fi
done

echo "=== PXE provisioning for ${PLATFORM} ==="
echo "  Target MAC: ${MAC}"
echo "  Serving on: ${IFACE} ${ADDR} (proxyDHCP for ${SUBNET}, HTTP :${PORT})"
echo "  Target disk: ${DISK:-auto (the only internal disk)}"

# =============================================================================
# The disk image the installer writes
# =============================================================================
IMAGE_NAME="avocado-os-${PLATFORM}.img"
IMAGE_FILE="${BUILD_DIR}/${IMAGE_NAME}"
if [ ! -f "$IMAGE_FILE" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    bash "${SCRIPT_DIR}/stone-provision-img.sh"
fi
if [ ! -f "$IMAGE_FILE" ]; then
    echo "ERROR: disk image not found: ${IMAGE_FILE}"
    exit 1
fi

# =============================================================================
# Serving tree: TFTP (iPXE) and HTTP (boot script, installer, image)
# =============================================================================
SERVE="${BUILD_DIR}/pxe"
rm -rf "$SERVE"
mkdir -p "${SERVE}/tftp" "${SERVE}/http"
cp "${PAYLOAD}/snponly.efi" "${SERVE}/tftp/"
for f in "${PAYLOAD}"/*; do
    case "$(basename "$f")" in
        snponly.efi | cmdline) ;;
        *) ln -sf "$f" "${SERVE}/http/" ;;
    esac
done
ln -sf "$IMAGE_FILE" "${SERVE}/http/disk.img"

BASE="http://${ADDR}:${PORT}"
EXTRA=""
if [ -f "${PAYLOAD}/cmdline" ]; then
    EXTRA=$(sed "s|@BASE@|${BASE}|g" "${PAYLOAD}/cmdline" | tr '\n' ' ')
fi
cat > "${SERVE}/tftp/boot.ipxe" <<IPXE
#!ipxe
echo Avocado OS PXE install from ${ADDR}
kernel ${BASE}/vmlinuz initrd=initrd ${EXTRA} avocado.install.url=${BASE} ${DISK:+avocado.install.disk=${DISK}}
initrd ${BASE}/initrd
boot
IPXE

cat > "${SERVE}/dnsmasq.conf" <<DNSMASQ
port=0
interface=${IFACE}
bind-interfaces
dhcp-range=${SUBNET},proxy
dhcp-host=${MAC},set:target
dhcp-ignore=tag:!target
dhcp-userclass=set:ipxe,iPXE
pxe-service=tag:target,tag:!ipxe,X86-64_EFI,"iPXE",snponly.efi
pxe-service=tag:target,tag:ipxe,X86-64_EFI,"Avocado install",boot.ipxe
enable-tftp
tftp-root=${SERVE}/tftp
dhcp-leasefile=${SERVE}/dnsmasq.leases
log-dhcp
DNSMASQ

# The installer reports with GET /done?status=ok|fail&disk=...&msg=...
cat > "${SERVE}/server.py" <<'PY'
import http.server, os, sys, urllib.parse
root, addr, port, done, mac = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
arp = os.environ.get("PXE_ARP_TABLE", "/proc/net/arp")

def is_target(ip):
    # The client reached us on the LAN, so the host has its ARP entry.
    with open(arp) as f:
        for line in f:
            col = line.split()
            if len(col) > 3 and col[0] == ip and col[3].lower() == mac:
                return True
    return False

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=root, **k)

    # Gate every method here, not in do_GET: HEAD and the rest would
    # otherwise answer any host.
    def parse_request(self):
        if not super().parse_request():
            return False
        if not is_target(self.client_address[0]):
            self.send_error(403)
            return False
        return True

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/done":
            q = urllib.parse.parse_qs(url.query)
            with open(done + ".tmp", "w") as f:
                for k in ("status", "disk", "msg"):
                    f.write("%s=%s\n" % (k, q.get(k, [""])[0]))
            os.rename(done + ".tmp", done)
            self.send_response(200)
            self.end_headers()
            return
        super().do_GET()

http.server.ThreadingHTTPServer((addr, port), Handler).serve_forever()
PY

DONE="${SERVE}/done"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap cleanup EXIT

dnsmasq -k -C "${SERVE}/dnsmasq.conf" --log-facility=- &
PIDS+=($!)
python3 "${SERVE}/server.py" "${SERVE}/http" "$ADDR" "$PORT" "$DONE" "$MAC" 2>"${SERVE}/http.log" &
PIDS+=($!)
sleep 1
for p in "${PIDS[@]}"; do
    if ! kill -0 "$p" 2>/dev/null; then
        echo "ERROR: PXE server failed to start (port ${PORT} or 67/69 in use, or no NET_ADMIN?)"
        exit 1
    fi
done

echo ""
echo "Serving. Power on or reboot the target now; it must PXE boot over IPv4 UEFI."
echo "Waiting up to ${TIMEOUT} s for the installer to report back..."
waited=0
while [ ! -f "$DONE" ]; do
    if [ "$waited" -ge "$TIMEOUT" ]; then
        echo "ERROR: no report from the installer after ${TIMEOUT} s"
        echo "  Last requests:"
        tail -n 5 "${SERVE}/http.log" | sed 's/^/    /'
        exit 1
    fi
    sleep 5
    waited=$((waited + 5))
done

status=$(sed -n 's/^status=//p' "$DONE")
disk=$(sed -n 's/^disk=//p' "$DONE")
msg=$(sed -n 's/^msg=//p' "$DONE")
echo "Installer reported: status=${status} disk=${disk} ${msg}"
if [ "$status" != "ok" ]; then
    exit 1
fi
echo "=== Avocado OS installed on ${disk}; the target reboots from it ==="
