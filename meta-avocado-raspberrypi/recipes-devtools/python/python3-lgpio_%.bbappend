# lgpio.py imports socket at module level to talk to rgpiod, and socket lives
# in python3-io rather than python3-core, so the recipe's own dependency on
# python3-core leaves `import lgpio` failing on an image with a minimal Python.
RDEPENDS:${PN} += "python3-io"
