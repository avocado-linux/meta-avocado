inherit parallel-make-highmem

# Skip configure-unsafe QA check for nativesdk builds since wx configure checks host paths
INSANE_SKIP += " configure-unsafe buildpaths"

