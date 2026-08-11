DESCRIPTION = "Packagegroup for Avocado AWS cloud feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${AWS_PACKAGES} \
"

# AWS Greengrass and openjdk-17 RDEPEND on a JRE/JDK; Amazon Corretto and
# OpenJDK only build for aarch64 and x86_64. Skip on aarch32 (Cortex-A32 /
# Cortex-A7 etc.) where TARGET_ARCH == "arm".
AWS_PACKAGES = "${@' \
  greengrass-bin \
  aws-iot-device-client \
' if d.getVar('TARGET_ARCH') in ('aarch64', 'x86_64') else ''}"
