# SPDX-License-Identifier: Apache-2.0
"""Name the source a local build came from, for DISTRO_VERSION and BUILD_ID.

A release build is handed both values by the pipeline. A local build gets them
from here: the number of commits behind HEAD, so two local builds order the way
the history does, then the revision, so they still differ when the counts tie.
"""

import os
import subprocess

# What a tree reads when it is not a usable checkout of its own repository.
# Wrong-looking on purpose, so a feed or an os-release that carries it says so.
UNKNOWN = "0.gunknown"

_TIMEOUT = 20


def _git(path, *args):
    """stdout of `git <args>` run in path, or None when git cannot answer."""
    env = dict(os.environ, PSEUDO_UNLOAD="1", GIT_OPTIONAL_LOCKS="0")
    try:
        done = subprocess.run(
            ["git", *args], cwd=path, env=env, capture_output=True, text=True, timeout=_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def revision_tag(path):
    """`<commit count>.g<8 hex of HEAD>`, plus `.dirty` for uncommitted changes.

    UNKNOWN when path is not a checkout of the repository that tracks it. The
    layer's own conf/layer.conf must be tracked, so a tree extracted inside some
    other repository does not borrow that repository's revision.

    A shallow clone cannot count its history, so its count reads 0 rather than
    the depth, which would look like a real number. The count is the only part
    that orders builds, and 0 says it cannot be trusted.

    Untracked files count as dirty and ignored ones do not. Two builds of one
    commit with different uncommitted edits still share a tag.
    """
    if not path or not os.path.isdir(path):
        return UNKNOWN
    if _git(path, "ls-files", "--error-unmatch", "conf/layer.conf") is None:
        return UNKNOWN

    rev = (_git(path, "rev-parse", "HEAD") or "").strip()
    status = _git(path, "status", "--porcelain", "--untracked-files=normal")
    if not rev or status is None:
        return UNKNOWN

    shallow = (_git(path, "rev-parse", "--is-shallow-repository") or "").strip()
    count = (_git(path, "rev-list", "--count", "HEAD") or "").strip() if shallow == "false" else ""

    return "%s.g%s%s" % (count if count.isdigit() else "0", rev[:8], ".dirty" if status.strip() else "")
