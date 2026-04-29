# Wrynose's stricter `buildpaths` QA check flags references to TMPDIR
# embedded in libgfortran's debug binary
# (`/usr/lib/.debug/libgfortran.so.5.0.0`). The build path leaks via the
# fortran compiler's runtime metadata; the debug-info file-prefix-map
# rewrites OE-core applies to most libs aren't enough to scrub all of
# fortran's gunk. Skip the QA check for the -dbg subpackage.
#
# We force Fortran globally (kas/base.yml: FORTRAN:forcevariable
# = ",fortran"), so libgfortran is part of every build.

INSANE_SKIP:${PN}-dbg += "buildpaths"
