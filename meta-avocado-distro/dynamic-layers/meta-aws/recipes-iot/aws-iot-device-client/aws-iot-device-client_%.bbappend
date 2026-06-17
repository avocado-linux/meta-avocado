# OE's git fetcher checks out SRCREV without tag refs, so git describe (used by
# CMakeLists.txt.versioning) fails. Create a tag before cmake runs.
# Use git -C to avoid changing cwd away from ${B} (cmake needs to run there).
do_configure:prepend() {
    git -C ${S} tag -f "v${PV}" HEAD
}
