#!/usr/bin/env bash

# Stone Platform Provisioning for Peridio
# Platform-specific configuration for stone builds

set -e

# =============================================================================
# Platform-Specific Configuration
# =============================================================================

# Get the avocado-os artifact path from the stone manifest
# This is platform-specific: stone builds use the rootdisk output from the manifest
archive_name=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r .storage_devices.rootdisk.out)
AVOCADO_OS_ARTIFACT="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"

# =============================================================================
# Call the common provisioning script
# =============================================================================

exec "${AVOCADO_RUNTIME_BUILD_DIR}/peridio-provision.sh" --avocado-os "$AVOCADO_OS_ARTIFACT" --installer-type fwup
