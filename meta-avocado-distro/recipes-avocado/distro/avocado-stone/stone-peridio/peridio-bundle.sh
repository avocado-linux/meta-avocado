#!/usr/bin/env bash

# Peridio Bundle Generator
# Creates a serialized bundle in Peridio's format from provisioned artifacts

set -e

# Verbose logging helper
log_verbose() {
    if [ -n "${AVOCADO_VERBOSE:-}" ]; then
        echo "$@"
    fi
}

# Parse command line arguments
OUT_DIR=""
INSTALLER_TYPE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --out)
            OUT_DIR="$2"
            shift 2
            ;;
        --installer-type)
            INSTALLER_TYPE="$2"
            shift 2
            ;;
        *)
            echo "Error: Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$OUT_DIR" ]; then
    echo "Error: --out directory is required"
    exit 1
fi

if [ -z "$INSTALLER_TYPE" ]; then
    echo "Error: --installer-type is required"
    exit 1
fi

# Ensure output directory exists
mkdir -p "$OUT_DIR"

# Check required environment variables
if [ -z "${AVOCADO_PROVISION_STATE:-}" ]; then
    echo "Error: AVOCADO_PROVISION_STATE is not set"
    exit 1
fi

if [ -z "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "Error: AVOCADO_PROVISION_OUT is not set"
    exit 1
fi

if [ -z "${AVOCADO_DISTRO_VERSION:-}" ]; then
    echo "Error: AVOCADO_DISTRO_VERSION is not set"
    exit 1
fi

if [ -z "${AVOCADO_TARGET:-}" ]; then
    echo "Error: AVOCADO_TARGET is not set"
    exit 1
fi

if [ -z "${AVOCADO_RUNTIME_NAME:-}" ]; then
    echo "Error: AVOCADO_RUNTIME_NAME is not set"
    exit 1
fi

if [ -z "${AVOCADO_RUNTIME_VERSION:-}" ]; then
    echo "Error: AVOCADO_RUNTIME_VERSION is not set"
    exit 1
fi

STATE_FILE="${AVOCADO_PROVISION_STATE}"
PROVISION_DIR="${AVOCADO_PROVISION_OUT}"
TARGET="${AVOCADO_TARGET}"
RUNTIME_NAME="${AVOCADO_RUNTIME_NAME}"
RUNTIME_VERSION="${AVOCADO_RUNTIME_VERSION}"
BUNDLE_NAME="${RUNTIME_NAME}-${RUNTIME_VERSION}"

log_verbose "=== Peridio Bundle Generator ==="
log_verbose "State file: $STATE_FILE"
log_verbose "Provision directory: $PROVISION_DIR"
log_verbose "Output directory: $OUT_DIR"
log_verbose "Target: $TARGET"
log_verbose "Bundle name: $BUNDLE_NAME"

# Load state file
if [ ! -f "$STATE_FILE" ]; then
    echo "Error: State file does not exist: $STATE_FILE"
    exit 1
fi

PERIDIO_STATE=$(cat "$STATE_FILE")
log_verbose "State loaded successfully"

# Function to generate a new UUID
generate_uuid() {
    uuidgen | tr '[:upper:]' '[:lower:]'
}

# Function to get artifact ID from state
get_artifact_id() {
    local artifact_name="$1"
    echo "$PERIDIO_STATE" | jq -r ".artifacts.\"$artifact_name\".id // empty"
}

# Function to get version ID from state
get_version_id() {
    local artifact_name="$1"
    local version="$2"
    echo "$PERIDIO_STATE" | jq -r ".artifacts.\"$artifact_name\".versions.\"$version\".id // empty"
}

# Function to parse extension name and version from filename
parse_extension() {
    local filename="$1"
    local basename=$(basename "$filename" .raw)
    
    # Match pattern: <name>-<version>
    if [[ "$basename" =~ ^(.+)-([0-9]+\.[0-9]+\.[0-9]+.*)$ ]]; then
        echo "${BASH_REMATCH[1]}|${BASH_REMATCH[2]}"
    else
        echo "$basename|unknown"
    fi
}

# Function to get file hash (sha256)
get_file_hash() {
    local file="$1"
    sha256sum "$file" | cut -d' ' -f1
}

# Function to get file size
get_file_size() {
    local file="$1"
    stat -c%s "$file"
}

# Function to get signature from .sig file
get_signature_info() {
    local sig_file="$1"
    if [ -f "$sig_file" ]; then
        cat "$sig_file"
    else
        echo '{"keyid": "", "signature": ""}'
    fi
}

# Function to compute bundle hash using JCS (JSON Canonicalization Scheme)
# This matches the server-side hash computation
compute_bundle_hash() {
    local manifest_json="$1"
    
    # Apply JCS: sort keys lexicographically and compact format
    local jcs_json
    jcs_json=$(echo "$manifest_json" | jq -Sc '[.[] | {
        artifact_id,
        artifact_version_id,
        binary_id,
        custom_metadata,
        hash,
        size,
        target
    }]')
    
    # Compute SHA256 hash and encode as lowercase hex
    echo -n "$jcs_json" | sha256sum | cut -d' ' -f1
}

# Function to generate custom metadata from template
# Args: artifact_type ("avocado-os" or "avocado-ext") [ext_name] [ext_version]
generate_custom_metadata() {
    local artifact_type="$1"
    local ext_name="${2:-}"
    local ext_version="${3:-}"
    local installer=""
    local installer_opts=""
    local reboot_required=""
    
    if [ "$artifact_type" = "avocado-os" ]; then
        installer="avocado-os"
        installer_opts="{\"type\": \"${INSTALLER_TYPE}\"}"
        reboot_required="true"
    else
        installer="avocado-ext"
        installer_opts="{\"name\": \"${ext_name}-${ext_version}\", \"image\": \"${ext_name}-${ext_version}.raw\", \"enabled\": true}"
        reboot_required="false"
    fi
    
    # Generate the custom metadata JSON
    jq -n \
        --arg installer "$installer" \
        --argjson installer_opts "$installer_opts" \
        --argjson reboot_required "$reboot_required" \
        '{
            "peridiod": {
                "installer": $installer,
                "installer_opts": $installer_opts,
                "reboot_required": $reboot_required
            }
        }'
}

# Initialize artifacts and manifest arrays
ARTIFACTS_JSON="{}"
MANIFEST_JSON="[]"

log_verbose ""
log_verbose "=== Processing Avocado OS ==="

# Find the avocado-os archive (zip or swu file depending on installer type)
AVOCADO_OS_FILE=""
case "$INSTALLER_TYPE" in
    fwup)
        for f in "$PROVISION_DIR"/*.zip; do
            if [ -f "$f" ]; then
                AVOCADO_OS_FILE="$f"
                break
            fi
        done
        ;;
    swupdate)
        for f in "$PROVISION_DIR"/*.swu; do
            if [ -f "$f" ]; then
                AVOCADO_OS_FILE="$f"
                break
            fi
        done
        ;;
    *)
        echo "Error: Unknown installer type: $INSTALLER_TYPE"
        exit 1
        ;;
esac

if [ -z "$AVOCADO_OS_FILE" ] || [ ! -f "$AVOCADO_OS_FILE" ]; then
    echo "Error: Avocado OS archive not found in $PROVISION_DIR (expected .$INSTALLER_TYPE archive)"
    exit 1
fi

log_verbose "Found Avocado OS: $(basename "$AVOCADO_OS_FILE")"

# Get avocado-os IDs from state
AVOCADO_OS_ARTIFACT_ID=$(get_artifact_id "avocado-os")
AVOCADO_OS_VERSION_ID=$(get_version_id "avocado-os" "$AVOCADO_DISTRO_VERSION")

if [ -z "$AVOCADO_OS_ARTIFACT_ID" ]; then
    echo "Error: avocado-os artifact not found in state"
    exit 1
fi

if [ -z "$AVOCADO_OS_VERSION_ID" ]; then
    echo "Error: avocado-os version $AVOCADO_DISTRO_VERSION not found in state"
    exit 1
fi

# Generate binary ID for avocado-os
AVOCADO_OS_BINARY_ID=$(generate_uuid)

# Get file info
AVOCADO_OS_HASH=$(get_file_hash "$AVOCADO_OS_FILE")
AVOCADO_OS_SIZE=$(get_file_size "$AVOCADO_OS_FILE")
AVOCADO_OS_SIG_FILE="${AVOCADO_OS_FILE}.sig"

# Get signature info
AVOCADO_OS_SIG_JSON=$(get_signature_info "$AVOCADO_OS_SIG_FILE")
AVOCADO_OS_KEYID=$(echo "$AVOCADO_OS_SIG_JSON" | jq -r '.keyid // ""')
AVOCADO_OS_SIGNATURE=$(echo "$AVOCADO_OS_SIG_JSON" | jq -r '.signature // ""')

log_verbose "  Artifact ID: $AVOCADO_OS_ARTIFACT_ID"
log_verbose "  Version ID: $AVOCADO_OS_VERSION_ID"
log_verbose "  Binary ID: $AVOCADO_OS_BINARY_ID"
log_verbose "  Hash: $AVOCADO_OS_HASH"
log_verbose "  Size: $AVOCADO_OS_SIZE"

# Add avocado-os to artifacts
ARTIFACTS_JSON=$(echo "$ARTIFACTS_JSON" | jq \
    --arg artifact_id "$AVOCADO_OS_ARTIFACT_ID" \
    --arg version_id "$AVOCADO_OS_VERSION_ID" \
    --arg binary_id "$AVOCADO_OS_BINARY_ID" \
    --arg version "$AVOCADO_DISTRO_VERSION" \
    --arg keyid "$AVOCADO_OS_KEYID" \
    --arg sig "$AVOCADO_OS_SIGNATURE" \
    '.[$artifact_id] = {
        "name": "avocado-os",
        "description": null,
        "versions": {
            ($version_id): {
                "version": $version,
                "description": null,
                "binaries": {
                    ($binary_id): {
                        "description": null,
                        "signatures": [{"keyid": $keyid, "sig": $sig}]
                    }
                }
            }
        }
    }')

# Generate custom metadata for avocado-os
AVOCADO_OS_CUSTOM_METADATA=$(generate_custom_metadata "avocado-os")

# Add avocado-os to manifest
MANIFEST_JSON=$(echo "$MANIFEST_JSON" | jq \
    --arg hash "$AVOCADO_OS_HASH" \
    --argjson size "$AVOCADO_OS_SIZE" \
    --arg binary_id "$AVOCADO_OS_BINARY_ID" \
    --arg target "$TARGET" \
    --arg artifact_version_id "$AVOCADO_OS_VERSION_ID" \
    --arg artifact_id "$AVOCADO_OS_ARTIFACT_ID" \
    --argjson custom_metadata "$AVOCADO_OS_CUSTOM_METADATA" \
    '. += [{
        "hash": $hash,
        "size": $size,
        "binary_id": $binary_id,
        "target": $target,
        "artifact_version_id": $artifact_version_id,
        "artifact_id": $artifact_id,
        "custom_metadata": $custom_metadata
    }]')

# Process extensions
log_verbose ""
log_verbose "=== Processing Extensions ==="

EXT_LIST="${AVOCADO_EXT_LIST:-}"

if [ -z "$EXT_LIST" ]; then
    log_verbose "No extensions to process (AVOCADO_EXT_LIST is empty)"
else
    for ext_name in $EXT_LIST; do
        # Add .raw extension if not present
        case "$ext_name" in
            *.raw) ext_file="$ext_name" ;;
            *)     ext_file="${ext_name}.raw" ;;
        esac
        
        ext_path="${PROVISION_DIR}/${ext_file}"
        ext_sig="${ext_path}.sig"
        
        if [ ! -f "$ext_path" ]; then
            log_verbose "Extension not found: $ext_path"
            continue
        fi
        
        log_verbose "Processing extension: $ext_file"
        
        # Parse extension name and version
        parsed=$(parse_extension "$ext_file")
        parsed_name=$(echo "$parsed" | cut -d'|' -f1)
        parsed_version=$(echo "$parsed" | cut -d'|' -f2)
        
        # Get IDs from state
        EXT_ARTIFACT_ID=$(get_artifact_id "$parsed_name")
        EXT_VERSION_ID=$(get_version_id "$parsed_name" "$parsed_version")
        
        if [ -z "$EXT_ARTIFACT_ID" ] || [ -z "$EXT_VERSION_ID" ]; then
            log_verbose "  Skipping: artifact or version not found in state"
            continue
        fi
        
        # Generate binary ID
        EXT_BINARY_ID=$(generate_uuid)
        
        # Get file info
        EXT_HASH=$(get_file_hash "$ext_path")
        EXT_SIZE=$(get_file_size "$ext_path")
        
        # Get signature info
        EXT_SIG_JSON=$(get_signature_info "$ext_sig")
        EXT_KEYID=$(echo "$EXT_SIG_JSON" | jq -r '.keyid // ""')
        EXT_SIGNATURE=$(echo "$EXT_SIG_JSON" | jq -r '.signature // ""')
        
        # Verify extension has a valid signature
        if [ ! -f "$ext_sig" ] || [ -z "$EXT_KEYID" ] || [ -z "$EXT_SIGNATURE" ]; then
            echo "Error: Extension '$parsed_name' is unsigned or has an invalid signature."
            echo "Please sign the runtime first by running:"
            echo "  avocado runtime sign -r ${RUNTIME_NAME}"
            exit 1
        fi
        
        log_verbose "  Artifact ID: $EXT_ARTIFACT_ID"
        log_verbose "  Version ID: $EXT_VERSION_ID"
        log_verbose "  Binary ID: $EXT_BINARY_ID"
        log_verbose "  Hash: $EXT_HASH"
        log_verbose "  Size: $EXT_SIZE"
        
        # Add extension to artifacts
        ARTIFACTS_JSON=$(echo "$ARTIFACTS_JSON" | jq \
            --arg artifact_id "$EXT_ARTIFACT_ID" \
            --arg version_id "$EXT_VERSION_ID" \
            --arg binary_id "$EXT_BINARY_ID" \
            --arg name "$parsed_name" \
            --arg version "$parsed_version" \
            --arg keyid "$EXT_KEYID" \
            --arg sig "$EXT_SIGNATURE" \
            '.[$artifact_id] = {
                "name": $name,
                "description": null,
                "versions": {
                    ($version_id): {
                        "version": $version,
                        "description": null,
                        "binaries": {
                            ($binary_id): {
                                "description": null,
                                "signatures": [{"keyid": $keyid, "sig": $sig}]
                            }
                        }
                    }
                }
            }')
        
        # Generate custom metadata for extension
        EXT_CUSTOM_METADATA=$(generate_custom_metadata "avocado-ext" "$parsed_name" "$parsed_version")
        
        # Add extension to manifest
        MANIFEST_JSON=$(echo "$MANIFEST_JSON" | jq \
            --arg hash "$EXT_HASH" \
            --argjson size "$EXT_SIZE" \
            --arg binary_id "$EXT_BINARY_ID" \
            --arg target "$TARGET" \
            --arg artifact_version_id "$EXT_VERSION_ID" \
            --arg artifact_id "$EXT_ARTIFACT_ID" \
            --argjson custom_metadata "$EXT_CUSTOM_METADATA" \
            '. += [{
                "hash": $hash,
                "size": $size,
                "binary_id": $binary_id,
                "target": $target,
                "artifact_version_id": $artifact_version_id,
                "artifact_id": $artifact_id,
                "custom_metadata": $custom_metadata
            }]')
    done
fi

# Generate bundle ID
BUNDLE_ID=$(generate_uuid)

log_verbose ""
log_verbose "=== Generating Bundle ==="
log_verbose "Bundle ID: $BUNDLE_ID"

# Create the manifest content for signing
MANIFEST_CONTENT=$(echo "$MANIFEST_JSON" | jq -c '.')

# Sign the manifest
log_verbose ""
log_verbose "=== Signing Bundle Manifest ==="

BUNDLE_KEYID=""
BUNDLE_SIGNATURE=""

# Create a temporary file for the manifest to sign
MANIFEST_TEMP_FILE=$(mktemp)
echo -n "$MANIFEST_CONTENT" > "$MANIFEST_TEMP_FILE"

if command -v avocado-sign-request &> /dev/null; then
    log_verbose "Requesting signature for bundle manifest..."
    
    if avocado-sign-request "$MANIFEST_TEMP_FILE" 2>/dev/null; then
        log_verbose "Successfully signed bundle manifest"
        MANIFEST_SIG_FILE="${MANIFEST_TEMP_FILE}.sig"
        if [ -f "$MANIFEST_SIG_FILE" ]; then
            BUNDLE_SIG_JSON=$(cat "$MANIFEST_SIG_FILE")
            BUNDLE_KEYID=$(echo "$BUNDLE_SIG_JSON" | jq -r '.keyid // ""')
            BUNDLE_SIGNATURE=$(echo "$BUNDLE_SIG_JSON" | jq -r '.signature // ""')
            log_verbose "Bundle signature obtained"
            rm -f "$MANIFEST_SIG_FILE"
        else
            log_verbose "Signature file not found"
        fi
    else
        log_verbose "Signing not available, continuing without bundle signature"
    fi
else
    log_verbose "avocado-sign-request not available, skipping bundle signing"
fi

rm -f "$MANIFEST_TEMP_FILE"

# Build the final bundle JSON
log_verbose ""
log_verbose "=== Building Final Bundle JSON ==="

# Compute bundle hash (matching server-side computation)
BUNDLE_HASH=$(compute_bundle_hash "$MANIFEST_JSON")
BUNDLE_HASH_VERSION=1

log_verbose "Bundle hash: $BUNDLE_HASH"
log_verbose "Bundle hash version: $BUNDLE_HASH_VERSION"

BUNDLE_JSON=$(jq -n \
    --argjson artifacts "$ARTIFACTS_JSON" \
    --arg bundle_id "$BUNDLE_ID" \
    --arg bundle_name "$BUNDLE_NAME" \
    --arg bundle_keyid "$BUNDLE_KEYID" \
    --arg bundle_sig "$BUNDLE_SIGNATURE" \
    --arg bundle_hash "$BUNDLE_HASH" \
    --argjson bundle_hash_version "$BUNDLE_HASH_VERSION" \
    --argjson manifest "$MANIFEST_JSON" \
    '{
        "artifacts": $artifacts,
        "bundle": {
            "id": $bundle_id,
            "name": $bundle_name,
            "hash": $bundle_hash,
            "hash_version": $bundle_hash_version,
            "signatures": [{"keyid": $bundle_keyid, "sig": $bundle_sig}],
            "manifest": $manifest
        }
    }')

# Write the bundle to output file
BUNDLE_OUTPUT_FILE="${OUT_DIR}/bundle.json"
echo "$BUNDLE_JSON" | jq '.' > "$BUNDLE_OUTPUT_FILE"

log_verbose ""
log_verbose "=== Bundle JSON Complete ==="
log_verbose "Output file: $BUNDLE_OUTPUT_FILE"
log_verbose "Artifacts: $(echo "$ARTIFACTS_JSON" | jq 'keys | length')"
log_verbose "Manifest entries: $(echo "$MANIFEST_JSON" | jq 'length')"

# Create cpio archive with zstd compression
log_verbose ""
log_verbose "=== Creating CPIO Archive ==="

ARCHIVE_NAME="${BUNDLE_NAME}.cpio.zst"
ARCHIVE_PATH="${OUT_DIR}/${ARCHIVE_NAME}"

log_verbose "Archive name: $ARCHIVE_NAME"

# Create a temporary directory to stage files for the archive
STAGING_DIR=$(mktemp -d)
trap "rm -rf $STAGING_DIR" EXIT

# Copy bundle.json to staging
cp "$BUNDLE_OUTPUT_FILE" "$STAGING_DIR/"

# Copy avocado-os zip file
if [ -n "$AVOCADO_OS_FILE" ] && [ -f "$AVOCADO_OS_FILE" ]; then
    log_verbose "  Adding: $(basename "$AVOCADO_OS_FILE")"
    cp "$AVOCADO_OS_FILE" "$STAGING_DIR/"
fi

# Copy extension files (excluding .sig files)
if [ -n "$EXT_LIST" ]; then
    for ext_name in $EXT_LIST; do
        case "$ext_name" in
            *.raw) ext_file="$ext_name" ;;
            *)     ext_file="${ext_name}.raw" ;;
        esac
        
        ext_path="${PROVISION_DIR}/${ext_file}"
        
        if [ -f "$ext_path" ]; then
            log_verbose "  Adding: $(basename "$ext_path")"
            cp "$ext_path" "$STAGING_DIR/"
        fi
    done
fi

# Create cpio archive and compress with zstd
log_verbose ""
log_verbose "Creating compressed archive..."
(cd "$STAGING_DIR" && find . -type f | cpio -o -H newc 2>/dev/null) | zstd -q -f -o "$ARCHIVE_PATH"

log_verbose ""
log_verbose "=== Bundle Generation Complete ==="
log_verbose "Bundle JSON: $BUNDLE_OUTPUT_FILE"
log_verbose "Archive: $ARCHIVE_PATH"
log_verbose "Archive size: $(stat -c%s "$ARCHIVE_PATH") bytes"

# Print summary (always shown)
echo "Peridio bundle: ${BUNDLE_NAME} ($(echo "$MANIFEST_JSON" | jq 'length') artifacts)"
