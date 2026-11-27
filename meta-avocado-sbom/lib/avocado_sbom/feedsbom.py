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


COMPILED_SOURCES_VAR = "SPDX_INCLUDE_COMPILED_SOURCES"


def compiled_source_recipes(recipes, getvar):
    """The recipes whose SPDX is built to include their compiled source files.

    Only these recipes have a use for their builds document, and a builds
    document refers to the builds of the recipe's dependencies, which are not
    all in the feed: an image recipe's does, to a recipe with no document. A
    per-recipe setting wins over the global one, as OE-Core reads it.
    getvar(name) returns the variable's value, or None when it is not set.
    """
    default = getvar(COMPILED_SOURCES_VAR)
    selected = []
    for recipe in recipes:
        value = getvar("%s:pn-%s" % (COMPILED_SOURCES_VAR, recipe))
        if (default if value is None else value) == "1":
            selected.append(recipe)
    return selected


def collect_builds(recipes, find_build):
    """The builds documents of the recipes that have one, in recipe order.

    A recipe's compiled-source files and its build element live in its builds
    document, not in the recipe-level document the feed starts from. OE-Core
    pulls a document in only when something references it, and nothing in the
    recipe-level documents does, so the scanner would find no compiled sources
    to filter a kernel's CVEs with. find_build(recipe) returns the document, or
    None when the recipe has none; each recipe is looked up once.
    """
    found = []
    seen = set()
    for recipe in recipes:
        if recipe in seen:
            continue
        seen.add(recipe)
        doc = find_build(recipe)
        if doc is not None:
            found.append(doc)
    return found


def packages_of(packages, recipes):
    """Sorted names of the packages that belong to the given recipes.

    The scanner links a recipe's build to its compiled sources through the
    recipe's installable packages, whose documents hold the build's output
    relationships, so the feed hands those over beside the builds document.
    packages is the pkgdata mapping of package name to its record.
    """
    wanted = set(recipes)
    return sorted(name for name, record in packages.items()
                  if record["recipe"] in wanted)


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


def alt_path(topdir, tmpdir, path, mc):
    """path, a directory under the default TMPDIR, in the multiconfig's TMPDIR.

    Raises FeedSbomError when path is not under tmpdir, since the multiconfig's
    copy then cannot be derived from it.
    """
    tmpdir = tmpdir.rstrip("/")
    if not path.startswith(tmpdir + "/"):
        raise FeedSbomError("%s is not under TMPDIR %s" % (path, tmpdir))
    return alt_tmpdir(topdir, mc) + path[len(tmpdir):]


def alt_recipes_by_mc(pairs):
    """{mc: set of recipes} from parse_alt_recipes' pairs, in first-seen order.

    These are the recipes of each multiconfig that reach the feed, so the only
    ones whose packages the report and the RPM manifest read from its tree.
    """
    by_mc = {}
    for mc, recipe in pairs:
        by_mc.setdefault(mc, set()).add(recipe)
    return by_mc


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


def _statements_by_cve(statements):
    by_cve = {}
    for statement in statements:
        by_cve.setdefault(statement[0], set()).add(statement)
    return by_cve


def vex_overlap(build, other):
    """(product or None, version, CVE): a version build and other share and
    the first CVE their statements differ on, or None. Each is a dict with
    "products", "versions" and "statements" sets; a statement is a tuple whose
    first item is its CVE.

    sbom-cve-check 1.4.0 applies a VEX statement in the scanned document to a
    build whose version equals the version of the package the statement is
    about, whatever build that package belongs to (database/annot_utils.py
    checks the version before any CPE), for each CVE it matched to that build.
    Which CVEs those are depends on the records, which change between rescans
    and can name two products at once, and on the scanner's product aliases,
    so a differing statement at a shared version is never ruled harmless here.
    """
    versions = build["versions"] & other["versions"]
    if not versions:
        return None
    mine = _statements_by_cve(build["statements"])
    theirs = _statements_by_cve(other["statements"])
    for cve in sorted(set(mine) | set(theirs)):
        if mine.get(cve, set()) != theirs.get(cve, set()):
            products = build["products"] & other["products"]
            return (min(products) if products else None), min(versions), cve
    return None


def vex_twin(build, default_builds):
    """Whether a default build has build's products, versions and statements,
    and whatever else its dict carries: the recipe task gives the full CPEs
    and the package version too, since the scanner matches on vendor and part
    as well, and on the package version before any CPE.

    The scanner then treats the two alike: whatever statement build would give
    another build, or take from it, the default build already gives or takes,
    so leaving build in changes no result in the document. On Jetson each
    alternate multiconfig's nvidia-kernel-oot is the default one's twin, and it
    shares only a version number with edk2-firmware-tegra.
    """
    return any(build == other for other in default_builds.values())


def drop_vex_overlap(included, alt_builds, default_builds):
    """Split included into (kept, not covered) by whether the scanner would mix
    an alternate build's VEX statements with another build's.

    alt_builds maps alt_label(mc, recipe) to that build's dict (see
    vex_overlap); default_builds maps a default recipe to its dict. An
    alternate with a twin among the default builds (vex_twin) stays. Any other
    is compared with every default build and with every alternate kept before
    it, so of two alternates that overlap the first one stays.
    """
    kept = []
    not_covered = []
    others = sorted(default_builds.items())
    for mc, recipe, handles in included:
        label = alt_label(mc, recipe)
        build = alt_builds.get(label)
        found = None
        if build is not None and not vex_twin(build, default_builds):
            for name, other in others:
                overlap = vex_overlap(build, other)
                if overlap:
                    found = (name, overlap)
                    break
        if found:
            name, (product, version, cve) = found
            not_covered.append(
                {
                    "mc": mc,
                    "recipe": recipe,
                    "reason": "VEX overlap: %s is also %s, with other statements on %s"
                    % (" ".join(p for p in (product, version) if p), name, cve),
                }
            )
            continue
        kept.append((mc, recipe, handles))
        if build is not None:
            others.append((label, build))
    return kept, not_covered


def drop_unresolved(included, needs, unresolved):
    """Split included into (kept, not covered) by whether the alternate's own
    documents refer to an identifier the assembled document left unresolved.

    needs maps alt_label(mc, recipe) to the identifiers that alternate's
    documents refer to but do not define. An alternate kernel's document can
    link to a recipe only its multiconfig built, which the default tree's
    documents cannot resolve; that drops the kernel, not the whole feed.
    """
    unresolved = set(unresolved)
    kept = []
    not_covered = []
    for mc, recipe, handles in included:
        hit = unresolved & set(needs.get(alt_label(mc, recipe), ()))
        if hit:
            not_covered.append(
                {
                    "mc": mc,
                    "recipe": recipe,
                    "reason": "unresolved reference: %d identifier(s)" % len(hit),
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
