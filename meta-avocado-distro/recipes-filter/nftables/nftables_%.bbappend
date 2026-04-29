# Required for nativesdk-docker / nativesdk-containerd cgo builds:
# docker's libnetwork cgo bindings include `libnftables.pc` and the
# nft headers via pkg-config. Upstream meta-networking's nftables
# is target-only, so we add nativesdk here.
BBCLASSEXTEND = "nativesdk"
