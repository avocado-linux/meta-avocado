# Same incomplete-upstream-fix as triton-backend: pytorch ships a static lib in
# ${PN}-staticdev (mimalloc-2.2) whose archive embeds TMPDIR buildpaths, and the
# upstream recipe skips the buildpaths QA on ${PN} and ${PN}-dev but not
# ${PN}-staticdev. avocado treats buildpaths as fatal, so extend the skip.
# TODO: upstream alongside the existing INSANE_SKIP:${PN}-dev.
INSANE_SKIP:${PN}-staticdev += "buildpaths"
