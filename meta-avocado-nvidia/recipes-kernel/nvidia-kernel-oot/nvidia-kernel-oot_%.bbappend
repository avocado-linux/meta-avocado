# Extend the default -src package with Makefiles and build configuration files
# These help understand which source files and headers build which modules
# The default -src package from splitdebug only includes .c/.h files referenced in debug info
#
# Path for debug sources (used by splitdebug class)
DEBUG_SRC_PATH = "/usr/src/debug/${BPN}/${EXTENDPE}${PV}"

# Append build system files to the -src package
# These files document the module build structure and are useful for SDK users
FILES:${PN}-src += "\
    ${DEBUG_SRC_PATH}/**/Makefile \
    ${DEBUG_SRC_PATH}/**/Makefile.* \
    ${DEBUG_SRC_PATH}/**/*.mk \
    ${DEBUG_SRC_PATH}/**/*.tmk \
    ${DEBUG_SRC_PATH}/**/Kconfig* \
    ${DEBUG_SRC_PATH}/**/*.sources \
    ${DEBUG_SRC_PATH}/**/*.configs \
    ${DEBUG_SRC_PATH}/**/*.export \
"

do_install:append() {
    # Install Makefiles and build system files to the debug source directory
    # This allows SDK users to understand how modules are built
    install -d ${D}${DEBUG_SRC_PATH}
    (
        cd ${S}
        # Install all Makefiles and Makefile.* files (Makefile.sources, Makefile.configs, etc.)
        find . -name "Makefile" -o -name "Makefile.*" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install Kconfig files (kernel configuration)
        find . -name "Kconfig*" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .mk files (make include files like utils.mk, version.mk)
        find . -name "*.mk" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .tmk files (Tegra make files for nvethernetrm)
        find . -name "*.tmk" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .sources files (source file lists like Makefile.sources)
        find . -name "*.sources" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .configs files (build configuration files)
        find . -name "*.configs" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done

        # Install .export files (symbol export definitions)
        find . -name "*.export" | while read -r file; do
            install -D -m 0644 "$file" "${D}${DEBUG_SRC_PATH}/$file"
        done
    )
}
