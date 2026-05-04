# Avocado provisioning scripts shell out to dfu-util inside the SDK container
# (currently for stm32mp2 USB-DFU bring-up). The upstream meta-oe recipe
# doesn't BBCLASSEXTEND nativesdk by default, so nativesdk-dfu-util doesn't
# exist without this.
BBCLASSEXTEND += "nativesdk"
