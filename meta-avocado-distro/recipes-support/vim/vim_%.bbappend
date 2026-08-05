# vim-native's configure cannot run its own test programs on a host whose
# libnsl pulls in Kerberos, and fails on the first run-test it treats as fatal:
#
#   checking uint32_t is 32 bits... configure: error: WRONG!
#
# config.log shows the test compiling cleanly and then dying at exec:
#
#   ./conftest: error while loading shared libraries: libgssapi_krb5.so.2
#   configure: program exited with status 127
#
# libnsl is not staged into recipe-sysroot-native, so the -lnsl that
# ac_cv_lib_nsl_gethostbyname=yes puts on the link line resolves against the
# host's copy, and on Arch that drags in libtirpc -> libgssapi_krb5 -> libkrb5.
# None of those reach the native sysroot, and the uninative loader searches
# RUNPATH and its own sysroot but never the host's default paths, so the binary
# links but cannot start.
#
# The damage is wider than the one fatal check: every earlier run-test failed
# the same way and was silently recorded as zero - "checking size of time_t...
# 0", "size of off_t... 0" - so the configure that precedes the error is
# already wrong, not merely incomplete.
#
# Declining the library is the fix rather than a workaround. gethostbyname has
# lived in glibc proper since the libnsl split, so vim gets the same symbol
# with one less dependency, and the recipe already steers configure through
# ac_cv_* cache variables (vim.inc:78, :91) so this matches how it is done.
EXTRA_OECONF:append:class-native = " ac_cv_lib_nsl_gethostbyname=no"
