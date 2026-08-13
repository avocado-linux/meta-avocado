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
# lever at all: cmcurl sets it as a normal variable
# (Utilities/cmcurl/CMakeLists.txt:90), which shadows any -D on the command line
# - the same shape oe-core carries 0001-CMakeLists.txt-disable-USE_NGHTTP2.patch
# for on the adjacent set(USE_NGHTTP2 ON) one line below. check_library_exists
# also runs whether or not the feature switch is set, so even a switch that took
# would leave HAVE_LIBIDN2=1 in the cache and -lidn2 on the link line.
#
# Filename pinned to 3.28.% because the seeds reach nothing on 4.3.x, not
# because 4.3.x is immune - it is not. Two separate reasons, and only the first
# is about this append:
#
#   CMAKE_EXTRACONF does not exist in cmake-native 4.3.1, which passes
#   `-- ${EXTRA_OECMAKE}` to bootstrap instead (cmake-native_4.3.1.bb:46). A _%
#   filename would keep matching after the bump and leave an append that parses,
#   sets nothing any recipe reads, warns about nothing, and looks like it is
#   still preventing the bug. Pinned, the same bump is a dangling-append error.
#
#   4.3.x has the same leak by a different route, and oe-core already fixes it.
#   cmcurl there calls find_package(Libidn2), which upstream measured as
#   detecting the host library during configure - the compile then fails with
#   `fatal error: idn2.h: No such file or directory`. oe-core's fix is
#   -DCMAKE_DISABLE_FIND_PACKAGE_Libidn2=ON in cmake-native_4.3.1.bb's
#   EXTRA_OECMAKE (commit 854e940580d, on the wrynose branch). So the wrynose
#   bump needs nothing from this layer, provided the oe-core it pins carries
#   that commit - which is the thing to check at bump time rather than assume.
#
# LAYERSERIES_COMPAT_meta-avocado is "scarthgap" alone today, so the pin cannot
# strand a build that is already happening; it comes due when compat widens.
CMAKE_EXTRACONF += "-DHAVE_LIBIDN2=0 -DHAVE_IDN2_H=0"
