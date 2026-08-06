# cmake-native's bundled cmcurl probes for libidn2 with check_library_exists,
# which searches the default linker path rather than recipe-sysroot-native. On a
# build host that ships libidn2 and its header in the base system the probe
# succeeds and -lidn2 lands on five link lines, cmake's own among them - but
# nothing stages libidn2 into the native sysroot, so RUNPATH never covers it and
# the freshly built binary cannot start under the uninative loader:
#
#   bin/cmake: error while loading shared libraries: libidn2.so.0
#
# do_install then dies with exit 127, reported only as "oe_runmake failed" some
# forty lines below the real error. Whether cmake links libidn2 at all depends on
# what the builder happens to have installed, so seeding the probe keeps the
# result the same across build machines.
#
# Seeding the HAVE_ results is what actually works here. USE_LIBIDN2 is not a
# lever at all: cmcurl sets it as a normal variable (CMakeLists.txt:101), which
# shadows any -D on the command line - the same shape oe-core carries
# 0001-CMakeLists.txt-disable-USE_NGHTTP2.patch for on the adjacent
# set(USE_NGHTTP2 ON). check_library_exists also runs whether or not the feature
# switch is set, so even a switch that took would leave HAVE_LIBIDN2=1 in the
# cache and -lidn2 on the link line.
#
# Filename pinned to 3.28.% on purpose. cmake 4.3.1 detects with
# find_package(Libidn2 QUIET) instead (Utilities/cmcurl/CMakeLists.txt:1408) and
# unconditionally sets HAVE_IDN2_H and HAVE_LIBIDN2 to OFF as normal variables
# first (:1405-1406), so these seeds are shadowed there exactly as -DUSE_LIBIDN2
# is here. find_package also honours cmake's find-root confinement, which
# check_library_exists bypasses by asking the linker directly - that is the
# difference that closes the host leak at 4.3.x, and CMAKE_DISABLE_FIND_PACKAGE_Libidn2
# (a stock cmake variable, not an oe-core knob) is the lever if it ever reopens.
# A _% filename would keep matching after the bump and leave an append that
# parses, sets nothing readable, warns about nothing, and looks like it is still
# preventing the bug. Pinned, the same bump is a dangling-append error instead.
CMAKE_EXTRACONF += "-DHAVE_LIBIDN2=0 -DHAVE_IDN2_H=0"
