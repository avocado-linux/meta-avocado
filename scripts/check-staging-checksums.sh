#!/bin/bash

# Fast RPM checksum analyzer using bash and RPM tools
# This version eliminates database overhead for maximum speed

set -euo pipefail

# Default values
DEFAULT_STAGING_BASE="/mnt/raid/repo/staging"
VERBOSE=false
QUIET=false
MAX_JOBS=$(nproc)
OUTPUT_FORMAT="text"
SHOW_PROGRESS=true

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Usage function
usage() {
    cat << EOF
Usage: $0 [OPTIONS] [STAGING_DIR]

Fast RPM checksum analyzer for staging directories.

OPTIONS:
    -v, --verbose       Enable verbose output
    -q, --quiet         Suppress progress and info messages
    -j, --jobs N        Number of parallel jobs (default: $(nproc))
    --format FORMAT     Output format: text, json, csv (default: text)
    --no-progress       Disable progress display
    -h, --help          Show this help message

ARGUMENTS:
    STAGING_DIR         Staging directory to analyze (default: find latest in $DEFAULT_STAGING_BASE)

EXAMPLES:
    $0                                    # Use latest timestamped dir in default staging
    $0 /path/to/staging                   # Use latest timestamped dir in custom staging
    $0 /path/to/staging/2025-01-15-123456 # Analyze specific timestamped directory
    $0 -j 64 --verbose /path/to/staging   # Use 64 parallel jobs with verbose output

EOF
}

# Logging functions
log_info() {
    if [[ "$QUIET" != "true" ]]; then
        echo -e "${BLUE}INFO:${NC} $1" >&2
    fi
}

log_verbose() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${YELLOW}VERBOSE:${NC} $1" >&2
    fi
}

log_error() {
    echo -e "${RED}ERROR:${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}WARNING:${NC} $1" >&2
}

# Progress display function
show_progress() {
    local current=$1
    local total=$2
    local desc="$3"
    
    if [[ "$SHOW_PROGRESS" != "true" ]] || [[ "$QUIET" == "true" ]]; then
        return
    fi
    
    local percent=$((current * 100 / total))
    
    # Simple percentage display - always works in any terminal
    printf "\r%s: %d%% (%d/%d)" "$desc" $percent $current $total
}

# Find latest timestamped directory
find_latest_staging_dir() {
    local base_dir="$1"
    
    if [[ ! -d "$base_dir" ]]; then
        log_error "Staging base directory does not exist: $base_dir"
        exit 2
    fi
    
    # Look for timestamped directories (YYYY-MM-DD-HHMMSS format)
    local latest_dir
    latest_dir=$(find "$base_dir" -maxdepth 1 -type d -name "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]" | sort -r | head -1)
    
    if [[ -z "$latest_dir" ]]; then
        log_error "No timestamped staging directories found in $base_dir"
        exit 2
    fi
    
    echo "$latest_dir"
}

# Determine staging directory to analyze
determine_staging_dir() {
    local input_path="$1"
    
    if [[ -z "$input_path" ]]; then
        # Use default staging base and find latest
        log_verbose "Looking for latest timestamped directory in $DEFAULT_STAGING_BASE"
        find_latest_staging_dir "$DEFAULT_STAGING_BASE"
    elif [[ -d "$input_path" ]]; then
        # Check if it's a timestamped directory or a base directory
        if [[ $(basename "$input_path") =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}$ ]]; then
            # It's already a timestamped directory
            echo "$input_path"
        else
            # It's a base directory, find latest timestamped subdir
            log_verbose "Looking for latest timestamped directory in $input_path"
            find_latest_staging_dir "$input_path"
        fi
    else
        log_error "Staging directory does not exist: $input_path"
        exit 2
    fi
}

# Extract RPM checksum and package info
extract_rpm_info() {
    local rpm_file="$1"
    local staging_dir="$2"
    
    # Get checksum and package name from RPM
    local rpm_info
    if ! rpm_info=$(rpm -qp --qf '%{SHA256HEADER}|%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' "$rpm_file" 2>/dev/null); then
        log_verbose "Failed to extract RPM info from: $rpm_file"
        return 1
    fi
    
    local checksum="${rpm_info%|*}"
    local package_name="${rpm_info#*|}"
    
    # Validate checksum format
    if [[ ! "$checksum" =~ ^[0-9a-f]{64}$ ]]; then
        log_verbose "Invalid checksum format from: $rpm_file"
        return 1
    fi
    
    # Calculate normalized path (relative to staging dir)
    local rel_path="${rpm_file#$staging_dir/}"
    local dir_path="${rel_path%/*}"
    
    # Output: checksum|package_name|normalized_path|full_path
    echo "${checksum}|${package_name}|${dir_path}|${rpm_file}"
}

# Process RPM files in parallel
process_rpms_parallel() {
    local staging_dir="$1"
    local temp_dir="$2"
    
    log_info "Phase 1: Discovering RPM files..."
    
    # Find all RPM files
    local rpm_files=()
    while IFS= read -r -d '' file; do
        rpm_files+=("$file")
    done < <(find "$staging_dir" -name "*.rpm" -type f -print0)
    
    local total_files=${#rpm_files[@]}
    log_info "Found $total_files RPM files"
    
    if [[ $total_files -eq 0 ]]; then
        log_warn "No RPM files found in $staging_dir"
        return 0
    fi
    
    log_info "Phase 2: Extracting RPM checksums (using $MAX_JOBS parallel jobs)..."
    
    # Export functions for parallel execution
    export -f extract_rpm_info log_verbose show_progress
    export VERBOSE SHOW_PROGRESS QUIET
    
    # Process files in parallel and save results
    local results_file="$temp_dir/rpm_results.txt"
    local progress_file="$temp_dir/progress.txt"
    echo "0" > "$progress_file"
    
    # Use GNU parallel or xargs for parallel processing
    if command -v parallel >/dev/null 2>&1; then
        # Use GNU parallel if available (with progress bar)
        if [[ "$SHOW_PROGRESS" == "true" ]] && [[ "$QUIET" != "true" ]]; then
            printf '%s\n' "${rpm_files[@]}" | \
            parallel -j "$MAX_JOBS" --bar extract_rpm_info {} "$staging_dir" 2>&1 | \
            grep -v '^$' > "$results_file" || true
        else
            printf '%s\n' "${rpm_files[@]}" | \
            parallel -j "$MAX_JOBS" extract_rpm_info {} "$staging_dir" 2>/dev/null | \
            grep -v '^$' > "$results_file" || true
        fi
    else
        # Fallback to xargs with manual progress tracking
        if [[ "$SHOW_PROGRESS" == "true" ]] && [[ "$QUIET" != "true" ]]; then
            # Process with progress tracking
            local count=0
            local update_interval=$((total_files / 100))  # Update every 1%
            [[ $update_interval -lt 10 ]] && update_interval=10  # At least every 10 files
            
            printf '%s\0' "${rpm_files[@]}" | \
            xargs -0 -P "$MAX_JOBS" -I {} bash -c '
                result=$(extract_rpm_info "$1" "$2")
                if [[ -n "$result" ]]; then
                    echo "$result"
                fi
                # Update progress counter
                count_file="$3/progress_count"
                (
                    flock 200
                    if [[ -f "$count_file" ]]; then
                        current=$(cat "$count_file")
                    else
                        current=0
                    fi
                    current=$((current + 1))
                    echo "$current" > "$count_file"
                    
                    # Show progress every N files
                    if (( current % '$update_interval' == 0 )) || (( current == '$total_files' )); then
                        show_progress "$current" "'$total_files'" "Processing RPMs" >&2
                    fi
                ) 200>"$count_file.lock"
            ' _ {} "$staging_dir" "$temp_dir" | \
            grep -v '^$' > "$results_file" || true
            
            # Final progress update
            if [[ -f "$temp_dir/progress_count" ]]; then
                final_count=$(cat "$temp_dir/progress_count")
                show_progress "$final_count" "$total_files" "Processing RPMs" >&2
                echo >&2  # New line after progress
            fi
        else
            # No progress tracking
            printf '%s\0' "${rpm_files[@]}" | \
            xargs -0 -P "$MAX_JOBS" -I {} bash -c 'extract_rpm_info "$1" "$2"' _ {} "$staging_dir" | \
            grep -v '^$' > "$results_file" || true
        fi
    fi
    
    echo "$results_file"
}

# Analyze for duplicates and anomalies
analyze_duplicates() {
    local results_file="$1"
    local temp_dir="$2"
    
    log_info "Phase 3: Analyzing for duplicate packages and checksum anomalies..."
    
    # Group by package name and normalized path
    local groups_file="$temp_dir/groups.txt"
    
    # Sort by package_name|normalized_path, then group
    sort -t'|' -k2,3 "$results_file" > "$temp_dir/sorted_results.txt"
    
    # Find groups with multiple instances
    awk -F'|' '
    {
        key = $2 "|" $3  # package_name|normalized_path
        checksums[key] = checksums[key] $1 "|"
        paths[key] = paths[key] $4 "|"
        counts[key]++
    }
    END {
        for (key in counts) {
            if (counts[key] > 1) {
                print key "|" counts[key] "|" checksums[key] "|" paths[key]
            }
        }
    }' "$temp_dir/sorted_results.txt" > "$groups_file"
    
    # Analyze each group for anomalies
    local anomalies_file="$temp_dir/anomalies.txt"
    > "$anomalies_file"  # Clear file
    
    local total_groups=0
    local anomaly_groups=0
    
    while IFS='|' read -r package_name normalized_path count checksums_str paths_str; do
        ((total_groups++))
        
        # Split checksums and check for uniqueness
        IFS='|' read -ra checksums_array <<< "$checksums_str"
        IFS='|' read -ra paths_array <<< "$paths_str"
        
        # Remove empty elements
        local unique_checksums=()
        local unique_paths=()
        for i in "${!checksums_array[@]}"; do
            if [[ -n "${checksums_array[i]}" ]]; then
                unique_checksums+=("${checksums_array[i]}")
                unique_paths+=("${paths_array[i]}")
            fi
        done
        
        # Check if all checksums are the same
        local first_checksum="${unique_checksums[0]}"
        local has_anomaly=false
        
        for checksum in "${unique_checksums[@]}"; do
            if [[ "$checksum" != "$first_checksum" ]]; then
                has_anomaly=true
                break
            fi
        done
        
        if [[ "$has_anomaly" == "true" ]]; then
            ((anomaly_groups++))
            # Save anomaly details
            echo "$package_name|$normalized_path|${#unique_checksums[@]}" >> "$anomalies_file"
            for i in "${!unique_checksums[@]}"; do
                echo "  ${unique_checksums[i]}|${unique_paths[i]}" >> "$anomalies_file"
            done
        fi
        
    done < "$groups_file"
    
    log_info "Found $total_groups groups with duplicate packages"
    
    if [[ $anomaly_groups -eq 0 ]]; then
        log_info "Analysis complete: No anomalies found"
        echo -e "${GREEN}✓ No checksum anomalies found${NC}"
        echo "Analyzed $total_groups package groups - all duplicates have matching checksums"
        return 0
    else
        log_info "Analysis complete: $anomaly_groups anomalies found"
        echo "$anomalies_file"
        return 1
    fi
}

# Output results in different formats
output_results() {
    local anomalies_file="$1"
    local format="$2"
    
    if [[ ! -f "$anomalies_file" ]]; then
        return 0
    fi
    
    case "$format" in
        "json")
            output_json "$anomalies_file"
            ;;
        "csv")
            output_csv "$anomalies_file"
            ;;
        *)
            output_text "$anomalies_file"
            ;;
    esac
}

output_text() {
    local anomalies_file="$1"
    
    echo -e "\n${RED}⚠️  Checksum Anomalies Found:${NC}"
    
    local current_package=""
    while IFS='|' read -r line; do
        if [[ "$line" =~ ^[[:space:]]*([0-9a-f]{64})\|(.+)$ ]]; then
            # Checksum line
            local checksum="${BASH_REMATCH[1]}"
            local file_path="${BASH_REMATCH[2]}"
            echo "    Checksum: $checksum"
            echo "    File: $file_path"
        else
            # Package header line
            IFS='|' read -r package_name normalized_path count <<< "$line"
            echo -e "\n${YELLOW}Package:${NC} $package_name"
            echo -e "${YELLOW}Location:${NC} $normalized_path"
            echo -e "${YELLOW}Conflicting instances:${NC} $count"
        fi
    done < "$anomalies_file"
}

output_json() {
    local anomalies_file="$1"
    
    echo "{"
    echo '  "anomalies": ['
    
    local first_entry=true
    local current_package=""
    local current_location=""
    local current_files=()
    
    while IFS='|' read -r line; do
        if [[ "$line" =~ ^[[:space:]]*([0-9a-f]{64})\|(.+)$ ]]; then
            # Checksum line
            local checksum="${BASH_REMATCH[1]}"
            local file_path="${BASH_REMATCH[2]}"
            current_files+=("{\"checksum\": \"$checksum\", \"file_path\": \"$file_path\"}")
        else
            # Package header line - output previous package if exists
            if [[ -n "$current_package" ]]; then
                if [[ "$first_entry" != "true" ]]; then
                    echo ","
                fi
                echo "    {"
                echo "      \"package_name\": \"$current_package\","
                echo "      \"tree_location\": \"$current_location\","
                echo "      \"conflicting_files\": ["
                printf "        %s" "${current_files[0]}"
                for ((i=1; i<${#current_files[@]}; i++)); do
                    printf ",\n        %s" "${current_files[i]}"
                done
                echo ""
                echo "      ]"
                echo -n "    }"
                first_entry=false
            fi
            
            # Start new package
            IFS='|' read -r package_name normalized_path count <<< "$line"
            current_package="$package_name"
            current_location="$normalized_path"
            current_files=()
        fi
    done < "$anomalies_file"
    
    # Output last package
    if [[ -n "$current_package" ]]; then
        if [[ "$first_entry" != "true" ]]; then
            echo ","
        fi
        echo "    {"
        echo "      \"package_name\": \"$current_package\","
        echo "      \"tree_location\": \"$current_location\","
        echo "      \"conflicting_files\": ["
        printf "        %s" "${current_files[0]}"
        for ((i=1; i<${#current_files[@]}; i++)); do
            printf ",\n        %s" "${current_files[i]}"
        done
        echo ""
        echo "      ]"
        echo "    }"
    fi
    
    echo ""
    echo "  ]"
    echo "}"
}

output_csv() {
    local anomalies_file="$1"
    
    echo "package_name,tree_location,file_path,checksum"
    
    local current_package=""
    local current_location=""
    
    while IFS='|' read -r line; do
        if [[ "$line" =~ ^[[:space:]]*([0-9a-f]{64})\|(.+)$ ]]; then
            # Checksum line
            local checksum="${BASH_REMATCH[1]}"
            local file_path="${BASH_REMATCH[2]}"
            echo "\"$current_package\",\"$current_location\",\"$file_path\",\"$checksum\""
        else
            # Package header line
            IFS='|' read -r package_name normalized_path count <<< "$line"
            current_package="$package_name"
            current_location="$normalized_path"
        fi
    done < "$anomalies_file"
}

# Main function
main() {
    local staging_path=""
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -q|--quiet)
                QUIET=true
                SHOW_PROGRESS=false
                shift
                ;;
            -j|--jobs)
                MAX_JOBS="$2"
                shift 2
                ;;
            --format)
                OUTPUT_FORMAT="$2"
                shift 2
                ;;
            --no-progress)
                SHOW_PROGRESS=false
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
            *)
                staging_path="$1"
                shift
                ;;
        esac
    done
    
    # Validate jobs parameter
    if ! [[ "$MAX_JOBS" =~ ^[0-9]+$ ]] || [[ "$MAX_JOBS" -lt 1 ]]; then
        log_error "Invalid number of jobs: $MAX_JOBS"
        exit 1
    fi
    
    # Validate output format
    case "$OUTPUT_FORMAT" in
        text|json|csv)
            ;;
        *)
            log_error "Invalid output format: $OUTPUT_FORMAT. Must be text, json, or csv."
            exit 1
            ;;
    esac
    
    # Determine staging directory
    local staging_dir
    staging_dir=$(determine_staging_dir "$staging_path")
    log_info "Found latest staging directory: $(basename "$staging_dir")"
    log_info "Analyzing staging directory: $staging_dir"
    log_info "Using $MAX_JOBS parallel workers for RPM processing"
    
    # Create temporary directory
    local temp_dir
    temp_dir=$(mktemp -d)
    trap "rm -rf '$temp_dir'" EXIT
    
    # Start timing
    local start_time
    start_time=$(date +%s)
    
    # Process RPMs and analyze
    local results_file
    results_file=$(process_rpms_parallel "$staging_dir" "$temp_dir")
    
    local anomalies_file
    anomalies_file=$(analyze_duplicates "$results_file" "$temp_dir")
    
    # Calculate timing
    local end_time
    end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Total execution time: ${duration}s"
    fi
    
    # Output results
    if [[ -n "$anomalies_file" ]] && [[ -f "$anomalies_file" ]]; then
        output_results "$anomalies_file" "$OUTPUT_FORMAT"
        exit 1
    else
        exit 0
    fi
}

# Run main function
main "$@"
