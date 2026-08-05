# nativesdk-ethos-u-vela RDEPENDS on the flatbuffers Python binding, so it needs
# a nativesdk variant too. (The flatbuffers C++ lib already nativesdk-extends.)
BBCLASSEXTEND += "nativesdk"
