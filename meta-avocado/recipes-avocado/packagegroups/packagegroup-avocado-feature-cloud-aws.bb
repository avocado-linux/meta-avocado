DESCRIPTION = "Packagegroup for Avocado AWS cloud feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${AWS_PACKAGES} \
  ${AWS_PACKAGES_64BIT} \
"

# What a device product on AWS runs: Greengrass (the Java nucleus and the C
# Lite one), IoT device clients and SDKs, fleet management and telemetry
# agents, secure tunneling, vehicle data collection, and camera streaming to
# Kinesis Video and WebRTC. Nothing here is enabled at boot: an extension
# installs what it needs and lists the services it runs.
AWS_PACKAGES = " \
  aws-cli-v2 \
  aws-greengrass-component-sdk \
  aws-iot-device-client \
  aws-iot-device-sdk-cpp-v2 \
  aws-iot-device-sdk-python-v2 \
  aws-iot-fleetwise-edge \
  aws-iot-securetunneling-localproxy \
  amazon-kvs-producer-sdk-c \
  amazon-ssm-agent \
  greengrass-lite \
  python3-boto3 \
"

# Greengrass's nucleus RDEPENDS on a JRE, and Amazon Corretto, the CloudWatch
# agent, the Kinesis Video C++ producer and the WebRTC SDK only build for
# aarch64 and x86_64.
AWS_PACKAGES_64BIT = "${@' \
  amazon-cloudwatch-agent \
  amazon-kvs-producer-sdk-cpp \
  amazon-kvs-webrtc-sdk \
  greengrass-bin \
' if d.getVar('TARGET_ARCH') in ('aarch64', 'x86_64') else ''}"
