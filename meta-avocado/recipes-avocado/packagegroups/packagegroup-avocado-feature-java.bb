DESCRIPTION = "Packagegroup for the Avocado java feature"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${JAVA_PACKAGES} \
"

# openjdk-17 RDEPENDs on a JRE/JDK; OpenJDK only builds for aarch64 and
# x86_64. Skip on aarch32 (Cortex-A32 / Cortex-A7 etc.) where TARGET_ARCH
# == "arm".
JAVA_PACKAGES = "${@' \
  openjdk-17-jdk \
  openjdk-17-jre \
' if d.getVar('TARGET_ARCH') in ('aarch64', 'x86_64') else ''}"
