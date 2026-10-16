# numba/core/codegen.py imports html, which lives in python3-html and is not
# declared. A minimal Python image without that package fails at
# `import numba`, which only a test on such an image shows.
RDEPENDS:${PN} += "python3-html"
