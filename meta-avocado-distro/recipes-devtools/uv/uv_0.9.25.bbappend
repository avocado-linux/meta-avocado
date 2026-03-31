# Disable LTO fat linking — causes OOM on systems with <64GB RAM
# lto=fat on the final uv binary link requires holding all crate IR in memory
do_compile:prepend() {
    export CARGO_PROFILE_RELEASE_LTO=thin
}
