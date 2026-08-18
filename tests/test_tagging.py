"""Regression tests for Layer 5, the deterministic tag lexicon.

Every case here is a false positive that reached the shortlist during
development. The asymmetry from `CLAUDE.md` holds one layer up: a false hit
hides a real one, so it is worse than a false miss.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import sqlite3
import unittest

from quantscraper import db, lexicon, tagging


def _posting(title, description="", location="Stockholm, Sweden", department=None,
             category=None):
    return {
        "ats": "greenhouse", "token": "firm", "job_id": "1",
        "title": title, "description": description,
        "location": location, "department": department, "category": category,
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
        """admini*strat*or contains "strat", and this corpus is full of them.

        It reads `rejected` rather than `unknown` since `lexicon.judge` became
        the last word on relevance: a corporate administrator is a named
        corporate function, so "nothing decided this" was never the honest
        answer. What the test guards is the token boundary."""
        tags = _tags(title="Corporate Administrator")

        self.assertEqual(tags["relevance"], {"rejected"})
        self.assertNotIn("quant_dev", tags["role_class"])

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

        self.assertEqual(tags["relevance"], {"relevant"})
        self.assertNotIn("apply_now", tags["fit"])  # capped: the title said nothing

    def test_desk_support_is_not_the_desk(self):
        for title in ("Trading Operations Engineer", "Campus Recruiter"):
            with self.subTest(title=title):
                self.assertEqual(
                    _tags(title=title, department="Trading")["relevance"], {"rejected"}
                )

    def test_a_domain_word_beside_a_desk_word_demotes_rather_than_rejects(self):
        """"Credit Risk Quant" is quant work; "Credit Risk Operations (Debt
        Collections)" is a collections job, and only the qualifier tells them
        apart. The second reached the shortlist as apply_now.

        Demoted, not rejected: a missed posting is the expensive failure, so
        it stays readable at a lower rank."""
        tags = _tags(title="Associate, Credit Risk Operations (Debt Collections)")

        self.assertEqual(tags["relevance"], {"adjacent"})
        self.assertNotIn("apply_now", tags["fit"])

    def test_an_unambiguous_quant_word_is_not_demoted_by_one(self):
        """A *risk quant* is a modelling role; a *risk analyst* need not be."""
        self.assertEqual(
            _tags(title="Credit Risk Quant, Operations")["relevance"], {"relevant"}
        )

    def test_a_quant_title_outranks_a_desk_word(self):
        self.assertEqual(
            _tags(title="Quantitative Researcher, Trading Operations")["relevance"],
            {"relevant"},
        )


class HandLabelledTest(unittest.TestCase):
    """Every case here came back from the hand-labelled sheet as a
    disagreement, which is what the fixture is for."""

    def test_equity_research_is_not_quant_research(self):
        """Sell-side equity research is an investment-banking job. Bare
        `research analyst` is the same shape as bare `trader`: the job it names
        is quant at one firm and something else at the next."""
        tags = _tags(title="Equity Research Analyst")

        self.assertNotIn("relevant", tags["relevance"])

    def test_a_quantitative_research_analyst_still_reads_as_one(self):
        """The fix must not cost the postings it was never about."""
        self.assertEqual(
            _tags(title="Quantitative Research Analyst")["relevance"], {"relevant"}
        )

    def test_one_quant_phrase_in_a_body_is_not_a_quant_role(self):
        """`Data Management Analyst - Data Governance` says "model validation"
        once, the way every governance document does, and came back as
        research work. A fragment needs a second word -- the rule `domains.py`
        arrived at one layer down, for the same reason."""
        tags = _tags(
            title="Data Management Analyst - Data Governance",
            description="You will support model validation reporting across "
                        "the group and maintain the data catalogue. " * 8,
        )

        self.assertNotIn("relevant", tags["relevance"])
        self.assertNotIn("less_relevant", tags["relevance"])

    def test_one_quant_phrase_and_no_markets_word_is_not_even_adjacent(self):
        """The corpus contains a computational chemist, a thermal-fluids
        analyst and a cloud engineer, all reading as quant work on a single
        borrowed phrase. `judge` says it best: "model validation" in a
        chemist's posting is chemistry."""
        for title in ("Computational Chemist (Electronic & Functional Materials)",
                      "Thermal - Fluids Analyst I / II", "Cloud Engineer"):
            with self.subTest(title=title):
                tags = _tags(
                    title=title,
                    description="You will own model validation for our "
                                "simulation pipeline and tooling. " * 8,
                )
                self.assertNotIn("adjacent", tags["relevance"])

    def test_a_markets_word_still_lets_one_phrase_count(self):
        """Two-sided, not one: the same phrase in a body that also places the
        role in markets is evidence."""
        tags = _tags(
            title="Analyst, Capital Markets",
            description="You will own model validation for the trading desk "
                        "and its pricing library. " * 8,
        )

        self.assertIn(tags["relevance"], ({"adjacent"}, {"relevant"}, {"less_relevant"}))

    def test_two_quant_phrases_in_a_body_still_carry_a_silent_title(self):
        tags = _tags(
            title="Analyst, Team 4",
            description="You will run alpha research on systematic trading. " * 20,
        )

        self.assertEqual(tags["relevance"], {"relevant"})

    def test_a_named_occupation_is_rejected_rather_than_unplaced(self):
        """`Wealth Advisor` and `Alliance Director` fell through every rule and
        came back `unknown` -- "nothing looked at this", when three rules had.
        `lexicon.judge` carries the long occupation lists and now has the last
        word."""
        for title in ("Wealth Advisor", "Alliance Director",
                      "Head of Security & AI Governance"):
            with self.subTest(title=title):
                self.assertEqual(_tags(title=title)["relevance"], {"rejected"})

    def test_a_department_name_cannot_reject_the_role(self):
        """The first false rejection the fixture found. `Senior Trading
        Associate` sits in a department called *Trading Operations*, and the
        desk-support rule read title and department together -- so the desk's
        name rejected a seat on the desk."""
        tags = _tags(title="Senior Trading Associate", department="Trading Operations")

        self.assertNotIn("rejected", tags["relevance"])

    def test_a_desk_word_in_the_title_still_rejects(self):
        self.assertEqual(
            _tags(title="Trading Operations Engineer")["relevance"], {"rejected"}
        )

    def test_a_management_title_outranks_a_weak_positive(self):
        """`Director of Trading` reached `adjacent` on the ordinary word
        *trading*, when what the title announces is that somebody else does
        the work. The reader has under a year of experience and no interest in
        management."""
        for title in ("Director of Trading", "Head of Managed Accounts",
                      "Applied Science / Data Science Leader",
                      "Product Manager - B2C Credit",
                      "Managing Director, Head of EU Sales"):
            with self.subTest(title=title):
                self.assertEqual(_tags(title=title)["relevance"], {"rejected"})

    def test_an_unambiguous_quant_word_survives_a_management_title(self):
        """A quant role with a management grade is still a quant role -- the
        seniority dimension is what says it is out of reach."""
        tags = _tags(title="Head of Quantitative Research")

        self.assertEqual(tags["relevance"], {"relevant"})
        self.assertEqual(tags["seniority"], {"head_or_md"})

    def test_associate_director_is_not_management(self):
        """A bank stamps it on a five-year hire."""
        self.assertNotIn(
            "rejected", _tags(title="Associate Director, EQD Quant")["relevance"]
        )

    def test_a_department_name_is_not_a_management_grade_either(self):
        """`Associate - Fund Governance` sits in a department called *Director
        Services*. The seniority rules already name this posting; the
        management rule was rejecting it anyway."""
        tags = _tags(title="Associate - Fund Governance",
                     department="Director Services")

        self.assertNotIn("management title", tags.get("relevance_evidence", ""))
        self.assertNotEqual(tags["seniority"], {"head_or_md"})

    def test_discretionary_investing_is_not_quant_work(self):
        """Nine rejections in a row on the hand-labelled sheet, while the
        lexicon had `investment analyst` filed as a weak positive."""
        for title in ("Senior Investment Analyst", "Portfolio Associate",
                      "Asset Management Analyst", "Partner, Private Equity",
                      "Equity Research Analyst"):
            with self.subTest(title=title):
                self.assertEqual(_tags(title=title)["relevance"], {"rejected"})

    def test_a_quant_qualifier_still_rescues_the_same_desk(self):
        """The qualifier is the whole difference, as it is for `Credit Risk
        Operations`."""
        self.assertEqual(
            _tags(title="Quantitative Analyst, Private Equity")["relevance"],
            {"relevant"},
        )

    def test_a_bare_adjective_in_a_body_is_not_a_quant_phrase(self):
        """`Cloud Engineer` reached `adjacent` on "body only 'quantitative',
        once, at 'investment management'", and `Walleye Stock Competition` on
        a bare "quant". Both are hand-labelled rejections, and both were
        rescued by the one word every employer writes about every role.

        `lexicon` had already named that set and the body branch here was not
        reading from it.
        """
        for title, word in (("Cloud Engineer", "quantitative"),
                            ("Site Reliability Engineer", "quant")):
            with self.subTest(title=title):
                tags = _tags(
                    title=title,
                    description=f"We are an investment management firm with a "
                                f"strong {word} culture. You will run our "
                                f"Kubernetes clusters. " * 8,
                )
                self.assertNotIn("adjacent", tags["relevance"])
                self.assertNotIn("relevant", tags["relevance"])

    def test_a_real_phrase_in_the_same_body_still_reaches_adjacent(self):
        """Dropping the adjectives must not drop the phrases. The same posting
        that says *statistical arbitrage* instead of *quantitative* is the one
        case the body branch exists for."""
        tags = _tags(
            title="Cloud Engineer",
            description="We are an investment management firm running "
                        "statistical arbitrage strategies. You will run our "
                        "Kubernetes clusters. " * 8,
        )
        self.assertIn("adjacent", tags["relevance"])

    def test_the_last_word_can_never_overturn_a_positive(self):
        """It only converts an `unknown`, so a title that already said *quant*
        is out of its reach and it cannot manufacture a false rejection."""
        self.assertEqual(
            _tags(title="Head of Quantitative Research")["relevance"], {"relevant"}
        )


class DistanceFromTheCentreTest(unittest.TestCase):
    """Relevance measures distance; `role_class` carries direction.

    The three-bucket scale collapsed the two, and the first hand-labelled
    sample proved it: `adjacent` was used for "a quant dev role, less relevant
    to me" and for "very close to what I want" in neighbouring rows.
    """

    def test_research_is_the_centre(self):
        tags = _tags(title="Quantitative Researcher")

        self.assertEqual(tags["relevance"], {"relevant"})
        self.assertEqual(tags["role_class"], {"quant_research"})

    def test_a_trading_seat_is_real_quant_work_one_step_out(self):
        tags = _tags(title="Graduate Trader", department="Trading")

        self.assertEqual(tags["relevance"], {"less_relevant"})
        self.assertEqual(tags["role_class"], {"trading"})

    def test_trading_style_records_the_split_without_ranking_it(self):
        """Ranking on it was tried, measured at one row out of eighty, and
        reverted -- the sheet puts `Algorithmic Trader` at `less_relevant` and
        `Quantitative Trader` at `relevant`, which is the same category twice.

        The dimension stays because the fact is worth filtering on. This test
        exists so the next reader finds the answer instead of re-deriving it.
        """
        quant = _tags(title="Quantitative Trader", department="Trading")
        pure = _tags(title="Graduate Trader", department="Trading")

        self.assertEqual(quant["trading_style"], {"quant"})
        self.assertEqual(pure["trading_style"], {"pure"})
        self.assertEqual(quant["relevance"], pure["relevance"])

    def test_the_desks_name_is_still_not_a_seat_on_it(self):
        """Bare *trading* is a department, and `_TRADER_SEAT` matches the
        nouns for the job."""
        tags = _tags(title="Backend Engineer - Trading & Asset Optimization")
        self.assertEqual(tags["trading_style"], {"unstated"})

    def test_a_title_naming_both_research_and_developer_is_a_build_seat(self):
        """Schonfeld's `Quantitative Research / Developer` folds to
        "research developer", and the day job is shipping tools."""
        tags = _tags(title="Quantitative Research / Developer - Intern")

        self.assertEqual(tags["role_class"], {"quant_dev"})
        self.assertEqual(tags["relevance"], {"less_relevant"})

    def test_a_quant_title_over_an_operations_body_is_adjacent(self):
        """`Quantitative Trading Associate`: market-hours oversight, runbooks,
        incident response and position reconciliation, under a title that
        reads like a seat on the desk."""
        tags = _tags(
            title="Quantitative Trading Associate",
            description="Oversee trading activity, maintain operational "
                        "runbooks and alerts, lead incident response and "
                        "position reconciliations with counterparties. " * 8,
        )

        self.assertEqual(tags["desk"], {"middle_office"})
        self.assertEqual(tags["relevance"], {"adjacent"})

    def test_a_front_office_body_does_not_demote(self):
        """A trading-floor posting names trade-lifecycle machinery all the
        time; the specific claim has to win over the incidental mention."""
        tags = _tags(
            title="Quantitative Researcher",
            description="You will sit on the trading floor and need a grasp "
                        "of trade lifecycle workflows. " * 12,
        )

        self.assertEqual(tags["desk"], {"front_office"})
        self.assertEqual(tags["relevance"], {"relevant"})


class SeniorityTest(unittest.TestCase):
    def test_a_graduation_gate_is_a_hard_gate_not_a_rank(self):
        """The user has graduated, so a future graduation date is noise -- and
        titles never announce it.

        It moved off the seniority ladder: being a student is something you
        cannot pass rather than a grade you grow into, so it is a hard gate,
        and the *rank* is whatever the title said, which here is nothing."""
        tags = _tags(
            title="Quantitative Analyst",
            description="You must be enrolled and graduating in 2028. " * 20,
        )

        self.assertIn("student_only", tags["hard_gates"])
        self.assertEqual(tags["seniority"], {"unknown"})
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

    def test_a_body_welcoming_students_is_not_gated_on_graduation(self):
        """A full-time PhD-level research role at Radix was marked
        student-only because its body said "students"."""
        tags = _tags(
            title="Quantitative Researcher (Full-Time - PhD+)",
            description="We welcome students and graduates alike. " * 20,
        )

        self.assertNotIn("student_intern", tags["seniority"])

    def test_a_real_graduation_gate_still_wins_from_the_body(self):
        """No title announces it, which is why the gate is read from the body.
        It still costs the posting its fit; it just no longer claims to be a
        rank."""
        tags = _tags(
            title="Quantitative Analyst",
            description="Applicants must be graduating in 2028. " * 20,
        )

        self.assertIn("student_only", tags["hard_gates"])
        self.assertEqual(tags["fit"], {"out_of_scope"})

    def test_the_ladder_no_longer_offers_a_student_grade(self):
        """It was the one value read from a body rather than a title, so the
        labelling sheet kept asking a question the tagger does not answer."""
        self.assertNotIn("student_intern", tagging._SENIORITY)

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

    def test_an_internship_is_a_contract_not_a_rank(self):
        """Schonfeld's `Quantitative Research / Developer - Intern` demands
        "2-3 years buy- or sell-side experience" and converts to full time. It
        is an internship *contract* around a mid-level *bar*, and a ladder with
        `intern` on it swallowed the posting whole."""
        tags = _tags(
            title="Quantitative Research / Developer - Intern",
            description="You will need 2-3 years buy- or sell-side experience "
                        "as a STRAT or quant developer. " * 10,
        )

        self.assertEqual(tags["contract"], {"internship"})
        self.assertNotIn("intern", tags["seniority"])
        self.assertEqual(tags["experience_floor"], {"2"})

    def test_a_years_figure_outranks_the_titles_grade_word(self):
        """`Quantitative Trading Associate` reads junior on "associate" and
        asks for "3+ years". A grade word describes the ladder; a years figure
        states the bar."""
        tags = _tags(
            title="Quantitative Trading Associate",
            description="We require 3+ years of relevant experience. " * 20,
        )

        self.assertEqual(tags["experience_floor"], {"3"})
        self.assertEqual(tags["seniority"], {"mid_3_5"})

    def test_a_stray_authority_word_in_a_body_is_not_a_rank(self):
        """A `partner` in the diversity paragraph made an internship a
        managing-director posting, and that one tag moved it to `stretch`."""
        tags = _tags(
            title="Quantitative Research Developer",
            description="We partner with our people; our chief aim is that "
                        "the head of each team can hire well. " * 12,
        )

        self.assertNotIn("head_or_md", tags["seniority"])

    def test_the_smallest_demand_is_the_floor(self):
        tags = _tags(
            title="Quantitative Researcher",
            description="At least 3 years required, 8+ years preferred. " * 15,
        )

        self.assertEqual(tags["experience_floor"], {"3"})


class GatesAndSoftFiltersTest(unittest.TestCase):
    def test_a_doctorate_is_read_only_when_it_is_compulsory(self):
        """Every quantitative posting on earth prefers a higher degree, so a
        preference is not a gate and is deliberately not tagged."""
        preferred = _tags(
            title="Quantitative Researcher",
            description="A PhD is preferred and an MSc or Ph.D. is a plus. " * 15,
        )
        demanded = _tags(
            title="Quantitative Researcher",
            description="A Ph.D. is required for this role. " * 15,
        )

        self.assertNotIn("phd_required", preferred["hard_gates"])
        self.assertIn("phd_required", demanded["hard_gates"])

    def test_a_posting_saying_no_phd_required_does_not_trip_the_gate(self):
        """Matching is on token runs, so " no phd required " contains
        " phd required "."""
        tags = _tags(
            title="Quantitative Researcher",
            description="No PhD required for this role. " * 20,
        )

        self.assertNotIn("phd_required", tags["hard_gates"])

    def test_swedish_and_english_are_not_a_language_filter(self):
        """The user reads both, and the old gate flagged "flytande svenska" on
        Stockholm postings -- the one hub the project cares most about."""
        tags = _tags(
            title="Kvantitativ Analytiker",
            description="Du behover flytande svenska och engelska. " * 20,
        )

        self.assertEqual(tags["spoken_language"], {"none"})

    def test_a_third_language_is_recorded_and_ranks_the_posting_down(self):
        tags = _tags(
            title="Quantitative Researcher",
            location="Amsterdam",
            description="Fluent in Dutch is required for this role. " * 15,
        )
        without = _tags(title="Quantitative Researcher", location="Amsterdam")

        self.assertEqual(tags["spoken_language"], {"dutch"})
        self.assertEqual(without["fit"], {"strong"})
        self.assertEqual(tags["fit"], {"plausible"})  # one notch, never a drop


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

        self.assertEqual(tags["relevance"], {"relevant"})
        self.assertEqual(tags["hub"], {"other"})


class CompletenessTest(unittest.TestCase):
    def test_every_dimension_carries_a_value(self):
        """A posting with no seniority tag is indistinguishable from one
        nothing looked at -- the hole `ats.py` refuses to leave untiered."""
        tags = _tags(title="Something Entirely Unrelated", location="")

        for dimension in (
            "relevance", "role_class", "seniority", "code_depth", "contract",
            "asset_class", "horizon", "hard_gates", "hub", "fit",
            "desk", "experience_floor", "spoken_language",
        ):
            with self.subTest(dimension=dimension):
                self.assertTrue(tags.get(dimension))

    def test_a_rejected_posting_still_carries_its_reason(self):
        tags = _tags(title="Actuarial Pricing Analyst")

        self.assertEqual(tags["relevance"], {"rejected"})
        self.assertIn("actuarial", tags["exclusion_reason"])


if __name__ == "__main__":
    unittest.main()


class SearchTest(unittest.TestCase):
    """The read side, which is where filtering belongs.

    Nothing is dropped at ingest -- every lexicon bug found so far was fixed
    by re-running over stored rows, and a write-time filter would have thrown
    those rows away.
    """

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(db.SCHEMA)
        self.connection.executescript(tagging.SCHEMA)

    def tearDown(self):
        self.connection.close()

    def _store(self, job_id, title, location, first_seen="2026-01-01"):
        self.connection.execute(
            "INSERT INTO jobs (ats, token, job_id, title, location, first_seen,"
            " last_seen) VALUES ('greenhouse', 'b', ?, ?, ?, ?, ?)",
            (job_id, title, location, first_seen, first_seen),
        )
        row = dict(
            ats="greenhouse", token="b", job_id=job_id, title=title,
            location=location, description="", department=None,
        )
        tags = tagging.tag_posting(row)
        tags.append(tagging._fit(tags))
        tagging.record(self.connection, tags)

    def test_dimensions_are_and_but_values_within_one_are_or(self):
        """What a person means by "Amsterdam or Stockholm, and junior"."""
        self._store("1", "Junior Quantitative Researcher", "Amsterdam")
        self._store("2", "Junior Quantitative Researcher", "Singapore")
        self._store("3", "Senior Quantitative Researcher", "Amsterdam")

        found = tagging.search(
            self.connection,
            require={"hub": ("amsterdam", "stockholm"), "seniority": ("junior_0_2",)},
        )

        self.assertEqual([r["job_id"] for r in found], ["1"])

    def test_exclude_drops_a_posting_carrying_any_listed_value(self):
        self._store("1", "Quantitative Researcher", "Amsterdam")
        self._store("2", "Crypto Quantitative Researcher", "Amsterdam")

        found = tagging.search(
            self.connection, exclude={"exclusion_reason": ("crypto_web3",)}
        )

        self.assertEqual([r["job_id"] for r in found], ["1"])

    def test_the_best_fit_sorts_first(self):
        self._store("1", "Quantitative Researcher", "Amsterdam")
        self._store("2", "Junior Quantitative Researcher", "Amsterdam")

        self.assertEqual(
            [r["fit"] for r in tagging.search(self.connection)][0], "apply_now"
        )

    def test_a_withdrawn_posting_is_never_returned(self):
        """Removed, not deleted -- the row stays and stops being offered."""
        self._store("1", "Junior Quantitative Researcher", "Amsterdam")
        self.connection.execute("UPDATE jobs SET removed_at = '2026-02-01'")

        self.assertEqual(tagging.search(self.connection), [])

    def test_since_filters_on_first_seen(self):
        self._store("1", "Quantitative Researcher", "Amsterdam", "2026-01-01")
        self._store("2", "Quantitative Researcher", "Amsterdam", "2026-06-01")

        found = tagging.search(self.connection, since="2026-05-01")

        self.assertEqual([r["job_id"] for r in found], ["2"])


class OffIndustryTest(unittest.TestCase):
    """Stage one: another profession entirely, and the board drops it.

    Every other exclusion here ranks a posting further away and leaves it
    readable. This one removes it from the board, so it has to be narrow, and
    these are the cases that say whether it still is.
    """

    def _reasons(self, **kwargs) -> set[str]:
        return _tags(**kwargs).get("exclusion_reason", set())

    def test_the_sources_own_taxonomy_gates_the_posting(self):
        """21 occupation fields, and fifteen can never hold a quant job."""
        tags = _tags(title="Undersköterska till natten", category="Hälso- och sjukvård")
        self.assertIn("off_industry", tags["exclusion_reason"])
        self.assertEqual(tags["relevance"], {"rejected"})

    def test_a_quant_title_does_not_talk_the_gate_out_of_it(self):
        """A hospital hiring a statistician is still a hospital.

        This is the branch order: `off_industry` is tested before the quant
        ladder, so a body full of "analys" cannot promote it.
        """
        tags = _tags(
            title="Kvantitativ analytiker",
            description="Vi söker en kvantitativ analytiker för statistisk analys. " * 8,
            category="Hälso- och sjukvård",
        )
        self.assertEqual(tags["relevance"], {"rejected"})

    def test_a_kept_field_stays_readable(self):
        """A drop list fails towards keeping, which is the safe direction."""
        tags = _tags(title="Kvantitativ analytiker", category="Administration, ekonomi, juridik")
        self.assertNotIn("off_industry", tags.get("exclusion_reason", set()))
        self.assertEqual(tags["relevance"], {"relevant"})

    def test_an_unrecognised_field_passes(self):
        tags = _tags(title="Quantitative Researcher", category="Något helt nytt")
        self.assertNotIn("off_industry", tags.get("exclusion_reason", set()))

    def test_occupation_words_gate_the_boards_with_no_taxonomy(self):
        """Only JobStream publishes a field, so the ATS boards need the words."""
        for title in ("Certified Nurse Midwife (CNM)", "Medical AI Specialist",
                      "Maintenance Electrician / Controls", "Piercing Studio Nurse"):
            with self.subTest(title=title):
                self.assertIn("off_industry", self._reasons(title=title))

    def test_chef_is_swedish_for_manager(self):
        """`Ekonomichef` is a CFO. The English word would have dropped it."""
        self.assertNotIn("off_industry", self._reasons(title="Ekonomichef"))

    def test_the_gate_leaves_finance_alone(self):
        for title in ("Quantitative Researcher", "Market Risk Quant",
                      "Value Driver Analyst", "Head of Trading",
                      "Portfolio Manager, Systematic Equities"):
            with self.subTest(title=title):
                self.assertNotIn("off_industry", self._reasons(title=title))


class AccentFoldingTest(unittest.TestCase):
    """`fold` deleted every character outside `a-z0-9+#`, so `Sjuksköterska`
    became "sjuksk terska" while the needle said `sjukskoterska`. Every Swedish
    rule in the module was therefore dead, and a rule that never fires looks
    exactly like a rule with nothing to catch."""

    def test_nordic_letters_become_their_ascii_letter(self):
        self.assertIn(" goteborg ", tagging.fold("Göteborg"))
        self.assertIn(" sjukskoterska ", tagging.fold("Sjuksköterska"))
        self.assertIn(" lastbilsforare ", tagging.fold("Lastbilsförare"))
        self.assertIn(" francais ", tagging.fold("français"))
        self.assertIn(" kobenhavn ", tagging.fold("København"))

    def test_the_swedish_occupation_needles_now_fire(self):
        for title in ("Sjuksköterska till akuten", "Städare sökes",
                      "Lastbilsförare Distribution", "Målare till Stockholm",
                      "Förskollärare till Husby"):
            with self.subTest(title=title):
                self.assertIsNotNone(
                    tagging._hit(tagging.fold(title), tagging._OFF_INDUSTRY))

    def test_a_needle_may_be_written_either_way(self):
        """Both sides converge now, which is what "fold both sides" was always
        supposed to mean and could not while the fold was lossy."""
        self.assertEqual(tagging._terms("Göteborg"), tagging._terms("goteborg"))

    def test_cplusplus_still_survives(self):
        """Transliteration runs before the symbol table, so it must not eat the
        one substitution the file already depended on."""
        self.assertIn(" cplusplus ", tagging.fold("Strong C++ skills"))


class GeographyGatesTest(unittest.TestCase):
    """Geography ranked and now gates, at the reader's request. That makes
    every imprecision in `_HUBS` a deleted posting rather than a mis-rank."""

    def _hub(self, location, title="Quantitative Analyst"):
        tags = tagging.tag_posting(_posting(title=title, location=location))
        return next(t.value for t in tags if t.dimension == "hub")

    def _gated(self, location, title="Quantitative Analyst"):
        tags = tagging.tag_posting(_posting(title=title, location=location))
        return "off_location" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_a_country_no_longer_claims_its_capital(self):
        """`sweden` used to sit in the `stockholm` tuple, so Kiruna, Lund and
        Visby all read Stockholm -- 180 postings placed in a city they are
        1,200 km from, which a gate would now delete for being there."""
        self.assertEqual(self._hub("Kiruna, Norrbotten, Sweden"), "sweden_other")
        self.assertEqual(self._hub("Stockholm, Sweden"), "stockholm")
        self.assertTrue(self._gated("Kiruna, Norrbotten, Sweden"))
        self.assertFalse(self._gated("Stockholm, Sweden"))

    def test_the_named_rejects(self):
        for location in ("Paris, France", "Barcelona, Spain", "Kiruna, Sweden"):
            with self.subTest(location=location):
                self.assertTrue(self._gated(location))

    def test_a_place_that_names_no_place_is_unknown_and_stays(self):
        """Workday publishes `2 Locations` for 6,281 postings. Reading that as
        `other` claimed we looked and found somewhere else, and under a gate it
        would delete a posting that might be in Amsterdam."""
        self.assertEqual(self._hub("2 Locations"), "unknown")
        self.assertFalse(self._gated("2 Locations"))

    def test_a_us_state_code_is_semi_target_not_elsewhere(self):
        """No US city list is ever finished; the state code is the handle. 5,987
        postings were being gated out of a geography that is kept."""
        for location in ("Cincinnati, OH", "Waltham, MA", "Holland, MI"):
            with self.subTest(location=location):
                self.assertEqual(self._hub(location), "deprioritized")
                self.assertFalse(self._gated(location))

    def test_a_state_code_is_never_read_from_the_title(self):
        """`IN`, `OR` and `ME` are English words as well as state codes, which
        is why this is matched against the location alone."""
        self.assertNotEqual(
            self._hub("Paris, France", title="Trading IN Rates OR Credit"),
            "deprioritized")

    def test_an_office_tower_is_still_its_city(self):
        """190 postings give `One Island East` as the whole location, and it is
        Swire's Quarry Bay tower."""
        self.assertEqual(self._hub("One Island East"), "hong_kong")


class OutOfReachTest(unittest.TestCase):
    """Management and senior titles gate rather than rank, at the reader's
    request: under a year of experience there is no reading of `Director` that
    is a first job."""

    def _gated(self, title):
        tags = tagging.tag_posting(_posting(title=title))
        return "out_of_reach" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_the_named_ranks_are_removed(self):
        for title in ("Director of Trading", "VP, Quantitative Analyst",
                      "Manager - Quantitative Strategies", "Product Owner - Risk",
                      "Project Leader, Analytics", "Head of Quantitative Research",
                      "Senior Quantitative Developer"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_nordic_manager_compounds_are_removed(self):
        """Swedish builds a manager's title by compounding and no word list
        finishes: `inköpschef`, `hållbarhetschef`, `projektledare`."""
        for title in ("Inköpschef till Stockholm", "Hållbarhetschef",
                      "Projektledare till IT", "Gruppchef Analys"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_it_fires_on_evidence_and_never_on_its_absence(self):
        """The safety property. A title carrying no grade word reads `unknown`
        and stays -- the gate can only remove a rank it actually read."""
        for title in ("Quantitative Researcher", "Junior Quantitative Researcher",
                      "Graduate Trader", "Data Scientist"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))

    def test_swedish_trade_compounds_are_off_industry(self):
        """`Elsäljare` is one token, so the needle `saljare` cannot see it, and
        48 of these were still on the board after the accent fix."""
        for title in ("Elsäljare till Barcelona", "Fältsäljare sökes",
                      "Tandsköterska - Smile Täby", "Skadetekniker till Spånga"):
            with self.subTest(title=title):
                tags = tagging.tag_posting(_posting(title=title))
                reasons = [t.value for t in tags if t.dimension == "exclusion_reason"]
                self.assertIn("off_industry", reasons)

    def test_the_compound_heads_that_were_rejected(self):
        """`medarbetare` is Swedish for "employee" and `Forskningsassistent` is
        a research assistant -- the `chef`-is-a-CFO mistake in a new place."""
        for title in ("Forskningsassistent", "Medarbetare till analysavdelningen"):
            with self.subTest(title=title):
                tags = tagging.tag_posting(_posting(title=title))
                reasons = [t.value for t in tags if t.dimension == "exclusion_reason"]
                self.assertNotIn("off_industry", reasons)

    def test_a_cook_is_not_a_manager(self):
        """`chef` is Swedish for manager and English for cook, and the compound
        rule must not read the English word as the Swedish one."""
        tags = tagging.tag_posting(_posting(title="Chef de Partie"))
        reasons = [t.value for t in tags if t.dimension == "exclusion_reason"]
        self.assertNotIn("out_of_reach", reasons)


class SpokenLanguageTest(unittest.TestCase):
    """Hand-written phrasings caught 151 postings out of 69,961. Advertisements
    ask for a language in twenty ways and the list knew three."""

    def _speaks(self, description):
        tags = tagging.tag_posting(_posting(title="Analyst", description=description))
        return {t.value for t in tags if t.dimension == "spoken_language"}

    def test_the_phrasings_a_hand_written_list_missed(self):
        for phrase in ("Proficiency in German is expected.",
                       "Good command of French required.",
                       "Written and spoken Dutch.",
                       "Business level Japanese.",
                       "Verhandlungssicher Deutsch.",
                       "Italian speaker preferred."):
            with self.subTest(phrase=phrase):
                self.assertNotEqual(self._speaks(phrase * 12), {"none"})

    def test_english_and_swedish_are_never_a_requirement(self):
        """The reader has both, and the old gate flagged "flytande svenska" on
        Stockholm postings -- the one hub the project cares most about -- as
        though it were an obstacle."""
        self.assertEqual(
            self._speaks("Flytande svenska och engelska krävs. " * 12), {"none"})


class TradingStyleTest(unittest.TestCase):
    """A bare `Trader` and a `Quantitative Trader` are different jobs."""

    def _style(self, title, description="") -> set[str]:
        return _tags(title=title, description=description)["trading_style"]

    def test_a_bare_trader_is_pure(self):
        for title in ("Trader", "Energy Trader", "Junior Trader",
                      "Commodity Trader", "Sales Trader"):
            with self.subTest(title=title):
                self.assertEqual(self._style(title), {"pure"})

    def test_a_quant_word_in_the_title_makes_it_quant(self):
        for title in ("Quantitative Trader", "Systematic Trader",
                      "Market Making Quant, Equity Derivatives"):
            with self.subTest(title=title):
                self.assertEqual(self._style(title), {"quant"})

    def test_a_body_cannot_make_a_trader_quant(self):
        """`role_class` falls back to the body and files SOX auditors as
        trading. A dimension about traders cannot inherit that."""
        self.assertEqual(
            self._style("Energy Trader", "We are a quantitative systematic trading firm. " * 10),
            {"pure"},
        )

    def test_a_non_trading_title_says_nothing(self):
        self.assertEqual(self._style("Quantitative Researcher"), {"unstated"})
        self.assertEqual(self._style("Trading Operations Analyst"), {"unstated"})

    def test_a_department_name_is_not_a_seat(self):
        """Bare *trading* is the name of a department. It made a backend
        engineer and an account manager into pure traders."""
        for title in ("(Senior) Backend Engineer - Trading & Asset Optimization",
                      "Account Manager (Wholesale & Trading), SME & Growth",
                      "Algo Developer, Fixed Income Trading"):
            with self.subTest(title=title):
                self.assertEqual(self._style(title), {"unstated"})

    def test_the_noun_form_of_a_quant_word_still_counts(self):
        """`Algorithmic Trader` is not the phrase "algorithmic trading", and
        was reading as a trader with no quant signal at all."""
        self.assertEqual(self._style("Algorithmic Trader"), {"quant"})


class GateRestraintTest(unittest.TestCase):
    """Words that look like a trade and name a job this project might want.

    Each of these matched something real in the corpus while the gate was
    being written. They are the reason `coach`, `pilot`, `librarian`,
    `translator` and `interpreter` are not needles.
    """

    def _gated(self, title) -> bool:
        return "off_industry" in _tags(title=title).get("exclusion_reason", set())

    def test_the_gate_catches_front_of_house(self):
        for title in ("Receptionist Floater", "Telefonist till televäxeln",
                      "Senior Concierge", "Front Desk Agent", "Janitor",
                      "Courtesy Bus Driver - PT", "Chauffeur Livreur"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_the_gate_leaves_look_alike_titles_alone(self):
        for title in ("Portfolio Manager/Agile Coach", "Financial Coach",
                      "Senior Engineer - Paint Pilot Projects",
                      "Lead Engineer-ECAD Librarian", "Research Librarian",
                      "ED/SVP, Team Head, Data Translator, CBG Singapore",
                      "Parts Interpreter"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))


class DirectorIsAlwaysOutOfReach(unittest.TestCase):
    """`associate director` and `assistant director` were protected as a bank's
    mid-career grade, which is true and does not help: from under a year both
    are as unreachable as a real one. Three reached the labelling sheet after
    the gate was added, because the protection routed them to `seniority`,
    where a body asking for three years read `mid_3_5` and cleared the bar."""

    def _gated(self, title, description=""):
        tags = tagging.tag_posting(_posting(title=title, description=description))
        return "out_of_reach" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_the_junior_sounding_director_grades(self):
        for title in ("Associate Director, FCC Models & Product Risk",
                      "Assistant Director - Front Office Services",
                      "Deputy Director of Analytics"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_a_years_figure_cannot_rescue_one(self):
        """The specific escape that let three through."""
        self.assertTrue(self._gated(
            "Associate Director, Quantitative Risk",
            "You will need 3+ years of relevant experience. " * 12))

    def test_director_in_another_sense_is_not_a_rank(self):
        for title in ("Art Director", "Creative Director", "Funeral Director"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))


class OccupationVocabularyTest(unittest.TestCase):
    """Added after a 1,000-posting machine-labelled sample showed the largest
    single disagreement was `relevance: unknown` on rows any reader rejects on
    sight. 6,604 of the 6,852 had no body at all, so this is title vocabulary
    rather than a broken rule."""

    def _gated(self, title):
        tags = tagging.tag_posting(_posting(title=title))
        return "off_industry" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_venue_and_front_of_house(self):
        for title in ("Retail Associate", "Usher/Ticket Taker", "Box Office Lead",
                      "Production Runner", "Venue Cleaner", "Workplace Ambassador",
                      "Conseiller Commercial F/H"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_the_plural_the_dictionary_form_missed(self):
        """`environmental inspector` did not match `Environmental Inspectors
        (Field Based)`. Token matching is exact; check the form the corpus
        actually advertises."""
        self.assertTrue(self._gated("Environmental Inspectors (Field Based)"))

    def test_quant_titles_are_untouched_by_any_of_it(self):
        for title in ("Quantitative Researcher", "Quantitative Developer",
                      "Junior Quant Trader", "Graduate Quantitative Analyst"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))


class RetailBankingIsNotMarkets(unittest.TestCase):
    """1,435 postings carry `banker` and not one was rated positively. Bare
    `banker` subsumes Universal, Premier, Associate, Retail and Personal on a
    token match."""

    def test_branch_staff_are_rejected(self):
        for title in ("Universal Banker (20 Hours)", "Premier Banker II",
                      "Client Relationship Consultant 2", "Banking Advisor",
                      "Small Business Specialist", "Audit Staff - Summer 2027",
                      "Tax Intern 2028"):
            with self.subTest(title=title):
                self.assertEqual(
                    lexicon.judge(title).verdict, "reject", title)

    def test_a_quant_title_at_a_bank_survives(self):
        for title in ("Quantitative Analyst, Retail Banking",
                      "Quantitative Researcher - Consumer Bank"):
            with self.subTest(title=title):
                self.assertNotEqual(lexicon.judge(title).verdict, "reject")


class EnrolmentBoundProgrammes(unittest.TestCase):
    """A German `Duales Studium` or `Werkstudent` contract is void without
    current enrolment and the reader has graduated, so the title settles it."""

    def test_the_programmes_are_rejected(self):
        for title in ("Duales Studium BWL - Risk and Insurance Management",
                      "Werkstudent (m/w/d) Financial Accounting",
                      "Ausbildung zum Zweiradmechatroniker"):
            with self.subTest(title=title):
                call = lexicon.judge(title)
                self.assertEqual(call.verdict, "reject")
                self.assertEqual(call.reason, "student_only")

    def test_a_bare_internship_is_still_not_rejected_on_its_title(self):
        """The documented false rejection this list must not re-create:
        Aquatic Capital's `Quantitative Researcher, Early Career` and
        `Quantitative Researcher, PhD` are the most on-target postings in the
        corpus. An internship is often open to a recent graduate; an
        enrolment-bound programme is not."""
        for title in ("Quantitative Research Intern",
                      "Quantitative Researcher, Early Career",
                      "Summer Analyst, Systematic Trading"):
            with self.subTest(title=title):
                self.assertNotEqual(lexicon.judge(title).verdict, "reject")


class SoftwareSpecialtyTest(unittest.TestCase):
    """Six hand-labelled rows, one shape. Every one reached `adjacent` or
    `unknown` on the bare word *trading* -- the name of the platform the
    engineer maintains, not the work -- and every one was rejected by hand."""

    def test_the_specialty_outranks_a_weak_positive(self):
        for title in ("Senior Software Engineer, Frontend (Agentic Trading)",
                      "Senior DevOps Engineer - Trading Platforms",
                      "Principal Engineer - Trading Core",
                      "Cloud Engineer",
                      "Data Infrastructure Engineer",
                      "Staff QE"):
            with self.subTest(title=title):
                self.assertEqual(_tags(title=title)["relevance"], {"rejected"})

    def test_an_unambiguous_quant_word_still_wins(self):
        """`CLAUDE.md` is explicit that heavy systems engineering is a
        down-rank rather than a hard drop, and many quant-dev roles are
        advertised as an engineering seat."""
        for title in ("Quantitative Developer",
                      "Quant Platform Engineer",
                      "Quantitative Research Engineer"):
            with self.subTest(title=title):
                self.assertNotIn("rejected", _tags(title=title)["relevance"])

    def test_bare_software_engineer_is_not_on_the_list(self):
        """The list is a proper subset of `lexicon.ENGINEERING` on purpose:
        `Software Engineer, Trading Systems` at Optiver is in scope, and no
        one-sided list of engineering words separates it from a payments
        backend. Only titles where the specialty *is* the job are here."""
        self.assertIsNone(tagging._hit(
            tagging.fold("Software Engineer, Trading Systems"),
            tagging._SOFTWARE_SPECIALTY,
        ))

    def test_a_markets_activity_body_still_holds_one_open(self):
        """The escape is narrowed, not closed -- nothing writes *statistical
        arbitrage* about a platform it merely hosts."""
        tags = _tags(
            title="Cloud Engineer",
            description="We are an investment management firm running "
                        "statistical arbitrage strategies. You will run our "
                        "Kubernetes clusters. " * 8,
        )
        self.assertNotIn("rejected", tags["relevance"])


class VicePresidentIsAnOfficerGrade(unittest.TestCase):
    """Four hand-labelled rows, all noted "filter out becuase VP role".

    `PLAN.md` records the argument for the old placement -- at a bank VP is a
    mid-career grade -- and `_MANAGEMENT` had already stopped believing it,
    so the gate and the ladder disagreed about the same word.
    """

    def test_vp_reads_as_head_or_md(self):
        for title in ("Credit Risk Sanctioner (VP)",
                      "Client Portfolio Manager - VP",
                      "VP, Corporate Development",
                      "Vice President, Assistant Portfolio Manager"):
            with self.subTest(title=title):
                self.assertEqual(_tags(title=title)["seniority"], {"head_or_md"})

    def test_a_years_figure_cannot_demote_an_officer_title(self):
        """`_FLOOR_DECIDES` deliberately excludes the structural grades. A
        VP posting asking for seven years is a VP posting."""
        tags = _tags(title="Vice President, Assistant Portfolio Manager",
                     description="You will need 7+ years of experience. " * 12)
        self.assertEqual(tags["seniority"], {"head_or_md"})

    def test_md_is_read_and_maryland_is_not(self):
        """78 titles in 157,464 carry `md` and one is rated positively, an
        `(ED/MD)` officer seat. The state code lives in the location column,
        which the ladder never reads."""
        self.assertEqual(
            _tags(title="Northland Capital Markets - MD -Investment Banking",
                  location="Baltimore, MD")["seniority"],
            {"head_or_md"},
        )

    def test_the_ladder_reads_the_title_and_not_the_department(self):
        """Every comment in that block says so and the code passed
        `fold(title, department)`. It went unnoticed while the needles were
        phrases a department rarely carries; bare `director` is not one."""
        self.assertNotIn(
            "head_or_md",
            _tags(title="Associate - Fund Governance",
                  department="Director Services")["seniority"],
        )


class DoctorateIsAnEligibilityFactNotAVerdict(unittest.TestCase):
    """Two hand-labelled rows: "perfect fit - but has hard requirement of
    phd". *Perfect fit* is the half that decides where this belongs."""

    def test_a_compulsory_doctorate_gates_without_touching_relevance(self):
        tags = _tags(title="Quantitative Researcher (Full-Time - PhD+)")
        self.assertEqual(tags["relevance"], {"relevant"})
        self.assertIn("phd_required", tags["exclusion_reason"])

    def test_a_bare_phd_in_a_title_is_an_audience_not_a_bar(self):
        """220 titles carry it and 29 are rated positively -- `Campus
        Quantitative Researcher, PhD` among them. `CLAUDE.md` records that an
        over-eager student rule threw away Aquatic Capital's posting once."""
        for title in ("Campus Quantitative Researcher, PhD",
                      "Junior Quantitative Researcher (Ph.D.)",
                      "2027 Internship - Quantitative Researcher (Master or PhD)"):
            with self.subTest(title=title):
                tags = _tags(title=title)
                self.assertNotIn("phd_required",
                                 tags.get("exclusion_reason", set()))

    def test_the_negation_still_holds(self):
        """" no phd required " contains " phd required "."""
        tags = _tags(title="Quantitative Researcher",
                     description="No PhD required for this role. " * 12)
        self.assertNotIn("phd_required", tags.get("exclusion_reason", set()))


class PruneTest(unittest.TestCase):
    """`job_tags` accumulated 34 dead lexicon versions holding 297,056 rows,
    and the retention they represented did not exist: the primary key omits
    `tagger`, so a re-tag overwrites the previous version wherever a posting
    keeps the same value. Only rows whose value changed survived."""

    def _connection(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(tagging.SCHEMA)
        # **Each version carries a different `value`, and that is not a
        # convenience -- it is the only way rows from two versions coexist.**
        # The primary key is `(ats, token, job_id, dimension, value)` with no
        # `tagger` in it, so a version that reaches the same verdict overwrites
        # its predecessor outright. Writing this fixture the obvious way raises
        # `IntegrityError`, which is the bug `prune` exists to clean up after.
        rows = [
            ("gh", "firm", "1", "relevance", value, "strong", None, v, "t")
            for value, v in (("relevant", tagging.TAGGER),
                             ("less_relevant", tagging.TAGGER - 1),
                             ("adjacent", 9),
                             ("rejected", 1))
        ]
        connection.executemany(
            "INSERT INTO job_tags (ats, token, job_id, dimension, value,"
            " confidence, evidence, tagger, tagged_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
        )
        connection.commit()
        return connection

    def test_it_reports_before_it_deletes(self):
        connection = self._connection()
        stale = dict(tagging.stale_taggers(connection))

        self.assertNotIn(tagging.TAGGER, stale)
        self.assertEqual(set(stale), {tagging.TAGGER - 1, 9, 1})

    def test_the_current_version_is_never_touched(self):
        connection = self._connection()
        removed = tagging.prune(connection)

        self.assertEqual(removed, 3)
        left = connection.execute(
            "SELECT DISTINCT tagger FROM job_tags"
        ).fetchall()
        self.assertEqual([row["tagger"] for row in left], [tagging.TAGGER])

    def test_pruning_twice_is_a_no_op(self):
        """It is a derived table and the command is safe to re-run -- the
        second call must not report work it did not do."""
        connection = self._connection()
        tagging.prune(connection)

        self.assertEqual(tagging.prune(connection), 0)
        self.assertEqual(tagging.stale_taggers(connection), [])


class YearsFigurePromotesOnly(unittest.TestCase):
    """A number in a body is the posting's own bar when the title under-sells
    itself, and noise when it contradicts a grade word the title carries.

    Read in the demoting direction it was a leadership escape: `Senior Software
    Engineer` whose body mentions three years came out `mid_3_5` and cleared
    `out_of_reach`. A body's smallest number is routinely the *entry* bar on a
    senior posting -- "3+ years required, 8+ preferred" floors at three."""

    BODY = "You will need {n}+ years of relevant experience. " * 12

    def test_a_years_figure_still_raises_a_title_that_undersells(self):
        """The case the carve-out was written for: `Quantitative Trading
        Associate` says associate and demands three years."""
        tags = _tags(title="Quantitative Trading Associate",
                     description=self.BODY.format(n=3))
        self.assertEqual(tags["seniority"], {"mid_3_5"})

    def test_a_years_figure_cannot_demote_a_stated_grade(self):
        for title, floor in (("Senior Software Engineer", 3),
                             ("Senior Quantitative Researcher", 4),
                             ("Senior Trading Associate", 4)):
            with self.subTest(title=title):
                tags = _tags(title=title, description=self.BODY.format(n=floor))
                self.assertEqual(tags["seniority"], {"senior_6_10"})

    def test_the_demoted_posting_is_gated_again(self):
        """The point of the fix, not a side effect of it."""
        tags = _tags(title="Senior Software Engineer",
                     description=self.BODY.format(n=3))
        self.assertIn("out_of_reach", tags["exclusion_reason"])

    def test_a_title_with_no_grade_still_takes_the_floor(self):
        tags = _tags(title="Quantitative Researcher",
                     description=self.BODY.format(n=7))
        self.assertEqual(tags["seniority"], {"senior_6_10"})


class LeadershipContainmentTest(unittest.TestCase):
    """Seniority is scored by what the reader said it is for -- keeping
    leadership off the board -- rather than by agreement on a rung."""

    def _connection(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(db.SCHEMA)
        connection.executemany(
            "INSERT INTO jobs (ats, token, job_id, title, description, location,"
            " first_seen, last_seen) VALUES (?, ?, ?, ?, '', 'Stockholm', 't', 't')",
            [("gh", "f", "1", "Head of Quantitative Research"),
             ("gh", "f", "2", "Quantitative Researcher")],
        )
        connection.commit()
        return connection

    def test_a_leadership_row_the_board_withholds_counts_as_contained(self):
        from quantscraper import labels as labels_module
        connection = self._connection()
        rows = [labels_module.Label("gh", "f", "1", "relevant", "head_or_md", "")]

        kept, graded, lost = labels_module.containment(
            connection, rows, tagging.GATES, tagging.tag_posting)

        self.assertEqual((kept, graded, lost), (1, 1, 0))

    def test_an_opening_removed_by_the_rank_gate_is_counted_separately(self):
        """The two errors are not interchangeable, so they are never netted
        off against each other."""
        from quantscraper import labels as labels_module
        connection = self._connection()
        rows = [labels_module.Label("gh", "f", "1", "relevant", "junior_0_2", "")]

        kept, graded, lost = labels_module.containment(
            connection, rows, tagging.GATES, tagging.tag_posting)

        self.assertEqual(graded, 0)   # not a leadership row
        self.assertEqual(lost, 1)     # but the rank gate took it

    def test_a_row_with_no_seniority_label_is_not_scored(self):
        from quantscraper import labels as labels_module
        connection = self._connection()
        rows = [labels_module.Label("gh", "f", "2", "relevant", "", "")]

        self.assertEqual(
            labels_module.containment(
                connection, rows, tagging.GATES, tagging.tag_posting),
            (0, 0, 0),
        )
