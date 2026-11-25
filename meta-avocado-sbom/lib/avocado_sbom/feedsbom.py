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


def parse_alt_recipes(text):
    """Split the multi-kernel recipe list into ((mc, recipe) pairs, malformed entries).

    Entries are whitespace-separated mc:recipe. Pairs keep first-seen order with
    duplicates collapsed; an entry with no colon, no multiconfig or no recipe is
    malformed.
    """
    pairs = []
    malformed = []
    for entry in text.split():
        mc, sep, recipe = entry.partition(":")
        if not sep or not mc or not recipe:
            malformed.append(entry)
        elif (mc, recipe) not in pairs:
            pairs.append((mc, recipe))
    return pairs, malformed


def alt_tmpdir(topdir, mc):
    """The alternate multiconfig's TMPDIR, as avocado-multikernel.bbclass builds it."""
    return "%s/tmp-%s" % (topdir, mc)


def classify_alt(pairs, find_alt_roots):
    """Split (mc, recipe) pairs into (mc, recipe, handles) and those with no document.

    find_alt_roots(mc, recipe) returns a list of root handles, empty when the
    multiconfig's directory holds no document for the recipe.
    """
    included = []
    not_covered = []
    for mc, recipe in pairs:
        handles = find_alt_roots(mc, recipe)
        if handles:
            included.append((mc, recipe, handles))
        else:
            not_covered.append(
                {
                    "mc": mc,
                    "recipe": recipe,
                    "reason": "no document in tmp-%s/deploy/spdx" % mc,
                }
            )
    return included, not_covered


def wrong_kernel_references(statements):
    """Statements whose target_version differs from their kernel_version."""
    return [s for s in statements if s["target_version"] != s["kernel_version"]]


def alias_collisions(default_aliases, alt_aliases):
    """Sorted identity aliases carried by both the default and the alternate kernel."""
    return sorted(set(default_aliases) & set(alt_aliases))


def referenced_aliases(shared, target_ids):
    """Sorted aliases among shared that some relationship or statement targets."""
    return sorted(set(shared) & set(target_ids))


def alt_label(mc, recipe):
    """How the coverage record names an alternate recipe it includes."""
    return "%s:%s" % (mc, recipe)


def drop_alias_collided(included, shared_by_label, target_ids):
    """Split included into (kept, not covered) by whether a shared alias is targeted.

    Two kernels sharing an identity alias is harmless until something refers to
    that alias, because the assembled set then resolves it to whichever kernel
    it indexed last. target_ids must be the raw targets taken before assembly,
    which resolves and strips aliases. shared_by_label is keyed by alt_label,
    because one recipe can be built in more than one alternate multiconfig and
    each is judged on its own aliases.
    """
    target_ids = set(target_ids)
    kept = []
    not_covered = []
    for mc, recipe, handles in included:
        aliases = referenced_aliases(
            shared_by_label.get(alt_label(mc, recipe), ()), target_ids
        )
        if aliases:
            not_covered.append(
                {
                    "mc": mc,
                    "recipe": recipe,
                    "reason": "alias collision: %s" % ", ".join(aliases),
                }
            )
        else:
            kept.append((mc, recipe, handles))
    return kept, not_covered


def drop_wrong_reference(included, wrong):
    """Split included into (kept, not covered) by whether a statement hit another version.

    wrong holds wrong_kernel_references' output, each carrying the recipe name and
    "mc", the alternate multiconfig the reference was traced to. One traced to a
    multiconfig drops that multiconfig's build of the recipe only, since one
    recipe can be built in several (Jetson builds nvidia-kernel-oot in three).
    One traced to none, "mc" empty or absent, drops every alternate build of the
    recipe: it came from the default kernel's side and any of them may be the
    other end.
    """
    counts = {}
    for statement in wrong:
        key = (statement.get("mc") or "", statement["recipe"])
        counts[key] = counts.get(key, 0) + 1
    kept = []
    not_covered = []
    for mc, recipe, handles in included:
        count = counts.get((mc, recipe), 0) + counts.get(("", recipe), 0)
        if count:
            not_covered.append(
                {
                    "mc": mc,
                    "recipe": recipe,
                    "reason": "reference collision: %d statement(s) target another version"
                    % count,
                }
            )
        else:
            kept.append((mc, recipe, handles))
    return kept, not_covered


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
        # mkstemp creates 0600; the document beside this record is written with
        # the umask mode, and a consumer running as another user must read both.
        os.fchmod(fd, 0o644)
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
