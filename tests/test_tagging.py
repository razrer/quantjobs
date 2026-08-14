"""Regression tests for Layer 5, the deterministic tag lexicon.

Every case here is a false positive that reached the shortlist during
development. The asymmetry from `CLAUDE.md` holds one layer up: a false hit
hides a real one, so it is worse than a false miss.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from quantscraper import tagging


def _posting(title, description="", location="Stockholm, Sweden", department=None):
    return {
        "ats": "greenhouse", "token": "firm", "job_id": "1",
        "title": title, "description": description,
        "location": location, "department": department,
    }


def _tags(**kwargs) -> dict[str, set[str]]:
    row = _posting(**kwargs)
    tags = tagging.tag_posting(row)
    tags.append(tagging._fit(tags))
    grouped: dict[str, set[str]] = {}
    for tag in tags:
        grouped.setdefault(tag.dimension, set()).add(tag.value)
    return grouped


class TokenBoundaryTest(unittest.TestCase):
    def test_administrator_is_not_a_strat(self):
        """admini*strat*or contains "strat", and this corpus is full of them."""
        self.assertEqual(_tags(title="Corporate Administrator")["relevance"], {"unknown"})

    def test_state_streets_alpha_platform_is_not_alpha_research(self):
        self.assertNotIn(
            "core", _tags(title="Alpha Account Services Data Analyst")["relevance"]
        )

    def test_cplusplus_survives_folding(self):
        """"c++" folds to "c" under a naive scrub, and "c" matches everything."""
        tags = _tags(title="Quant Developer", description="C++ and Python. " * 30)
        self.assertIn("cplusplus", tags["language"])
        self.assertEqual(tags["code_depth"], {"systems"})


class RelevanceTest(unittest.TestCase):
    def test_the_title_decides_what_the_role_is(self):
        """"Strong quantitative skills" is boilerplate in the body of an
        accounting job, and it made three of them core quant roles."""
        tags = _tags(
            title="Insurance Accounting & Reporting Specialist",
            description="We look for strong quantitative skills. " * 20,
        )

        self.assertNotIn("core", tags["relevance"])

    def test_a_silent_title_still_falls_through_to_the_body(self):
        """`CLAUDE.md` forbids classifying on a title alone: Goldman says
        "Strat" and Jane Street says "Trader", so a title that says nothing
        must not end the enquiry."""
        tags = _tags(
            title="Analyst, Team 4",
            description="You will run alpha research on systematic trading. " * 20,
        )

        self.assertEqual(tags["relevance"], {"core"})
        self.assertNotIn("apply_now", tags["fit"])  # capped: the title said nothing

    def test_desk_support_is_not_the_desk(self):
        for title in ("Trading Operations Engineer", "Campus Recruiter"):
            with self.subTest(title=title):
                self.assertEqual(
                    _tags(title=title, department="Trading")["relevance"], {"rejected"}
                )

    def test_a_quant_title_outranks_a_desk_word(self):
        self.assertEqual(
            _tags(title="Quantitative Researcher, Trading Operations")["relevance"],
            {"core"},
        )


class SeniorityTest(unittest.TestCase):
    def test_student_only_is_not_a_flavour_of_intern(self):
        """The user has graduated, so a future graduation date is noise -- and
        titles never announce it."""
        tags = _tags(
            title="Quantitative Analyst",
            description="You must be enrolled and graduating in 2028. " * 20,
        )

        self.assertEqual(tags["seniority"], {"student_only"})
        self.assertEqual(tags["fit"], {"out_of_scope"})

    def test_the_title_decides_the_rank_too(self):
        """A body saying "you will report to the Head of Trading" made
        `Graduate Trader` a head_or_md posting, and one mentioning senior
        colleagues made it senior_6_10. The rank is in the title."""
        tags = _tags(
            title="Graduate Trader",
            description="You report to the Head of Trading and work with "
                        "senior colleagues on the desk. " * 15,
        )

        self.assertEqual(tags["seniority"] & {"head_or_md", "senior_6_10", "lead"}, set())
        self.assertTrue(tags["seniority"] & {"new_grad", "junior_0_2"})

    def test_a_body_welcoming_students_is_not_a_student_only_role(self):
        """A full-time PhD-level research role at Radix was marked
        student-only because its body said "students"."""
        tags = _tags(
            title="Quantitative Researcher (Full-Time - PhD+)",
            description="We welcome students and graduates alike. " * 20,
        )

        self.assertNotIn("student_only", tags["seniority"])

    def test_a_real_graduation_gate_still_wins_from_the_body(self):
        """No title announces it, which is why the bucket exists at all."""
        tags = _tags(
            title="Quantitative Analyst",
            description="Applicants must be graduating in 2028. " * 20,
        )

        self.assertEqual(tags["seniority"], {"student_only"})

    def test_associate_director_is_not_an_associate(self):
        self.assertEqual(
            _tags(title="Associate Director, EQD Quant")["seniority"], {"senior_6_10"}
        )

    def test_a_senior_quant_role_is_a_stretch_not_a_match(self):
        """Under a year of experience, subject-matter fit does not make a VP
        posting a fit. `CLAUDE.md` puts "too senior" on the exclude list."""
        self.assertEqual(_tags(title="Senior Quantitative Researcher")["fit"], {"stretch"})

    def test_a_junior_quant_role_in_a_focus_hub_is_the_top_bucket(self):
        self.assertEqual(
            _tags(title="Junior Quantitative Researcher", location="Amsterdam")["fit"],
            {"apply_now"},
        )


class GeographyRanksTest(unittest.TestCase):
    """Geography ranks results; it never gates them.

    Santander's global board filled the shortlist from `hub: other` while
    Stockholm showed one entry. The postings are real and keep their rows --
    they just should not outrank a focus hub.
    """

    def test_a_focus_hub_outranks_the_same_role_elsewhere(self):
        here = _tags(title="Junior Quantitative Researcher", location="Amsterdam")
        there = _tags(title="Junior Quantitative Researcher", location="Sao Paulo")

        self.assertEqual(here["fit"], {"apply_now"})
        self.assertEqual(there["fit"], {"strong"})

    def test_a_downranked_posting_still_keeps_every_tag(self):
        """Ranked down, never dropped."""
        tags = _tags(title="Quantitative Researcher", location="Sao Paulo")

        self.assertEqual(tags["relevance"], {"core"})
        self.assertEqual(tags["hub"], {"other"})


class CompletenessTest(unittest.TestCase):
    def test_every_dimension_carries_a_value(self):
        """A posting with no seniority tag is indistinguishable from one
        nothing looked at -- the hole `ats.py` refuses to leave untiered."""
        tags = _tags(title="Something Entirely Unrelated", location="")

        for dimension in (
            "relevance", "role_family", "seniority", "code_depth", "contract",
            "asset_class", "horizon", "hard_gates", "hub", "fit",
        ):
            with self.subTest(dimension=dimension):
                self.assertTrue(tags.get(dimension))

    def test_a_rejected_posting_still_carries_its_reason(self):
        tags = _tags(title="Actuarial Pricing Analyst")

        self.assertEqual(tags["relevance"], {"rejected"})
        self.assertIn("actuarial", tags["exclusion_reason"])


if __name__ == "__main__":
    unittest.main()
