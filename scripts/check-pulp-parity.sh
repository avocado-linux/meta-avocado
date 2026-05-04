#!/usr/bin/env bash
#
# Local parity check for the inline-Pulp-upload manifests written by
# avocado-pulp-upload.bbclass. Every RPM under a mapped arch_dir must have a
# manifest entry — that catches the original bug where the kernel built live
# without firing the avocado_pulp_postinst hook.
#
# Set-based, not line-count: extra manifest entries (referring to RPMs no
# longer on disk) are reported as a warning, not a failure. Iterating dev
# builds leaves stale `.jsonl` files in tmp/deploy/pulp-uploads/ from earlier
# recipe versions; sstate_clean / cleansstate doesn't touch them, so the line
# count drifts even though the actual coverage is correct. Tekton CI
# always builds in a fresh container so it can use a simple line count, but
# dev needs the smarter comparison.
#
# Run after `kas build ...` (or `bitbake avocado-distro`) for any machine.
# In dev mode (AVOCADO_PULP_UPLOAD unset/0), the bbclass writes dry-run
# entries with the same shape as CI manifests; this check passes/fails
# identically.
#
# Usage:
#   distro/scripts/check-pulp-parity.sh                # auto-detect from cwd
#   distro/scripts/check-pulp-parity.sh <build-dir>    # e.g. build-rubikpi3/build

set -euo pipefail

BUILD_DIR="${1:-${BUILDDIR:-./build}}"

RPM_DIR="${BUILD_DIR}/tmp/deploy/rpm"
MANIFEST_DIR="${BUILD_DIR}/tmp/deploy/pulp-uploads"
MAP_FILE="${RPM_DIR}/avocado-repo.map"

if [ ! -f "${MAP_FILE}" ]; then
    echo "ERROR: no avocado-repo.map at ${MAP_FILE}" >&2
    echo "Run a full build (e.g. \`kas build ... --target avocado-distro\`) first." >&2
    exit 1
fi

if [ ! -d "${MANIFEST_DIR}" ]; then
    echo "ERROR: no manifest dir at ${MANIFEST_DIR}" >&2
    echo "Either the bbclass did not run, or the build failed before do_package_write_rpm." >&2
    exit 1
fi

echo "=== Pulp upload parity check ==="
echo "Build dir:    ${BUILD_DIR}"
echo "Map file:     ${MAP_FILE}"
echo "Manifest dir: ${MANIFEST_DIR}"

exec python3 - "${RPM_DIR}" "${MANIFEST_DIR}" "${MAP_FILE}" <<'PY'
import json, os, sys, glob

rpm_dir, manifest_dir, map_file = sys.argv[1], sys.argv[2], sys.argv[3]

mapped_archs = set()
with open(map_file) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        arch = line.split("=", 1)[0]
        if arch:
            mapped_archs.add(arch)

# (arch_dir, rpm_name) tuples for every RPM physically on disk in a mapped arch_dir.
on_disk = set()
for arch in mapped_archs:
    d = os.path.join(rpm_dir, arch)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if fn.endswith(".rpm"):
            on_disk.add((arch, fn))

# (arch_dir, rpm_name) tuples claimed by any per-recipe manifest.
in_manifests = set()
for jf in sorted(glob.glob(os.path.join(manifest_dir, "*.jsonl"))):
    for line in open(jf):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (e.get("arch_dir", ""), e.get("rpm_name", ""))
        if key[0] and key[1]:
            in_manifests.add(key)

missing = on_disk - in_manifests   # disk has it, no manifest covers it — fail
stale   = in_manifests - on_disk   # manifest mentions it, no longer on disk — warn

print(f"RPMs on disk in mapped arch_dirs: {len(on_disk)}")
print(f"Unique manifest tuples:           {len(in_manifests)}")
print(f"  covered:                        {len(on_disk & in_manifests)}")
print(f"  missing (disk ∩ ¬ manifest):    {len(missing)}")
print(f"  stale   (manifest ∩ ¬ disk):    {len(stale)}")

if stale:
    print()
    print("Warning: manifest entries reference RPMs no longer on disk.")
    print("These are leftovers from earlier dev iterations and are harmless;")
    print("Tekton CI doesn't see them because it always builds fresh.")
    for arch, name in sorted(stale)[:20]:
        print(f"  {arch}/{name}")
    if len(stale) > 20:
        print(f"  ... and {len(stale) - 20} more")

if missing:
    print()
    print("ERROR: RPMs on disk with no manifest entry — bbclass did not fire for these.")
    for arch, name in sorted(missing)[:30]:
        print(f"  {arch}/{name}")
    if len(missing) > 30:
        print(f"  ... and {len(missing) - 30} more")
    sys.exit(1)

print()
print("Parity check passed (every on-disk RPM has a manifest entry)")
PY
