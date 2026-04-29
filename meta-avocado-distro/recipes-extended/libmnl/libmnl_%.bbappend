# Transitive dep of nativesdk-{libnftnl,nftables} (both DEPENDS = "libmnl").
# Upstream OE-core libmnl declares `BBCLASSEXTEND = "native"`; we append
# nativesdk to keep target/native unaffected.
BBCLASSEXTEND:append = " nativesdk"
