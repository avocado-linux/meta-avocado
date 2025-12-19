#!/usr/bin/env bash

# Peridio State Management
# Manages the linkage between Avocado artifacts and Peridio IDs

# Verbose logging helper
log_verbose() {
    if [ -n "${AVOCADO_VERBOSE:-}" ]; then
        echo "$@"
    fi
}

# Determine the state file location from Avocado
if [ -z "${AVOCADO_PROVISION_STATE:-}" ]; then
    echo "Error: AVOCADO_PROVISION_STATE is not set"
    exit 1
fi

STATE_FILE="${AVOCADO_PROVISION_STATE}"

# Initialize empty state that will be populated
PERIDIO_STATE=""

# Function to initialize an empty state file
init_state_file() {
    log_verbose "Creating new state file: $STATE_FILE"
    cat > "$STATE_FILE" <<'EOF'
{
  "artifacts": {}
}
EOF
}

# Function to load the state file
load_state() {
    if [ ! -f "$STATE_FILE" ]; then
        log_verbose "State file does not exist, creating: $STATE_FILE"
        mkdir -p "$(dirname "$STATE_FILE")"
        init_state_file
    else
        log_verbose "Loading existing state file: $STATE_FILE"
    fi
    
    # Validate JSON
    if ! jq empty "$STATE_FILE" 2>/dev/null; then
        echo "Error: State file contains invalid JSON, reinitializing"
        init_state_file
    fi
    
    PERIDIO_STATE=$(cat "$STATE_FILE")
}

# Function to generate a new UUID
generate_uuid() {
    uuidgen | tr '[:upper:]' '[:lower:]'
}

# Function to check if an artifact exists in state
artifact_exists() {
    local artifact_name="$1"
    echo "$PERIDIO_STATE" | jq -e ".artifacts.\"$artifact_name\"" > /dev/null 2>&1
}

# Function to check if a version exists for an artifact
version_exists() {
    local artifact_name="$1"
    local version="$2"
    echo "$PERIDIO_STATE" | jq -e ".artifacts.\"$artifact_name\".versions.\"$version\"" > /dev/null 2>&1
}

# Function to add or update an artifact in state
ensure_artifact() {
    local artifact_name="$1"
    local version="$2"
    
    if ! artifact_exists "$artifact_name"; then
        log_verbose "  Adding new artifact: $artifact_name"
        local artifact_id=$(generate_uuid)
        
        PERIDIO_STATE=$(echo "$PERIDIO_STATE" | jq \
            --arg name "$artifact_name" \
            --arg id "$artifact_id" \
            '.artifacts[$name] = {
                "id": $id,
                "versions": {}
            }')
    fi
    
    if ! version_exists "$artifact_name" "$version"; then
        log_verbose "  Adding new version: $artifact_name @ $version"
        local version_id=$(generate_uuid)
        PERIDIO_STATE=$(echo "$PERIDIO_STATE" | jq \
            --arg name "$artifact_name" \
            --arg ver "$version" \
            --arg id "$version_id" \
            '.artifacts[$name].versions[$ver] = {"id": $id}')
    else
        log_verbose "  Version already exists: $artifact_name @ $version"
    fi
}

# Function to parse extension name and version from filename
parse_extension() {
    local filename="$1"
    local basename=$(basename "$filename" .raw)
    
    # Match pattern: <name>-<version>
    if [[ "$basename" =~ ^(.+)-([0-9]+\.[0-9]+\.[0-9]+.*)$ ]]; then
        echo "${BASH_REMATCH[1]}|${BASH_REMATCH[2]}"
    else
        # If no version pattern found, use the whole name and empty version
        echo "$basename|unknown"
    fi
}

# Function to process all artifacts for the current provisioning run
process_artifacts() {
    log_verbose "=== Processing Artifacts ==="
    
    # Process avocado-os artifact
    if [ -z "${AVOCADO_DISTRO_VERSION:-}" ]; then
        echo "Error: AVOCADO_DISTRO_VERSION is not set"
        exit 1
    fi
    
    local distro_version="$AVOCADO_DISTRO_VERSION"
    log_verbose "Processing avocado-os version: $distro_version"
    ensure_artifact "avocado-os" "$distro_version"
    
    # Process extensions
    if [ -n "${AVOCADO_EXT_LIST:-}" ]; then
        log_verbose "Processing extensions from AVOCADO_EXT_LIST"
        for ext_file in $AVOCADO_EXT_LIST; do
            # Remove .raw extension if present for parsing
            ext_file="${ext_file%.raw}"
            
            local parsed=$(parse_extension "$ext_file")
            local ext_name=$(echo "$parsed" | cut -d'|' -f1)
            local ext_version=$(echo "$parsed" | cut -d'|' -f2)
            
            log_verbose "Processing extension: $ext_name version: $ext_version"
            ensure_artifact "$ext_name" "$ext_version"
        done
    else
        log_verbose "No extensions to process (AVOCADO_EXT_LIST is empty)"
    fi
}

# Function to save the state file
save_state() {
    log_verbose "Saving state to: $STATE_FILE"
    echo "$PERIDIO_STATE" | jq '.' > "$STATE_FILE"
}

# Function to get artifact ID
get_artifact_id() {
    local artifact_name="$1"
    echo "$PERIDIO_STATE" | jq -r ".artifacts.\"$artifact_name\".id // empty"
}

# Function to get version ID
get_version_id() {
    local artifact_name="$1"
    local version="$2"
    echo "$PERIDIO_STATE" | jq -r ".artifacts.\"$artifact_name\".versions.\"$version\".id // empty"
}

# Initialize state management
load_state
process_artifacts




