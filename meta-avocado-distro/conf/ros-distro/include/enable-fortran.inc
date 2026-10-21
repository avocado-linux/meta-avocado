# Replaces meta-ros-common's enable-fortran.inc, which its layer.conf requires
# for every multiconfig: meta-avocado-distro is ahead of meta-ros in BBPATH, so
# this copy is the one found.
#
# Avocado enables Fortran in kas/base.yml for every build already (gcc-cross,
# gcc-runtime, HOSTTOOLS gfortran). meta-ros's copy appends the same settings a
# second time, which changes gcc-runtime's signature, and so the base feed's,
# just because the ROS layers are present. Empty on purpose.
