# Fix CMake finding native libraries instead of target libraries
# ROS2 interface packages have their dependencies in both native and target sysroots.
# We need to force the target versions for linking.

# Add target message dependencies explicitly
DEPENDS:append = " service-msgs builtin-interfaces rosidl-runtime-c rcutils"

# Remove native sysroot from search paths during linking
EXTRA_OECMAKE:append:class-target = " \
    -DCMAKE_FIND_ROOT_PATH='${STAGING_DIR_HOST}' \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
"
