#!/usr/bin/env bash

# Peridio Provisioning - Reusable Logic
# This script contains all the platform-independent provisioning logic.
# It should be called by platform-specific scripts that provide the avocado-os artifact path.

set -e

# Verbose logging helper
log_verbose() {
    if [ -n "${AVOCADO_VERBOSE:-}" ]; then
        echo "$@"
    fi
}

# Parse command line arguments
AVOCADO_OS_ARTIFACT=""
INSTALLER_TYPE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --avocado-os)
            AVOCADO_OS_ARTIFACT="$2"
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

if [ -z "$AVOCADO_OS_ARTIFACT" ]; then
    echo "Error: --avocado-os <artifact_path> is required"
    exit 1
fi

if [ -z "$INSTALLER_TYPE" ]; then
    echo "Error: --installer-type is required"
    exit 1
fi

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source peridio state management
source "${SCRIPT_DIR}/peridio-state.sh"

log_verbose "=== Peridio Provisioning ==="
log_verbose "Device ID: ${AVOCADO_DEVICE_ID:-not set}"
log_verbose "Build Dir: ${AVOCADO_STONE_BUILD_DIR}"
log_verbose "Data Dir: ${AVOCADO_STONE_DATA_DIR}"

# Check if signing is available
if [ -n "$AVOCADO_SIGNING_ENABLED" ]; then
    log_verbose "Signing is available"
    log_verbose "Using key: ${AVOCADO_SIGNING_KEY_NAME}"
    log_verbose "Algorithm: ${AVOCADO_SIGNING_CHECKSUM}"
fi

# Check if AVOCADO_PROVISION_OUT is set and create directory
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    log_verbose "AVOCADO_PROVISION_OUT is set: $AVOCADO_PROVISION_OUT"
    mkdir -p "$AVOCADO_PROVISION_OUT"
fi

# Validate avocado-os artifact
log_verbose "=== Validating Avocado OS Artifact ==="
archive_file="$AVOCADO_OS_ARTIFACT"

if [ ! -f "$archive_file" ]; then
    echo "Error: Avocado OS artifact not found: $archive_file"
    exit 1
fi

log_verbose "Avocado OS artifact: $archive_file ($(stat -c%s "$archive_file") bytes)"

# Sign the archive file
log_verbose "=== Signing Avocado OS Artifact ==="
if command -v avocado-sign-request &> /dev/null; then
    log_verbose "Requesting signature from host for: $archive_file"
    
    if avocado-sign-request "$archive_file"; then
        log_verbose "Successfully signed: $archive_file"
        ARCHIVE_SIG="${archive_file}.sig"
        if [ -f "$ARCHIVE_SIG" ]; then
            log_verbose "Signature file created: $ARCHIVE_SIG"
        else
            echo "Warning: Signature file not found at expected location"
        fi
    else
        EXIT_CODE=$?
        case $EXIT_CODE in
            1)
                echo "Error: Signing failed"
                exit 1
                ;;
            2)
                log_verbose "Signing not available, continuing without signature"
                ;;
            3)
                echo "Error: Artifact file not found"
                exit 1
                ;;
            *)
                echo "Error: Unknown signing error (exit code: $EXIT_CODE)"
                exit 1
                ;;
        esac
    fi
else
    log_verbose "avocado-sign-request not available, skipping signing"
fi

# Collect extensions
log_verbose "=== Collecting Extension Images ==="
EXT_SOURCES="${AVOCADO_RUNTIME_BUILD_DIR}/extensions"
EXT_LIST="${AVOCADO_EXT_LIST:-}"

EXTENSIONS_FOUND=()
EXTENSION_SIGS_FOUND=()

if [ -z "$EXT_LIST" ]; then
    log_verbose "No extensions to collect (AVOCADO_EXT_LIST is empty)"
elif [ ! -d "$EXT_SOURCES" ]; then
    log_verbose "Extension directory not found: $EXT_SOURCES"
else
    log_verbose "Using extension directory: $EXT_SOURCES"
    for ext_name in $EXT_LIST; do
        # Add .raw extension if not present
        case "$ext_name" in
            *.raw) ext_file="$ext_name" ;;
            *)     ext_file="${ext_name}.raw" ;;
        esac
        
        ext_path="${EXT_SOURCES}/${ext_file}"
        ext_sig="${ext_path}.sig"
        
        if [ -f "$ext_path" ]; then
            log_verbose "  Found extension: ${ext_file}"
            EXTENSIONS_FOUND+=("$ext_path")
            
            if [ -f "$ext_sig" ]; then
                log_verbose "  Found signature: ${ext_file}.sig"
                EXTENSION_SIGS_FOUND+=("$ext_sig")
            else
                log_verbose "  No signature found for ${ext_file}"
            fi
        else
            log_verbose "  Extension image not found: ${ext_path}"
        fi
    done
fi

# Summary
log_verbose ""
log_verbose "=== Provisioning Summary ==="
log_verbose "Avocado OS artifact: $(basename "$archive_file")"
if [ -f "${archive_file}.sig" ]; then
    log_verbose "Artifact signature: $(basename "${archive_file}.sig")"
else
    log_verbose "Artifact signature: NOT FOUND"
fi
log_verbose "Extensions found: ${#EXTENSIONS_FOUND[@]}"
log_verbose "Extension signatures found: ${#EXTENSION_SIGS_FOUND[@]}"

# Copy outputs to AVOCADO_PROVISION_OUT if set
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    log_verbose ""
    log_verbose "=== Copying Output Files to $AVOCADO_PROVISION_OUT ==="
    
    # Copy archive file
    log_verbose "Copying artifact: $(basename "$archive_file")"
    cp "$archive_file" "$AVOCADO_PROVISION_OUT/"
    
    # Copy archive signature if it exists
    if [ -f "${archive_file}.sig" ]; then
        log_verbose "Copying artifact signature: $(basename "${archive_file}.sig")"
        cp "${archive_file}.sig" "$AVOCADO_PROVISION_OUT/"
    fi
    
    # Copy extension files
    for ext_path in "${EXTENSIONS_FOUND[@]}"; do
        log_verbose "Copying extension: $(basename "$ext_path")"
        cp "$ext_path" "$AVOCADO_PROVISION_OUT/"
    done
    
    # Copy extension signatures
    for sig_path in "${EXTENSION_SIGS_FOUND[@]}"; do
        log_verbose "Copying extension signature: $(basename "$sig_path")"
        cp "$sig_path" "$AVOCADO_PROVISION_OUT/"
    done
    
    log_verbose "Copy complete"
    
    # Save the state file before generating the bundle
    # (bundle script reads the state file, so it must be persisted first)
    save_state
    
    # Generate the Peridio bundle
    log_verbose ""
    log_verbose "=== Generating Peridio Bundle ==="
    "${SCRIPT_DIR}/peridio-bundle.sh" --out "$AVOCADO_PROVISION_OUT" --installer-type "$INSTALLER_TYPE"
fi

log_verbose ""
log_verbose "=== Peridio Provisioning Complete ==="



