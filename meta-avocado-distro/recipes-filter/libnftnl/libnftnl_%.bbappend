# Required for nativesdk-docker / nativesdk-containerd cgo builds:
# meta-virtualization wrynose's docker.inc adds `libnftnl` to DEPENDS
# (moby v2 has libnetwork cgo bindings that need libnftables / libnftnl
# headers and pkg-config). Upstream meta-networking's libnftnl is
# target-only (no BBCLASSEXTEND), so we add nativesdk here.
BBCLASSEXTEND = "nativesdk"
