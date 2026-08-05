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
# Seed the HAVE_ results rather than using CMAKE_DISABLE_FIND_PACKAGE_Libidn2
# (oe-core's fix for 4.3.x): that knob disables a find_package(Libidn2) call the
# bundled cmcurl only grew in the 3.28.x -> 4.3.x upgrade, so on 3.28.x it has
# nothing to disable. USE_LIBIDN2 alone is not enough either - check_library_exists
# runs whether or not the feature switch is set, leaving HAVE_LIBIDN2=1 in the
# cache and -lidn2 on the link line.
#
# Drop this append when cmake moves to 4.3.x or later: that version carries the
# upstream fix, and renamed CMAKE_EXTRACONF to EXTRA_OECMAKE.
CMAKE_EXTRACONF += "-DUSE_LIBIDN2=0 -DHAVE_LIBIDN2=0 -DHAVE_IDN2_H=0"
