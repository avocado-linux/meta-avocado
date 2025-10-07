# Disable ptests for lapack
# The do_install_ptest tries to copy BLAS and LAPACKE directories
# that only exist when cblas and lapacke PACKAGECONFIG options are enabled
PTEST_ENABLED = "0"


