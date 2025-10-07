# Fix CMake not finding rosidl_core_generators
# The build tools need to be found from the native sysroot

DEPENDS:append = " rosidl-core-generators-native"

# Ensure CMake can find packages from both native and target sysroots
EXTRA_OECMAKE:append = " \
    -DCMAKE_PREFIX_PATH='${STAGING_DIR_HOST}${ros_prefix};${STAGING_DIR_HOST}${prefix};${STAGING_DIR_NATIVE}${ros_prefix};${STAGING_DIR_NATIVE}${prefix}' \
"


