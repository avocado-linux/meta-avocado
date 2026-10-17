# opencv-dev's OpenCVModules.cmake defines imported targets for the sfm module's
# third-party static libraries (opencv.sfm.correspondence, .multiview and
# .numeric) and CMake stops at find_package(OpenCV) when a file an imported
# target names is missing:
#
#   The imported target "opencv.sfm.correspondence" references the file
#   ".../usr/lib/opencv4/3rdparty/libopencv.sfm.correspondence.a" but this file
#   does not exist.
#
# The recipe packages those libraries in -staticdev, and -dev, whose main
# package is empty, requires nothing, so a sysroot with only -dev has the
# config and not the libraries. Make -dev require -staticdev so installing the
# CMake config installs the files it checks for. -staticdev keeps requiring
# -dev, and the two packages are always installed together.
RDEPENDS:${PN}-dev += "${PN}-staticdev"
