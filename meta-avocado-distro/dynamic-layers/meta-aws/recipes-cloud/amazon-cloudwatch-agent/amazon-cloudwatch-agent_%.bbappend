# The agent builds through its own Makefile, so go-mod.bbclass's -modcacherw
# (on GOBUILDFLAGS) never reaches go, the module cache is left read-only, and
# rm_work cannot delete it. GOFLAGS reaches every go command the Makefile runs.
export GOFLAGS = "-modcacherw"
