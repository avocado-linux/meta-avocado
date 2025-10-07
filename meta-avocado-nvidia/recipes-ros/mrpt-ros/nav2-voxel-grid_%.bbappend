inherit cuda

# Work around shadow warnings in rclcpp headers
# The rclcpp headers have parameter shadowing issues that trigger -Werror=shadow
# This is an upstream issue in ROS2 Jazzy rclcpp headers, not in nav2-voxel-grid code

# Append -Wno-shadow to override the -Wshadow set by CMakeLists.txt
CXXFLAGS:append = " -Wno-shadow"
