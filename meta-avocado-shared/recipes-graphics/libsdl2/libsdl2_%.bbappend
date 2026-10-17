# libsdl2-dev's SDL2Config.cmake includes the static, main and test target files
# when they exist, and each names a static library that lives in -staticdev
# (libSDL2.a, libSDL2main.a, libSDL2_test.a). A sysroot with only -dev therefore
# has the target files but not the libraries, and find_package(SDL2) fails:
#
#   The imported target "SDL2::SDL2-static" references the file
#   ".../usr/lib/libSDL2.a" but this file does not exist.
#
# Ship each target file with the library it describes. SDL2Config.cmake guards
# every include with EXISTS, so without -staticdev it skips them and uses the
# shared SDL2::SDL2 target; a project that installs -staticdev too still gets all
# of them. -staticdev already requires -dev, so the files are never present
# without the config that includes them.
#
# PACKAGES lists -staticdev before -dev, so these globs are claimed first.
FILES:${PN}-staticdev += " \
    ${libdir}/cmake/SDL2/SDL2staticTargets*.cmake \
    ${libdir}/cmake/SDL2/SDL2mainTargets*.cmake \
    ${libdir}/cmake/SDL2/SDL2testTargets*.cmake \
"
