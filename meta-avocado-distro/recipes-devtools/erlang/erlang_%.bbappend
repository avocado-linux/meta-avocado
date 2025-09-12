inherit parallel-make-highmem

# Remove wx and observer from nativesdk builds by default to avoid OpenGL dependency issues
PACKAGECONFIG:class-nativesdk:remove = "wx"
PACKAGECONFIG:class-nativesdk:remove = "observer"

# Only enable wx/observer if opengl is in DISTRO_FEATURES and we have the required dependencies
PACKAGECONFIG:class-nativesdk:append = "${@bb.utils.contains('DISTRO_FEATURES', 'opengl', 'wx observer', '', d)}"

# Skip configure-unsafe QA check for nativesdk builds since wx configure checks host paths
INSANE_SKIP += " configure-unsafe buildpaths"

