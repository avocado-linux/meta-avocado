# Transitive dep of nativesdk-nftables. Upstream meta-oe jansson
# declares `BBCLASSEXTEND = "native"`; we append nativesdk to keep
# target/native unaffected.
BBCLASSEXTEND:append = " nativesdk"
