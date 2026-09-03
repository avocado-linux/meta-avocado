# SPDX-License-Identifier: Apache-2.0

"""Render the repository sections written into a target's generated .repo file.

Extracted from avocado-sdk-metadata.bb so the emitted block can be asserted on
without a build. What the client is told to verify is a security decision, and
until now it was only observable by building an SDK and reading the file out of
it.

dnf keeps two independent options here and the recipe only ever emitted one:

``gpgcheck``
    verifies *package* signatures. Avocado does not sign packages, so this stays
    off regardless of anything below.

``repo_gpgcheck``
    verifies the *repository index* against a detached ``repomd.xml.asc``. This
    is the one a signed feed needs, and the name of the recipe variable that
    drove ``gpgcheck`` (``AVOCADO_REPO_GPGCHECK``) reads as though it already
    did this. It did not.

Both default off. Turning ``repo_gpgcheck`` on before the feed publishes
signatures breaks every install, so the switch belongs with the publisher
change, not ahead of it.

Every ``.repo`` section the tree installs renders through here: the per-target
sections from avocado-sdk-metadata.bb, and the SDK container's own
``[avocado-sdk]`` from avocado-sdk-repos.bb. That is what makes one switch
enough - a section rendered anywhere else would sit at whatever it was
hardcoded to while the rest moved.

One hardcoded verification value remains and is deliberately out of scope here:
``[main] gpgcheck=True`` in avocado-sdk-repos' dnf.conf. It is dnf's default for
a repo that sets nothing, and every section rendered here sets ``gpgcheck``
explicitly, so it decides nothing today - it would decide for a repo added to
the container by someone else.
"""

# Relative to the repository root, which is also what baseurl points at.
_KEY_RELPATH = "repodata/repomd.xml.key"

# dnf parses both switches as booleans. Anything else is read as false, so a
# typo would silently disable verification rather than fail - which is the one
# outcome a security option must not have.
_BOOLEAN = ("0", "1")


def render_repo_section(
    *,
    section,
    name,
    baseurl_path,
    priority,
    gpgcheck="0",
    repo_gpgcheck="0",
):
    """Return one ``[section]`` block, including its trailing blank separator.

    ``baseurl_path`` is appended to the ``${repo_url}`` placeholder, which is
    substituted by the client at SDK install time rather than at build time.

    ``priority`` of None writes no priority line, leaving the section at dnf's
    default of 99. It stays a required argument so that forgetting it is a
    TypeError rather than a section that silently sorts below its siblings -
    the per-target file ranks its sections 1..N and depends on every one of
    them carrying a priority.

    Raises:
        ValueError: ``baseurl_path`` is empty, which would point the client at
            the feed root, or either verification switch is not a dnf boolean.
    """
    if not baseurl_path:
        raise ValueError(f"repo section {section!r} has no baseurl path")
    for option, value in (("gpgcheck", gpgcheck), ("repo_gpgcheck", repo_gpgcheck)):
        if value not in _BOOLEAN:
            raise ValueError(
                f"repo section {section!r}: {option} must be one of "
                f"{_BOOLEAN}, got {value!r}"
            )

    baseurl = "${repo_url}/" + baseurl_path

    lines = [
        f"[{section}]",
        f"name={name}",
        f"baseurl={baseurl}",
        "enabled=1",
        f"gpgcheck={gpgcheck}",
        f"repo_gpgcheck={repo_gpgcheck}",
    ]
    if repo_gpgcheck == "1":
        # Only advertised alongside verification: the key is published by the
        # same step that publishes the signature, so referencing it while
        # verification is off points at a 404.
        lines.append(f"gpgkey={baseurl}/{_KEY_RELPATH}")
    if priority is not None:
        lines.append(f"priority={priority}")

    return "\n".join(lines) + "\n\n"


def render_sdk_repo_section(*, gpgcheck="0", repo_gpgcheck="0"):
    """Return the ``[avocado-sdk]`` block the SDK container's own dnf reads.

    The three literals live here rather than in the recipe because a recipe is
    a BitBake task the test suite cannot import: spelled there, a typo in the
    section name or the path would pass every test and 404 on the container's
    first transaction.

    No priority. avocado-cli merges this file with the per-target repo config
    in one transaction (it sets ``reposdir`` to both directories), and dnf
    ranks priority globally across that merged set rather than per file. The
    per-target sections occupy 1..N, so leaving this at dnf's default of 99
    ranks it below them - which is where the static file this replaced
    effectively sat.
    """
    return render_repo_section(
        section="avocado-sdk",
        name="Avocado SDK",
        baseurl_path="$releasever/sdk/all",
        priority=None,
        gpgcheck=gpgcheck,
        repo_gpgcheck=repo_gpgcheck,
    )
