# Drop meta-qcom's freedreno/turnip backports: oe-core's mesa already has them.
#
# meta-qcom's wrynose mesa.bbappend adds them unconditionally for :qcom, with
# no version guard, so once oe-core's mesa carries a backport, quilt refuses
# it and takes the whole do_patch down. That fails every build that pulls
# graphics (i.e. everything, once kas/feature/complete.yml is stacked), e.g.
# against 26.2.5:
#
#   Patch 0001-freedreno-Add-support-for-A704.patch
#   Hunk #1 FAILED at 693. 1 out of 1 hunk FAILED
#
# Every patch is a Backport, and oe-core's mesa 26.2.5 carries each change:
#   A704 GPUId                  freedreno_devices.py "Adreno (TM) 704"
#   A702 reg_size_vec4 = 64     freedreno_devices.py
#   a608/a612 reg_size_vec4     freedreno_devices.py a6xx_gen1_low_magic_regs
#   UBWC block sizes for NV12   fdl/fd6_layout.c plane 0/1 cases
#   small-renderpass autotune   vulkan/tu_autotune.cc (now the TUNE_SMALL flag)
# meta-qcom master already dropped the A704 one for the same reason
# (3b6c4af8); its wrynose branch has not.
#
# Removed here rather than in the vendored layer: the real fix is a version
# guard upstream in meta-qcom, since the mismatch hits anyone pairing its
# wrynose branch with a newer oe-core. Revisit on the next meta-qcom repin --
# a patch meta-qcom drops makes its line here a no-op, and it can go.
SRC_URI:remove = " \
    file://0001-freedreno-Add-support-for-A704.patch \
    file://0001-freedreno-Increase-reg_size_vec4-for-A702.patch \
    file://0001-freedreno-layout-tu-Fix-UBWC-block-sizes-for-PIPE_FO.patch \
    file://0001-freedreno-Modify-reg_size_vec4-for-a608-and-a612-to-32.patch \
    file://0001-tu-autotune-Disable-autotuning-for-small-renderpasse.patch \
"
