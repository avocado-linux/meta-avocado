#
# Copyright Peridio
#
# SPDX-License-Identifier: MIT
#
# nospdx, plus the runtime task oe-core's copy misses.
#
# oe-core's nospdx.bbclass (meta/classes-recipe/nospdx.bbclass) deletes
# do_create_spdx_runtime. No class defines that task: create-spdx-2.2.bbclass
# registers the runtime one as do_create_runtime_spdx, so the name has its two
# words the wrong way round.
#
# deltask on a name that was never added is silent - no warning, no error, no
# non-zero exit - so a recipe inheriting nospdx still runs do_create_runtime_spdx
# while every other SPDX task is correctly removed. The class looks like it
# worked and the cost is invisible: the task still runs, still writes to
# SPDXRUNTIMEDEPLOY, and still participates in sstate.
#
# The fix lives here rather than in the oe-core fork because the vendor-* forks
# take upstream pin bumps rather than carrying local patches; a layer-level class
# is the part of the tree we own.
#
# This is ADDITIVE rather than a copy of oe-core's class. Shadowing it by name
# would freeze the deltask list at today's contents, so a task oe-core adds to
# nospdx later would silently stop being deleted here. Inheriting it means we
# track whatever oe-core deletes and only add the one it misses.
#
# When oe-core corrects the name upstream, this deltask becomes a no-op rather
# than an error - by the same silence that hid the bug - so this class needs no
# follow-up to stay safe.

inherit nospdx

deltask do_create_runtime_spdx
