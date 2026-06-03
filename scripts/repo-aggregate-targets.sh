#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Script to aggregate target-specific JSON fragments into a complete targets.json file
# This script combines individual target fragments created during the build process
# into a single targets.json file for deployment.
#
# The script supports merging with existing targets.json files to handle cases where
# only a subset of targets are built (e.g., single machine workflow dispatch).

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
    echo "Usage: $0 <fragments-directory> <output-file> [existing-targets-json]"
    echo "Example: $0 /path/to/staging/fragments /path/to/releases/targets.json"
    echo "Example: $0 /path/to/staging/fragments /path/to/releases/targets.json /path/to/existing/targets.json"
    echo ""
    echo "If existing-targets-json is provided, new fragments will be merged with existing targets."
    echo "If not provided, the script will look for an existing targets.json at the output location."
    exit 1
fi

FRAGMENTS_DIR=$1
OUTPUT_FILE=$2
EXISTING_TARGETS_FILE=${3:-$OUTPUT_FILE}

echo "Aggregating target fragments from: ${FRAGMENTS_DIR}"
echo "Output file: ${OUTPUT_FILE}"

# Check if fragments directory exists
if [ ! -d "${FRAGMENTS_DIR}" ]; then
    echo "Error: Fragments directory not found at ${FRAGMENTS_DIR}" >&2
    exit 1
fi

# Create output directory if it doesn't exist
OUTPUT_DIR=$(dirname "${OUTPUT_FILE}")
mkdir -p "${OUTPUT_DIR}"

# Read existing targets.json if it exists
existing_targets=()
if [ -f "$EXISTING_TARGETS_FILE" ] && [ -s "$EXISTING_TARGETS_FILE" ]; then
    echo "Found existing targets file: $EXISTING_TARGETS_FILE"

    # Extract existing targets using jq if available, otherwise use basic parsing
    if command -v jq >/dev/null 2>&1; then
        # Use jq to extract key-value pairs
        while IFS= read -r target_entry; do
            if [ -n "$target_entry" ]; then
                existing_targets+=("$target_entry")
            fi
        done < <(jq -r 'to_entries[] | "\"\(.key)\":\(.value | @json)"' "$EXISTING_TARGETS_FILE" 2>/dev/null || true)
    else
        echo "Warning: jq not available, using basic JSON parsing"
        # Basic parsing - extract content between outer braces
        existing_content=$(cat "$EXISTING_TARGETS_FILE" | sed 's/^{//' | sed 's/}$//')
        if [ -n "$existing_content" ] && [ "$existing_content" != "{}" ]; then
            existing_targets+=("$existing_content")
        fi
    fi

    echo "Found ${#existing_targets[@]} existing target(s)"
else
    echo "No existing targets file found or file is empty"
fi

# Find all fragment files
fragment_files=($(find "${FRAGMENTS_DIR}" -name "*-fragment.json" -type f | sort))

if [ ${#fragment_files[@]} -eq 0 ]; then
    if [ ${#existing_targets[@]} -eq 0 ]; then
        echo "Warning: No fragment files found and no existing targets"
        echo "Creating empty targets.json file"
        echo "{}" > "${OUTPUT_FILE}"
        exit 0
    else
        echo "No new fragments found, preserving existing targets"
        # Reconstruct from existing targets
        printf "{" > "${OUTPUT_FILE}"
        first_target=true
        for target_entry in "${existing_targets[@]}"; do
            if [ "$first_target" = false ]; then
                printf "," >> "${OUTPUT_FILE}"
            fi
            first_target=false
            printf '%s' "$target_entry" >> "${OUTPUT_FILE}"
        done
        printf "}" >> "${OUTPUT_FILE}"
        echo "Preserved existing targets.json"
        exit 0
    fi
fi

echo "Found ${#fragment_files[@]} new fragment files:"
for file in "${fragment_files[@]}"; do
    echo "  - $(basename "$file")"
done

# Collect new targets from fragments
new_targets=()
new_target_names=()

for fragment_file in "${fragment_files[@]}"; do
    echo "Processing fragment: $(basename "$fragment_file")"

    # Validate fragment file is not empty
    if [ ! -s "$fragment_file" ]; then
        echo "  Warning: Fragment file is empty: $fragment_file"
        continue
    fi

    # Extract the content between the outer braces (works with both compact and formatted JSON)
    # Remove the outer { and } and extract the key-value pair
    fragment_content=$(cat "${fragment_file}" | sed 's/^{//' | sed 's/}$//')

    # Extract target name for duplicate detection
    target_name=$(echo "$fragment_content" | sed 's/^\"\([^\"]*\)\".*/\1/')

    # Debug: show what we're adding
    echo "  Target: $target_name"
    echo "  Adding content: ${fragment_content:0:100}$([ ${#fragment_content} -gt 100 ] && echo "...")"

    new_targets+=("$fragment_content")
    new_target_names+=("$target_name")
done

# Start building the aggregated JSON (compact format)
printf "{" > "${OUTPUT_FILE}"

# Add existing targets first (excluding any that are being updated by new fragments)
first_entry=true
for target_entry in "${existing_targets[@]}"; do
    # Extract target name from existing entry
    existing_target_name=$(echo "$target_entry" | sed 's/^\"\([^\"]*\)\".*/\1/')

    # Check if this target is being updated by a new fragment
    target_being_updated=false
    for new_target_name in "${new_target_names[@]}"; do
        if [ "$existing_target_name" = "$new_target_name" ]; then
            target_being_updated=true
            echo "Updating existing target: $existing_target_name"
            break
        fi
    done

    # Only add existing target if it's not being updated
    if [ "$target_being_updated" = false ]; then
        if [ "$first_entry" = false ]; then
            printf "," >> "${OUTPUT_FILE}"
        fi
        first_entry=false
        printf '%s' "$target_entry" >> "${OUTPUT_FILE}"
        echo "Preserving existing target: $existing_target_name"
    fi
done

# Add new/updated targets from fragments
for target_content in "${new_targets[@]}"; do
    if [ "$first_entry" = false ]; then
        printf "," >> "${OUTPUT_FILE}"
    fi
    first_entry=false
    printf '%s' "$target_content" >> "${OUTPUT_FILE}"
done

# Close the JSON object
printf "}" >> "${OUTPUT_FILE}"

echo "Aggregation complete!"
total_targets=$((${#existing_targets[@]} + ${#new_targets[@]} - ${#new_target_names[@]}))
echo "Generated targets.json with $total_targets total targets:"
echo "  - ${#existing_targets[@]} existing targets (${#new_target_names[@]} updated)"
echo "  - ${#new_targets[@]} new/updated targets from fragments"

# Validate the generated JSON
if command -v jq >/dev/null 2>&1; then
    echo "Validating generated JSON..."
    if jq empty "${OUTPUT_FILE}" 2>/dev/null; then
        echo "✓ Generated JSON is valid"
        echo "Preview of generated targets.json (formatted for readability):"
        jq . "${OUTPUT_FILE}" | head -20
        if [ $(jq . "${OUTPUT_FILE}" | wc -l) -gt 20 ]; then
            echo "... (truncated)"
        fi
        echo ""
        echo "Compact size: $(wc -c < "${OUTPUT_FILE}") bytes"
    else
        echo "✗ Generated JSON is invalid" >&2
        echo "Raw content:"
        cat "${OUTPUT_FILE}"
        exit 1
    fi
else
    echo "Note: jq not available for JSON validation"
    echo "Raw compact JSON:"
    cat "${OUTPUT_FILE}"
    echo ""
    echo "Size: $(wc -c < "${OUTPUT_FILE}") bytes"
fi

echo "Targets aggregation complete!"
