# Everything is in the shared .inc so the PREEMPT_RT sibling can have it too.
#
# linux-qcom-rt_6.18.bb is `require linux-qcom_6.18.bb`, but a require does NOT
# carry the required recipe's bbappends -- bbappends are matched on the recipe
# FILENAME being parsed, and linux-qcom-rt_6.18.bb is a different filename with
# a different PN. Without its own bbappend the RT kernel would build with none
# of the avocado cfg fragments, no board dts, and none of the feed classes.
require recipes-kernel/linux/avocado-linux-qcom.inc
