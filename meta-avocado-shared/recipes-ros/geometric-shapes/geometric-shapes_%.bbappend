# Copyright (c) 2025
#
# Fix octomap version constraint to accept 1.10.0
# The generated recipe restricts octomap to < 1.10.0, but the system uses 1.10.0

do_configure:prepend() {
    # Relax octomap version constraint from "1.9.7...<1.10.0" to "1.9.7"
    sed -i 's/find_package(octomap 1\.9\.7\.\.\.<1\.10\.0 REQUIRED)/find_package(octomap 1.9.7 REQUIRED)/' ${S}/CMakeLists.txt
}


