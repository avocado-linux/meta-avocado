#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Pin what a generated .repo section tells dnf to verify.

The distinction these tests exist to hold is that dnf has two separate options
and the tree only ever emitted one of them. ``gpgcheck`` verifies package
signatures; ``repo_gpgcheck`` verifies the repository index, which is the thing
a detached repomd.xml.asc covers. Emitting the first and calling it the second
is how a feed ends up believed-verified and unverified at once.

  python3 -m unittest discover -s meta-avocado/tests -p 'test_*.py'
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from avocado_sdk_metadata import repoconf  # noqa: E402


def parse(section_text):
    """Return the section's key=value body as a dict, ignoring the [header]."""
    out = {}
    for line in section_text.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        key, _, value = line.partition("=")
        out[key] = value
    return out


class RenderRepoSection(unittest.TestCase):
    def _render(self, **overrides):
        kwargs = {
            "section": "cortexa53-target",
            "name": "cortexa53-target",
            "baseurl_path": "$releasever/target/cortexa53",
            "priority": 3,
        }
        kwargs.update(overrides)
        return repoconf.render_repo_section(**kwargs)

    def test_header_and_baseurl_keep_the_repo_url_placeholder(self):
        text = self._render()

        self.assertTrue(text.startswith("[cortexa53-target]\n"))
        self.assertEqual(
            parse(text)["baseurl"],
            "${repo_url}/$releasever/target/cortexa53",
        )

    def test_metadata_verification_is_off_by_default(self):
        # Off is the only safe default while nothing in the feed is signed:
        # 92 of 92 live indexes carry no .asc today.
        self.assertEqual(parse(self._render())["repo_gpgcheck"], "0")

    def test_metadata_verification_can_be_turned_on(self):
        self.assertEqual(parse(self._render(repo_gpgcheck="1"))["repo_gpgcheck"], "1")

    def test_turning_on_metadata_verification_supplies_the_public_key(self):
        # Pulp publishes the key beside the index it signs, so the client has a
        # public half to pin without us distributing one separately.
        parsed = parse(self._render(repo_gpgcheck="1"))

        self.assertEqual(
            parsed["gpgkey"],
            "${repo_url}/$releasever/target/cortexa53/repodata/repomd.xml.key",
        )

    def test_no_key_is_advertised_while_verification_is_off(self):
        # A gpgkey= line pointing at a key that is not published yet is a 404
        # dnf can surface as an import failure. Nothing should reference it
        # until the signature it belongs to exists.
        self.assertNotIn("gpgkey", parse(self._render()))

    def test_package_signature_checking_is_independent_of_metadata_checking(self):
        # The two options are separate in dnf and must stay separate here:
        # packages are unsigned even once the index is signed.
        parsed = parse(self._render(gpgcheck="0", repo_gpgcheck="1"))

        self.assertEqual(parsed["gpgcheck"], "0")
        self.assertEqual(parsed["repo_gpgcheck"], "1")

    def test_package_signature_checking_still_honours_its_own_setting(self):
        self.assertEqual(parse(self._render(gpgcheck="1"))["gpgcheck"], "1")

    def test_the_existing_line_set_is_preserved(self):
        # Regression guard: this is the block the tree emits today. A change to
        # this set is a change to every generated client config.
        parsed = parse(self._render())

        self.assertEqual(
            parsed,
            {
                "name": "cortexa53-target",
                "baseurl": "${repo_url}/$releasever/target/cortexa53",
                "enabled": "1",
                "gpgcheck": "0",
                "repo_gpgcheck": "0",
                "priority": "3",
            },
        )

    def test_section_ends_with_a_blank_line_separator(self):
        # Sections are concatenated into one file; without the separator the
        # next [header] lands on the previous priority line.
        self.assertTrue(self._render().endswith("\n\n"))

    def test_priority_is_rendered_from_an_integer(self):
        self.assertEqual(parse(self._render(priority=11))["priority"], "11")


class PriorityIsOmissibleButNotOptional(unittest.TestCase):
    """A section can decline to rank itself; a caller cannot decline to say so.

    dnf ranks priority globally across every repo it loads, defaulting to 99.
    The per-target file ranks its own sections 1..N and breaks if one of them
    silently lands at 99, so omitting the argument stays a TypeError while
    passing None explicitly writes no line.
    """

    def test_passing_none_writes_no_priority_line(self):
        text = repoconf.render_repo_section(
            section="s", name="n", baseurl_path="p", priority=None
        )

        self.assertNotIn("priority", parse(text))

    def test_omitting_the_argument_is_still_an_error(self):
        # The guard the per-target file depends on: a section added there
        # without a priority must not render, it must fail.
        with self.assertRaises(TypeError):
            repoconf.render_repo_section(section="s", name="n", baseurl_path="p")

    def test_a_zero_priority_is_still_written(self):
        # Only None omits the line. Zero is a real dnf priority and must not
        # be swallowed by a falsy test.
        text = repoconf.render_repo_section(
            section="s", name="n", baseurl_path="p", priority=0
        )

        self.assertEqual(parse(text)["priority"], "0")

    def test_the_separator_survives_the_missing_line(self):
        # The priority line was last, so dropping it must not take the blank
        # separator with it.
        text = repoconf.render_repo_section(
            section="s", name="n", baseurl_path="p", priority=None
        )

        self.assertTrue(text.endswith("\n\n"))


class SdkRepoSection(unittest.TestCase):
    """Pin the block the SDK container's own dnf reads.

    These literals used to be a checked-in file a reviewer could diff. Now they
    are code, so this is what stands between a typo in the section name or the
    path and a container whose first dnf transaction 404s.
    """

    def test_the_whole_block_is_pinned(self):
        self.assertEqual(
            repoconf.render_sdk_repo_section(),
            "[avocado-sdk]\n"
            "name=Avocado SDK\n"
            "baseurl=${repo_url}/$releasever/sdk/all\n"
            "enabled=1\n"
            "gpgcheck=0\n"
            "repo_gpgcheck=0\n"
            "\n",
        )

    def test_it_declines_to_rank_itself(self):
        # avocado-cli merges this file with the per-target config in one
        # transaction, where the target sections hold 1..N. Staying at dnf's
        # default of 99 keeps this below them, as the static file it replaced
        # effectively was.
        self.assertNotIn("priority", parse(repoconf.render_sdk_repo_section()))

    def test_metadata_verification_reaches_it(self):
        # The whole point of routing this section through the renderer: the
        # switch has to reach the one repo every SDK container reads.
        parsed = parse(repoconf.render_sdk_repo_section(repo_gpgcheck="1"))

        self.assertEqual(parsed["repo_gpgcheck"], "1")
        self.assertEqual(
            parsed["gpgkey"],
            "${repo_url}/$releasever/sdk/all/repodata/repomd.xml.key",
        )

    def test_package_signature_checking_reaches_it_independently(self):
        parsed = parse(repoconf.render_sdk_repo_section(gpgcheck="1"))

        self.assertEqual(parsed["gpgcheck"], "1")
        self.assertEqual(parsed["repo_gpgcheck"], "0")

    def test_a_bad_switch_value_is_rejected_here_too(self):
        # The wrapper must not become a way around the boolean check.
        with self.assertRaises(ValueError):
            repoconf.render_sdk_repo_section(repo_gpgcheck="yes")


class RenderRepoSectionRejectsBadInput(unittest.TestCase):
    def test_an_empty_baseurl_path_is_rejected(self):
        # A section with no path silently points every client at the feed root.
        with self.assertRaises(ValueError):
            repoconf.render_repo_section(
                section="s", name="n", baseurl_path="", priority=1
            )

    def test_an_unknown_repo_gpgcheck_value_is_rejected(self):
        # dnf reads this as a boolean; anything else is a typo that would be
        # read as false and never noticed.
        with self.assertRaises(ValueError):
            repoconf.render_repo_section(
                section="s", name="n", baseurl_path="p", priority=1, repo_gpgcheck="yes"
            )

    def test_an_unknown_gpgcheck_value_is_rejected_the_same_way(self):
        # Both switches decide whether a signature is checked, so a typo in
        # either one silently disables a check. Neither gets to fail quietly.
        with self.assertRaises(ValueError):
            repoconf.render_repo_section(
                section="s", name="n", baseurl_path="p", priority=1, gpgcheck="ture"
            )


if __name__ == "__main__":
    unittest.main()
