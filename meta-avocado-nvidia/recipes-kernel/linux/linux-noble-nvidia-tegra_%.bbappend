# L4T 6.8 kernel, built in the jetson-l4t multiconfig. Everything is in the
# shared .incs so the PREEMPT_RT sibling
# (linux-noble-nvidia-tegra-rt_%.bbappend, built in the jetson-l4t-rt
# multiconfig) gets the identical treatment -- a `require` does not carry
# bbappends across PNs.
require recipes-kernel/linux/avocado-linux-noble-tegra.inc
