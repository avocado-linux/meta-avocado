SUMMARY = "Ganesha userspace NFSv3/v4/v4.1/9P fileserver"
HOMEPAGE = "https://github.com/nfs-ganesha/nfs-ganesha"
LICENSE = "LGPL-3.0-only"
LIC_FILES_CHKSUM = "\
    file://src/LICENSE.txt;md5=3000208d539ec061b899bce1d9ce9404 \
"

PV = "6.5"

SRC_URI = " \
  git://github.com/nfs-ganesha/nfs-ganesha.git;protocol=https;branch=V6-stable \
  file://0001-fix-uninitialized-warnings.patch \
  file://0002-fix-functions-with-no-return-value.patch \
  file://0003-fix-discarded-const-qualifier.patch \
"
SRCREV = "952fb93373a6f9f9e187bf9bc35c41a9fc25efa6"

DEPENDS = "flex-native bison-native util-linux libunwind ntirpc"
RDEPENDS:${PN} = "netbase ntirpc rpcbind"
inherit cmake pkgconfig systemd

# enable building -native and -nativesdk variants
BBCLASSEXTEND = "native nativesdk"

# select optional features (toggle with PACKAGECONFIG)
PACKAGECONFIG[dbus]     = "-DUSE_DBUS=ON,-DUSE_DBUS=OFF,dbus"
PACKAGECONFIG[nfsidmap] = "-DUSE_NFSIDMAP=ON,-DUSE_NFSIDMAP=OFF,nfs-utils"
PACKAGECONFIG[nfsv3]    = "-DUSE_NFS3=ON,-DUSE_NFS3=OFF"
PACKAGECONFIG[winbind]  = "-DUSE_SMB=ON,-DUSE_SMB=OFF,samba"
PACKAGECONFIG[lttng]    = "-DUSE_LTTNG=ON -DUSE_LTTNG_NTIRPC=ON,-DUSE_LTTNG=OFF -DUSE_LTTNG_NTIRPC=OFF,lttng-ust liburcu"
PACKAGECONFIG[acl]      = "-DUSE_ACL_MAPPING=ON,-DUSE_ACL_MAPPING=OFF,acl"
PACKAGECONFIG[gss]     = "-DUSE_GSS=ON,-DUSE_GSS=OFF,gss-ntlmssp"
PACKAGECONFIG[rdma]    = "-DUSE_RPC_RDMA=ON,-DUSE_RPC_RDMA=OFF,rdma-core"

PACKAGECONFIG ?= "acl dbus"

# The nativesdk build is a host NFS tool for dev-VM provisioning and does not need
# ganesha's D-Bus management interface; without this it fails do_compile on a
# missing dbus/dbus.h in the nativesdk sysroot.
PACKAGECONFIG:remove:class-nativesdk = "dbus"

OECMAKE_SOURCEPATH = "${S}/src"

EXTRA_OECMAKE = "\
    -DLIB_INSTALL_DIR=${libdir} \
    -DCMAKE_INSTALL_LIBDIR=${libdir} \
    -DUSE_SYSTEM_NTIRPC=ON \
    -DUSE_GSS=OFF \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DUSE_FSAL_GLUSTER=OFF \
"

# install the systemd unit
SYSTEMD_SERVICE_${PN} = "ganesha.nfsd.service"

# Package the configuration files and state directories
FILES:${PN} += "${sysconfdir}/ganesha/*"
FILES:${PN}:append:class-nativesdk = " ${prefix}/var/lib/nfs/ganesha"

do_install:append:class-nativesdk() {
    # For nativesdk, move config files from ${D}${prefix}/etc to ${D}${sysconfdir}
    if [ -d "${D}${prefix}/etc" ]; then
        mkdir -p "${D}${sysconfdir}"
        cp -r "${D}${prefix}/etc"/* "${D}${sysconfdir}/"
        rm -rf "${D}${prefix}/etc"
    fi

    # Create the ganesha state directories needed for NFSv4 recovery
    # These are required at runtime for client recovery tracking
    install -d "${D}${prefix}/var/lib/nfs/ganesha"
}

do_compile:append() {
    for f in $(find ${B} -type f \( -name 'conf_*.c' -o -name 'conf_*.h' \)); do
        sed -i -e "s|${WORKDIR}||g" -e "s|${TMPDIR}||g" "$f"
    done
}
