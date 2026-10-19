# pyarrow/compat.pxi imports pickle, which lives in python3-pickle and is not
# declared. A minimal Python image fails at `import pyarrow` with
# ModuleNotFoundError: No module named 'pickle'.
RDEPENDS:${PN} += "python3-pickle"
