# Copyright (c) 2025
#
# Fix for UNPACKDIR variable not being expanded correctly.
# Replace UNPACKDIR with WORKDIR for compatibility.

# Fix "Unknown" license for SPDX - OpenNI2 is Apache-2.0
LICENSE = "Apache-2.0"

do_install () {
  install -d ${D}${libdir}
  install -m 0755 Bin/*-Release/libOpenNI2.so.* ${D}${libdir}
  ln -sf libOpenNI2.so.0 ${D}${libdir}/libOpenNI2.so

  install -d ${D}${libdir}/OpenNI2/Drivers
  install -m 0755 Bin/*-Release/OpenNI2/Drivers/libDummyDevice.so.0 ${D}${libdir}/OpenNI2/Drivers/
  ln -sf  libDummyDevice.so.0 ${D}${libdir}/OpenNI2/Drivers/libDummyDevice.so
  install -m 0755 Bin/*-Release/OpenNI2/Drivers/libOniFile.so.0 ${D}${libdir}/OpenNI2/Drivers/
  ln -sf  libOniFile.so.0 ${D}${libdir}/OpenNI2/Drivers/libOniFile.so
  install -m 0755 Bin/*-Release/OpenNI2/Drivers/libPS1080.so.0 ${D}${libdir}/OpenNI2/Drivers/
  ln -sf  libPS1080.so.0 ${D}${libdir}/OpenNI2/Drivers/libPS1080.so
  install -m 0755 Bin/*-Release/OpenNI2/Drivers/libPSLink.so.0 ${D}${libdir}/OpenNI2/Drivers/
  ln -sf  libPSLink.so.0 ${D}${libdir}/OpenNI2/Drivers/libPSLink.so

  install -d ${D}${sysconfdir}/openni2/
  install -m 0600 Config/*.ini ${D}${sysconfdir}/openni2/

  install -d ${D}${includedir}/openni2/Driver/
  install -m 0600 Include/Driver/* ${D}${includedir}/openni2/Driver
  install -d ${D}${includedir}/openni2/Linux-Arm
  install -m 0600 Include/Linux-Arm/* ${D}${includedir}/openni2/Linux-Arm
  install -d ${D}${includedir}/openni2/Linux-generic
  install -m 0600 Include/Linux-generic/* ${D}${includedir}/openni2/Linux-generic
  install -d ${D}${includedir}/openni2/Linux-x86
  install -m 0600 Include/Linux-x86/* ${D}${includedir}/openni2/Linux-x86
  install -m 0600 Include/*.h ${D}${includedir}/openni2/

  install -d ${D}${datadir}/pkgconfig
  install -m 0600 ${WORKDIR}/libopenni2.pc ${D}${datadir}/pkgconfig

  install -d ${D}${bindir}
  install -m 0755 Bin/*-Release/NiViewer ${D}${bindir}
}

