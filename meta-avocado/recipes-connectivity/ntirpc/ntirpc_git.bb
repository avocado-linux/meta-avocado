SUMMARY = "Transport-Independent RPC (TI-RPC) library for NFS-Ganesha"
HOMEPAGE = "https://github.com/nfs-ganesha/ntirpc"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://COPYING;md5=f835cce8852481e4b2bbbdd23b5e47f3"

SRC_URI = "git://github.com/nfs-ganesha/ntirpc.git;branch=next;protocol=https"
SRCREV = "d2b7209f82fac44fe95731ce98740f793e9e98a0"

S = "${WORKDIR}/git"

inherit cmake pkgconfig

DEPENDS += "libtirpc libnsl2 liburcu"

EXTRA_OECMAKE += "\
    -DLIB_INSTALL_DIR=${libdir} \
    -DCMAKE_INSTALL_LIBDIR=${libdir} \
    -DNTIRPC_USE_NTIRPC_INIT=ON \
"

# Package the library files properly
FILES:${PN} += "${libdir}/libntirpc.so.*"
FILES:${PN}-dev += "${libdir}/libntirpc.so ${libdir}/pkgconfig/libntirpc.pc"

BBCLASSEXTEND = "native nativesdk"
