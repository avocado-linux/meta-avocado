# Ship libeigen's (empty) main package, as meta-ros does. Eigen is a template
# library, so meta-oe's recipe puts everything in -dev and writes no libeigen
# package, but ROS recipes RDEPEND on libeigen by name.
#
# This has to match meta-ros-common's libeigen_%.bbappend exactly. The
# ros2-jazzy add-on multiconfig keeps that bbappend, and if the base set
# anything different, libeigen would build twice with different signatures:
# the add-on would carry its own libeigen-dev and -dbg under the base's names
# but a different release, which the add-on stage refuses as shadowing (seen
# on raspberrypi5, which ships libeigen through onnxruntime). With the same
# value in both, the add-on reuses the base build and its copies are identical.
ALLOW_EMPTY:${PN} = "1"
