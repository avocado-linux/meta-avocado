# python3-scipy-native is a build dependency of the target recipe, but its
# Fortran sanity check runs a binary built by the build host's gfortran, which
# cannot load the host's libgfortran.so.5 under uninative:
#
#   ERROR: Executables created by fortran compiler gfortran are not runnable.
#
# The target build does not need it.
DEPENDS:remove:class-target = "python3-scipy-native"

# The recipe exports F77 and F90 as the bare cross gfortran, and FC is the same.
# Without --sysroot gfortran cannot find libgfortran.spec, which is in the recipe
# sysroot, and meson stops with
#
#   ERROR: Compiler aarch64-avocado-linux-gfortran cannot compile programs.
#
# Give the Fortran compiler the options CC gets.
FC:class-target = "${TARGET_PREFIX}gfortran ${HOST_CC_ARCH}${TOOLCHAIN_OPTIONS}"
F77:class-target = "${TARGET_PREFIX}gfortran ${HOST_CC_ARCH}${TOOLCHAIN_OPTIONS}"
F90:class-target = "${TARGET_PREFIX}gfortran ${HOST_CC_ARCH}${TOOLCHAIN_OPTIONS}"
export FC

# The recipe strips the sysroot and prefix-map arguments from __config__.py, but
# not -B<dir>, which a build that links with mold adds for its ld wrappers. The
# directory is under TMPDIR, so the [buildpaths] QA check fails the package.
do_install:append:class-target () {
	sed -i -e 's|, -B[^,"]*||g' ${D}${PYTHON_SITEPACKAGES_DIR}/scipy/__config__.py
	rm -f ${D}${PYTHON_SITEPACKAGES_DIR}/scipy/__pycache__/__config__.*.pyc
}
