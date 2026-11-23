# SPDX-License-Identifier: Apache-2.0

"""Which recipes a feed scan covers, and what it states about its own coverage.

The feed is whatever the build packaged, so the scan starts from the recipes
that shipped packages and reads each one's SPDX document. A recipe without a
document is a hole in the scan; it is counted, named in a coverage record and
gated by a ceiling instead of being skipped silently.

This module is plain logic over plain values. It imports neither oe nor bb, so
it runs and is tested outside a build.
"""

import json
import os
import tempfile

SCOPE_WORLD = "world"
SCOPE_IMAGE = "image"
SCOPE_FEED = "feed"

_WORLD_DEPENDENCY = "meta-world-recipe-sbom:do_sbom_cve_check_recipe"
_IMAGE_TASK = "do_sbom_cve_check"


class FeedSbomError(Exception):
    """The feed scan cannot honestly report what it covered."""


def feed_recipes(packages):
    """Sorted distinct recipe names from the mapping report.read_pkgdata returns."""
    return sorted({info["recipe"] for info in packages.values()})


def classify(recipes, find_roots):
    """Split recipes into (recipe, handle) roots and the recipes with no document.

    find_roots(recipe) returns a list of root handles, empty when the recipe has
    no document.
    """
    roots = []
    missing = []
    for recipe in recipes:
        handles = find_roots(recipe)
        if not handles:
            missing.append(recipe)
            continue
        roots.extend((recipe, handle) for handle in handles)
    return roots, sorted(missing)


def check_missing(missing, ceiling):
    """Fail, naming every recipe, when more have no document than the ceiling allows."""
    if len(missing) > ceiling:
        raise FeedSbomError(
            "%d recipes shipped packages but have no SPDX document (ceiling %d): %s"
            % (len(missing), ceiling, ", ".join(missing))
        )


def coverage_summary(roots, missing, unresolved, alt_included=(), alt_not_covered=()):
    return {
        "roots": len(roots),
        "no_document": sorted(missing),
        "unresolved_ids": unresolved,
        "alt_included": list(alt_included),
        "alt_not_covered": list(alt_not_covered),
    }


def write_summary(path, summary):
    """Replace the file at path with the summary as sorted-key JSON, atomically.

    An existing file or symlink is removed first so a stale record, or a link to
    somewhere else, is never written through.
    """
    if os.path.lexists(path):
        os.remove(path)
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".coverage-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(summary, f, sort_keys=True, indent=2)
            f.write("\n")
        os.rename(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise


def scope_dependency(scope, image):
    """The task a scope's report waits on, or None when it orders its own."""
    if scope == SCOPE_WORLD:
        return _WORLD_DEPENDENCY
    if scope == SCOPE_IMAGE:
        return "%s:%s" % (image, _IMAGE_TASK)
    if scope == SCOPE_FEED:
        return None
    raise FeedSbomError(
        "unknown scope %r: expected %s, %s or %s"
        % (scope, SCOPE_WORLD, SCOPE_IMAGE, SCOPE_FEED)
    )
