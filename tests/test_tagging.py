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

    def test_discretionary_investing_ranks_rather_than_rejects(self):
        """**Reversed at the reader's instruction**, against nine rejections in
        a row on the hand-labelled sheet.

        The sheet said these are not quant work and it is right about the
        work. The instruction is about the *board*: a markets seat at a markets
        firm belongs on it, ranked below the quant roles rather than removed
        from view. `Rates Sales - SEK Focus` at Nordea and `Commodities Sales
        to FICC Markets` at SEB are the postings that decided it, and the
        reader's words were "it is ok if it picks up junk, i can remove them
        myself".

        So the category still fires and is still recorded with its evidence --
        `list --exclude discretionary_investing` still shows exactly what it
        caught -- and it no longer reaches `rejected`. `_fit` caps it at
        `plausible`, which is what "below the quant roles" means here."""
        for title in ("Senior Investment Analyst", "Portfolio Associate",
                      "Asset Management Analyst", "Equity Research Analyst"):
            with self.subTest(title=title):
                tags = _tags(title=title)
                self.assertNotIn("rejected", tags["relevance"])
                self.assertIn("discretionary_investing", tags["exclusion_reason"])

    def test_a_partner_is_still_leadership_whatever_desk_it_names(self):
        """`Partner, Private Equity` was on the list above and comes off it:
        the reason it goes is `_MANAGEMENT`, which is untouched by the
        instruction and would remove it whatever the desk was called. Worth
        pinning separately, so a later change to the investing category cannot
        be read as having decided this one."""
        tags = _tags(title="Partner, Private Equity")
        self.assertEqual(tags["relevance"], {"rejected"})
        self.assertIn("out_of_reach", tags["exclusion_reason"])

    def test_a_department_is_not_the_desk_for_this_category_either(self):
        """Its own comment said "matched on the title only" and it was handed
        `fold(title, department)`. `Rates Sales - SEK Focus` sits in a
        department called *Investment banking / Institutional banking /
        Markets* and was rejected on `investment banking` -- the desk's name,
        not the job's. Third time this file has made the same mistake."""
        tags = _tags(title="Rates Sales - SEK Focus",
                     department="Investment banking / Institutional banking / Markets")

        self.assertNotIn("discretionary_investing", tags.get("exclusion_reason", set()))

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


class HeavySystemsDownRanksTest(unittest.TestCase):
    """`CLAUDE.md`'s role scope: heavy systems engineering **down-ranks rather
    than hard-drops**, because a quant-dev posting listing C++ as secondary
    still fits. A body match was hard-dropping 295 postings.

    The filter that says so governed one branch; a second branch read the
    unfiltered list and put both soft categories straight back. Found by a
    machine review of 720 rejected postings, which flagged exactly one false
    rejection: `Low Latency Engineer` at Da Vinci Derivatives.

    **The split is title against body**, which is the rule this file makes
    everywhere else. Excluding `heavy_systems` outright cost `Junior FPGA
    Engineer` at Eagle Seven, a hand-labelled rejection whose note reads
    "electronics work" -- and that title says what the job is.
    """

    def _read(self, title, body="", location="Amsterdam"):
        tags = tagging.tag_posting(
            _posting(title=title, description=body, location=location))
        return {t.dimension: t.value for t in tags
                if t.dimension in ("relevance", "role_class")}

    def test_fpga_in_a_body_no_longer_removes_a_posting(self):
        body = ("You will work with traders and quant researchers on our "
                "trading algorithms. Experience with FPGA is a plus. ") * 8
        self.assertNotEqual(self._read("Low Latency Engineer", body)["relevance"],
                            "rejected")
        self.assertNotEqual(
            self._read("Senior Software Engineer, C++", body)["relevance"],
            "rejected")

    def test_but_fpga_in_the_title_still_does(self):
        """The reader rejected this one by hand: "electronics work"."""
        body = "Eagle Seven is seeking a Junior FPGA Design Engineer. " * 10
        self.assertEqual(self._read("Junior FPGA Engineer", body)["relevance"],
                         "rejected")

    def test_but_crypto_still_rejects(self):
        """The asymmetry is deliberate: crypto is on the exclude list outright
        and heavy systems is explicitly not."""
        body = "We are building the leading crypto exchange. " * 20
        self.assertEqual(self._read("Staff Security Architect", body)["relevance"],
                         "rejected")

    def test_heavy_systems_still_ranks(self):
        """Down-ranked, not deleted -- the tag and its evidence stay."""
        tags = tagging.tag_posting(_posting(
            title="Low Latency Engineer",
            description="Our stack is FPGA and kernel bypass. " * 20))
        self.assertIn("heavy_systems",
                      [t.value for t in tags if t.dimension == "exclusion_reason"])
        self.assertNotIn("heavy_systems", tagging.GATES)

    def test_a_latency_budget_is_a_markets_fact(self):
        """23 titles in the corpus carry `low latency` and all 23 are markets
        firms -- LSEG, Tudor, Citi, Da Vinci, Tower Research, Jane Street."""
        read = self._read("Low-Latency Engineer")
        self.assertEqual(read["role_class"], "quant_dev")
        self.assertEqual(read["relevance"], "less_relevant")


class NordicOccupationTest(unittest.TestCase):
    """Sweden arrived as 48,173 postings on a board with no taxonomy.

    Jobindex and MyCareersFuture both publish an enumeration the advertiser
    picked from, and `_OFF_INDUSTRY_FIELDS` gates on it. Jobbsafari publishes
    none, so for Sweden the occupation words are the whole gate.
    """

    def _read(self, title, location="Stockholm"):
        tags = tagging.tag_posting(_posting(title=title, location=location))
        return {
            "relevance": next(t.value for t in tags if t.dimension == "relevance"),
            "gated": "off_industry" in
                     [t.value for t in tags if t.dimension == "exclusion_reason"],
        }

    def test_the_plural_is_a_different_string(self):
        """Token matching is exact, so `underskoterska` never saw
        `Undersköterskor` -- 269 of them, on the board."""
        for title in ("Undersköterskor till Korttidsenheten",
                      "Sjuksköterskor till Neuroenheten",
                      "Maskinoperatörer till Gnosjö",
                      "Taxichaufförer sökes",
                      "Däckmontörer till Däckia i Uppsala"):
            with self.subTest(title=title):
                self.assertTrue(self._read(title)["gated"])

    def test_the_workplace_names_the_profession(self):
        """"Timvikarier till Sjövägens barn och ungdomsboende" says what the
        work is only through the place it happens in."""
        for title in ("Timvikarier till Sjövägens barn och ungdomsboende",
                      "Sommarvikarier till hemtjänsten",
                      "Vikarier sökes till förskolor på Ekerö"):
            with self.subTest(title=title):
                self.assertTrue(self._read(title)["gated"])

    def test_the_assignment_names_it_when_nothing_else_does(self):
        """33 postings headed *Veteraner till städuppdrag!* -- no occupation
        word in the title at all."""
        self.assertTrue(self._read("Veteraner till städuppdrag!")["gated"])
        self.assertTrue(self._read("Veteraner till trädgårdsuppdrag!")["gated"])

    def test_danish_trades_are_read(self):
        for title in ("Sygeplejerske til Rigshospitalet",
                      "Pædagogmedhjælper til Børnehuset",
                      "Klejnsmed søges til daghold i Vojens",
                      "Musiklærer søges", "Tjener til restaurant"):
            with self.subTest(title=title):
                self.assertTrue(self._read(title, location="København")["gated"])

    def test_a_temporary_contract_is_not_another_profession(self):
        """`vikarie` is a contract length. Gating on it would delete a
        temporary quant seat on evidence about its duration."""
        read = self._read("Vikarierande Kvantitativ Analytiker")
        self.assertFalse(read["gated"])
        self.assertEqual(read["relevance"], "relevant")
        contract = tagging.tag_posting(
            _posting(title="Vikarierande analytiker",
                     description="Detta är ett vikariat på ett år. " * 12))
        self.assertIn("fixed_term",
                      [t.value for t in contract if t.dimension == "contract"])

    def test_the_dropped_heads_stay_dropped(self):
        """`-arbejder` is *medarbejder*, `-medhjaelper` is
        *studentermedhjælper* and half of those are IT work, `-vagt` is
        *aftenvagt*. Same shape as `-arbetare` catching *medarbetare*."""
        for head in tagging._NOT_A_TRADE_HEAD:
            with self.subTest(head=head):
                self.assertNotIn(head, tagging._TRADE_HEADS)
        self.assertFalse(
            self._read("Studentermedhjælper til udvikling af dataløsninger")["gated"])

    def test_no_nordic_needle_gates_a_quant_title(self):
        for title in ("Kvantitativ Analytiker", "Quantitative Researcher",
                      "Riskanalytiker inom kapitalförvaltning",
                      "Forskningsassistent"):
            with self.subTest(title=title):
                self.assertFalse(self._read(title)["gated"])


class SwissTradesTest(unittest.TestCase):
    """22,903 Swiss postings arrived and fifty reached the board.

    job-room.ch publishes its own taxonomy as bare AVAM codes with no labels
    and no open reference service, so Switzerland is gated by words where
    Denmark and Singapore are gated by an enumeration.
    """

    def _gated(self, title):
        tags = tagging.tag_posting(_posting(title=title, location="Zürich"))
        return "off_industry" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_the_fifty_that_leaked(self):
        for title in ("Zimmerreinigung 100%", "Masseurin", "Kosmetikerin",
                      "Dachdecker", "Verkäuferin Tankstellenshop 25-45%",
                      "Maçon coffreur", "Pflegefachfrau HF",
                      "Schlosser / Metallbauer 100%", "Polymechaniker"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_gartner_is_not_a_gardener_here(self):
        """Clean dry-run and dropped anyway: all 155 Danish gardeners are
        already gated by Jobindex's taxonomy, so the needle buys nothing --
        and `Gartner Research Analyst` is a title that exists."""
        self.assertNotIn("gartner", tagging._OFF_INDUSTRY)
        self.assertFalse(self._gated("Gartner Research Analyst"))

    def test_a_canton_code_is_switzerland(self):
        """job-room.ch writes the town and the canton, never the city, so
        **18,562 postings in a focus hub read `other`** and were gated off the
        board for being somewhere they are not."""
        for place in ("Meisterschwanden, AG", "Wallisellen, ZH", "Luzern, LU",
                      "Biel/Bienne, BE", "Solothurn, SO", "Chur, GR"):
            with self.subTest(place=place):
                tags = tagging.tag_posting(_posting(title="Analyst", location=place))
                self.assertEqual(
                    [t.value for t in tags if t.dimension == "hub"], ["switzerland"])

    def test_a_canton_code_is_never_read_from_a_title(self):
        """`SO`, `BE`, `AG`, `UR` and `GE` are all ordinary words. Same reason
        `_US_STATE` is matched against the location alone."""
        tags = tagging.tag_posting(
            _posting(title="Analyst, SO and GE reporting", location="Bangalore, India"))
        self.assertNotIn("switzerland", [t.value for t in tags if t.dimension == "hub"])

    def test_the_three_colliding_codes_stay_american(self):
        """`AR`, `NE` and `FL` are also Arkansas, Nebraska and Florida, and both
        readings are live here. Both labels keep the posting on the board, so
        the only question is which one is wrong -- and a false hit in a focus
        hub is worse than a false miss."""
        for place in ("Omaha, NE", "Hot Springs, AR", "Orlando, FL"):
            with self.subTest(place=place):
                tags = tagging.tag_posting(_posting(title="Analyst", location=place))
                self.assertEqual(
                    [t.value for t in tags if t.dimension == "hub"], ["deprioritized"])

    def test_no_swiss_needle_gates_a_quant_title(self):
        for title in ("Quantitative Analyst", "Quantitative Researcher",
                      "Analyste Commercial pour le Trading et la Trésorerie"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))


class NordicGeographyTest(unittest.TestCase):
    def test_a_swedish_town_is_sweden_and_not_elsewhere(self):
        """16,153 Swedish postings read `other`, which under a gate means
        deleted for being somewhere they are not."""
        for town in ("Ludvika", "Örnsköldsvik", "Trollhättan", "Gällivare",
                     "Katrineholm", "Västra Götalands län"):
            with self.subTest(town=town):
                tags = tagging.tag_posting(_posting(title="Analyst", location=town))
                self.assertEqual(
                    [t.value for t in tags if t.dimension == "hub"], ["sweden_other"])

    def test_the_commuting_belt_is_stockholm(self):
        for town in ("Södertälje", "Vallentuna", "Värmdö", "Ekerö", "Vaxholm"):
            with self.subTest(town=town):
                tags = tagging.tag_posting(_posting(title="Analyst", location=town))
                self.assertIn("stockholm", [t.value for t in tags if t.dimension == "hub"])

    def test_the_seven_dangerous_names_are_not_needles(self):
        """`Åre` folds to `are`, the ISO code for the United Arab Emirates, and
        reaches 83 Workday postings in Dubai."""
        for place, elsewhere in (
            ("Dubai, ARE", "sweden_other"),
            ("Salem, OR", "sweden_other"),
            ("VENEZIA, VENETO, Italy", "sweden_other"),   # Commis di Sala
        ):
            with self.subTest(place=place):
                tags = tagging.tag_posting(_posting(title="Analyst", location=place))
                self.assertNotIn(elsewhere,
                                 [t.value for t in tags if t.dimension == "hub"])

    def test_a_multi_country_region_is_unknown_and_stays(self):
        """1,392 postings say *De nordiska länderna*, which contains two focus
        hubs. `other` would delete them."""
        tags = tagging.tag_posting(
            _posting(title="Analyst", location="De nordiska länderna"))
        self.assertEqual([t.value for t in tags if t.dimension == "hub"], ["unknown"])
        self.assertNotIn("off_location",
                         [t.value for t in tags if t.dimension == "exclusion_reason"])


class ValuationAdjustmentTest(unittest.TestCase):
    """XVA and counterparty credit risk, added at the reader's request.

    `lexicon.py` had carried these words since it was written and
    `tagging.py` never did, so two modules disagreed about the same phrase.
    """

    def _read(self, title, body=""):
        row = _posting(title=title, description=body, location="Amsterdam")
        tags = tagging.tag_posting(row)
        return {t.dimension: t.value for t in tags if t.dimension in
                ("relevance", "role_class")}

    def test_xva_alone_names_the_work(self):
        """`XVA Analyst` came back `unknown` -- nothing in the lexicon read it."""
        self.assertEqual(self._read("XVA Analyst"),
                         {"relevance": "relevant", "role_class": "quant_research"})

    def test_counterparty_credit_risk_is_modelling_not_a_generic_risk_seat(self):
        """Bare `credit risk` is a domain that covers debt collections, which
        is why it grades weakly. *Counterparty* credit risk has no such
        reading: all 16 titles carrying it are bank quant seats."""
        self.assertEqual(self._read("Counterparty Credit Risk Analyst"),
                         {"relevance": "relevant", "role_class": "quant_research"})

    def test_a_build_seat_on_that_desk_is_no_longer_rejected(self):
        """`CCR Model Developer` was rejected outright as pure engineering."""
        self.assertNotEqual(self._read("CCR Model Developer")["relevance"], "rejected")
        self.assertEqual(
            self._read("Counterparty Credit Risk Python Developer")["relevance"],
            "relevant")

    def test_the_abbreviations_are_title_only(self):
        """`ccr` matches 15 bodies and most are "Channel and Customer
        Research"; `cva` matches 14 and the head of those is deal advisory;
        `dva` matched a Köksmästare. In a title they are the desk."""
        for word in ("ccr", "cva"):
            with self.subTest(word=word):
                self.assertIn(word, tagging._QUANT_CORE_TITLE)
                self.assertNotIn(word, tagging._QUANT_CORE)
        self.assertEqual(
            self._read("Channel and Customer Research Associate",
                       body="We track CCR and NPS across every channel and "
                            "report CVA to the board. " * 20)
            ["relevance"], "unknown")

    def test_the_qualifier_still_decides_for_bare_credit_risk(self):
        self.assertEqual(
            self._read("Credit Risk Operations (Debt Collections)")["role_class"],
            "risk")


class MultiLocationTest(unittest.TestCase):
    """A posting open in two cities is one row and two chances for the reader.

    `hub` was `_first`, so a seat advertised for Amsterdam *and* London was
    filed under whichever of them the lexicon happened to list earliest --
    which is a fact about the lexicon's ordering, not about the job.
    """

    def _hubs(self, location, title="Quantitative Analyst"):
        tags = tagging.tag_posting(_posting(title=title, location=location))
        return [t.value for t in tags if t.dimension == "hub"]

    def _gated(self, location, title="Quantitative Analyst"):
        tags = tagging.tag_posting(_posting(title=title, location=location))
        return "off_location" in [
            t.value for t in tags if t.dimension == "exclusion_reason"]

    def test_both_cities_are_recorded(self):
        self.assertEqual(
            self._hubs("Amsterdam, London"), ["amsterdam", "deprioritized"])

    def test_three_places_are_all_recorded(self):
        self.assertEqual(
            self._hubs("Hong Kong, Singapore, New York"),
            ["hong_kong", "singapore", "deprioritized"])

    def test_one_place_on_the_board_is_enough_to_stay(self):
        """The gate must fire on "nowhere the reader would go", never on
        "somewhere they would not" -- a Zurich-and-Milan posting is a Zurich
        posting, and gating it uses a fact that argues for keeping it."""
        self.assertFalse(self._gated("Zurich, Milan"))
        self.assertTrue(self._gated("Milan, Rome"))

    def test_the_lexicons_own_order_is_kept(self):
        """`build_data.py` leads a card with `hub[0]`, so the order carries
        meaning: a Stockholm-and-Frankfurt posting must not lead with
        Frankfurt."""
        self.assertEqual(self._hubs("Frankfurt, Stockholm")[0], "stockholm")

    def test_a_country_bucket_does_not_contradict_its_own_hub(self):
        """`sweden_other` means "in Sweden and *not* Stockholm", so emitting it
        beside `stockholm` is one posting asserting both. Jobbsafari writes
        exactly this string for a regional Stockholm advertisement."""
        self.assertEqual(self._hubs("Stockholm, Sverige"), ["stockholm"])
        self.assertEqual(self._hubs("Amsterdam, Netherlands"), ["amsterdam"])

    def test_but_a_real_second_city_survives_that_rule(self):
        """Collapsing on the bucket rather than on the country's own name would
        throw Aarhus away -- the multi-location bug arriving by the back door."""
        self.assertEqual(
            self._hubs("Copenhagen, Aarhus"), ["copenhagen", "denmark_other"])
        self.assertEqual(
            self._hubs("Stockholm, Goteborg, Sverige"), ["stockholm", "sweden_other"])

    def test_the_evidence_names_the_town_and_not_the_country(self):
        tags = tagging.tag_posting(
            _posting(title="Quant", location="Stockholm, Goteborg, Sverige"))
        residual = next(
            t for t in tags if t.dimension == "hub" and t.value == "sweden_other")
        self.assertIn("goteborg", residual.evidence)

    def test_one_place_still_yields_one_hub(self):
        self.assertEqual(self._hubs("Stockholm, Sweden"), ["stockholm"])
        self.assertEqual(self._hubs("2 Locations"), ["unknown"])
        self.assertEqual(self._hubs("Cincinnati, OH"), ["deprioritized"])

    def test_a_focus_hub_among_several_keeps_the_fit_notch_off(self):
        """`_fit` reads the set: an Amsterdam-and-Milan posting is not
        "outside the focus hubs"."""
        both = _tags(title="Quantitative Researcher", location="Amsterdam, Milan")
        away = _tags(title="Quantitative Researcher", location="Milan, Rome")
        self.assertNotEqual(both["fit"], away["fit"])


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
                      "Lead Quantitative Developer"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_a_plain_senior_title_ranks_rather_than_gates(self):
        """**`senior_6_10` came off the gate at the reader's instruction.**

        It was removing 9,914 postings, 947 of them in Stockholm and
        Copenhagen, and what it took there was not leadership: `Senior
        quantitative analyst within credit risk` at Swedbank, `Senior Engineer
        - Systematic Equity` at Lynx, Nordea's `Quantitative Risk Analyst,
        Credit Risk Data Management [Assistant/Regular/Senior]` -- a title
        whose own bracket offers the assistant rung. A Nordic bank stamps
        *Senior* on a three-to-five-year grade, which is the argument
        `_NOT_HEAD_GRADE` already makes for `Associate Director`.

        The rank is still read and still ranks: `_fit` caps it at `stretch`."""
        for title in ("Senior Quantitative Developer",
                      "Senior Quantitative Researcher"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))
                self.assertEqual(_tags(title=title)["seniority"], {"senior_6_10"})
                self.assertEqual(_tags(title=title)["fit"], {"stretch"})

    def test_a_student_title_is_not_a_leadership_title(self):
        """`Student Client Credit Manager to Stockholm` sits in a department
        called "Internships / Student positions" at Nordea and was rejected
        outright on the word *manager*, which there names the book rather than
        the reports. A management word in an intern title is the office the
        intern sits in."""
        for title in ("Student Client Credit Manager to Stockholm",
                      "Intern, AI Solutions for External Manager Selection",
                      "Early Career Intern - Fundamental Equities COO Office"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))

    def test_the_student_veto_does_not_reach_student_housing(self):
        """Greystar's `Student Living` is an apartment brand -- *student* is
        the tenant, not the applicant -- and it is the majority of the 95
        titles carrying both signals. They never depended on this rule:
        `student living` is an `_OFF_INDUSTRY` word, and `off_industry` is the
        first gate `build_data.py` tries."""
        tags = _tags(title="Leasing Manager - Haven at Elgin (Student Living)")
        self.assertIn("off_industry", tags["exclusion_reason"])

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

    def test_the_demoted_posting_is_ranked_down_again(self):
        """The point of the fix, not a side effect of it.

        It used to assert the gate, because `senior_6_10` was one. That rung
        ranks rather than gates now, at the reader's instruction, so the
        consequence to pin is the one that still exists: the rank survives the
        body's smaller number and `_fit` caps the posting at `stretch`. A
        quant title is used because `_fit` only reads the rank once relevance
        has been decided -- see the comment there."""
        tags = _tags(title="Senior Quantitative Researcher",
                     description=self.BODY.format(n=3))
        self.assertEqual(tags["seniority"], {"senior_6_10"})
        self.assertEqual(tags["fit"], {"stretch"})

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


class SwedishBoardTitlesTest(unittest.TestCase):
    """The 585 Swedish postings a fresh Jobbsafari sweep put on the board.

    These are real titles taken off `data.js`, not invented ones. They are the
    frame that matters: a national board advertises jobs no ATS in this project
    has ever carried, so the occupation vocabulary had been written against the
    wrong corpus and every one of these read as `relevance: unknown` -- which
    every gate deliberately lets through.
    """

    def _gated(self, title, **kwargs) -> bool:
        tags = _tags(title=title, **kwargs)
        return "off_industry" in tags.get("exclusion_reason", set())

    def test_the_titles_that_reached_the_board(self):
        for title in (
            "Barnvakt på heltid i Bro",
            "English Speaking Babysitter in Lidingö",
            "Allakando läxhjälp, Bromma, 1 gång/vecka, Generell läxhjälp",
            "Taxi förare",
            "Söker Taxi Förare",
            "Brevbärare Tibro, Tidsbegränsad anställning",
            "Brevbärare/paketbud - Huddinge",
            "Pasta- och pizzakock till Fratelli Mall of Scandinavia",
            "Sushikock",
            "Kvällskock sökes till Exit Lounge & Bar",
            "Köttmästare Sökes till Demirel Group AB",
            "Fönsterputsare / Window cleaners - Hemfrid Tyresö",
            "Snöskottare och sandupptagning",
            "Grävmaskinist Stockholm",
            "Reklamutdelare",
            "Skolpsykolog till Svedenskolan Bergshamra - 40%",
            "Anestesiolog till Tribonum för uppdrag i Södra Sverige",
            "Farmaceuter till DOZ Apotek Upplands Väsby Bredden",
            "Timvikarie - Brageskolan",
            "Biträdande lektor inom tumörbiologi",
            "Parkourtränare",
            "Båtbyggare",
            "Arborist",
            "Vi söker armerare till Stockholm!",
            "Registrator till statlig myndighet",
            "Night Audit - Nattreceptionist",
            "Sagsbehandler til kontrol af moms på e-handel",
        ):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title), f"{title!r} still reaches the board")

    def test_a_compound_head_catches_the_next_one_too(self):
        """The point of a head over a word: a compound nobody has seen yet."""
        for title in ("Grillkock till nyöppnad restaurang", "Tidningsutdelare sökes"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_the_swedish_postings_worth_keeping_survive(self):
        """The same sweep carried these, and a gate that eats them is worse."""
        for title in (
            "Quantitative Analyst to the IFRS 9 team | SEB, Stockholm",
            "Riskanalytiker inom kapitalförvaltning",
            "Quantitative Power Trader",
            "Intraday Trader",
            "Kvantitativt inriktad analytiker för verksamhetsuppföljning",
            "Fond- och värdepappersadministratör till AP7",
            "Analyst - Leveraged Finance | SEB, Stockholm",
            "Commodities Sales to FICC Markets | SEB, Stockholm",
            "Risk Model Developer",
        ):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title), f"{title!r} was gated off the board")

    def test_handlare_is_deliberately_not_a_needle(self):
        """One shopkeeper on the board is cheaper than a rule eating a trader."""
        self.assertFalse(self._gated("Handlare sökes till Tempo Singö"))

    def test_konsulent_is_deliberately_not_a_head(self):
        """Danish for an ordinary consultant, so it reads as a trade only in Swedish."""
        self.assertFalse(self._gated("IT-konsulent til Operations-teamet"))


class RatedPositivelyButNotTest(unittest.TestCase):
    """Read off what the re-tag rated *positively*, a different frame again.

    The board's own listing shows what got through; the positives show what got
    through *and was recommended*. A false keep near the top of a page sorted
    by fit costs more than fifty at the bottom.
    """

    def _gated(self, title) -> bool:
        return "off_industry" in _tags(title=title).get("exclusion_reason", set())

    def test_a_bare_technician_is_a_trade(self):
        """`tekniker` was a compound head and never a word, and it is eight
        characters -- one short of what `_compound` will look at."""
        for title in ("Tekniker till Quant Service i Ludvika", "Linux tekniker",
                      "AV-tekniker till Logic IT", "VVS-tekniker"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_car_sales_wearing_the_word_trader(self):
        for title in ("Intresserad av bilbranschen och försäljning? Bli Junior Trader",
                      "Trader till växande företag inom bilindustrin"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_a_real_trader_is_untouched(self):
        for title in ("Intraday Trader", "Power Trader", "Trader for Electronic Trading"):
            with self.subTest(title=title):
                self.assertFalse(self._gated(title))


class SwedishDefiniteFormTest(unittest.TestCase):
    """Swedish marks the definite by suffixing the occupational head.

    `underskoterska` against `Undersköterskor` was the plural; this is the same
    shape one inflection further on, and it is a rule rather than a list so the
    next definite form nobody has seen is caught too.
    """

    def _gated(self, title) -> bool:
        return "off_industry" in _tags(title=title).get("exclusion_reason", set())

    def test_the_definite_forms_the_corpus_actually_carries(self):
        """Both of these were on the board with the indefinite form gated."""
        for title in ("Taxiföraren", "Är du maskinföraren vi letat efter?"):
            with self.subTest(title=title):
                self.assertTrue(self._gated(title))

    def test_the_bare_head_still_needs_a_compound(self):
        """A head on its own is not a compound, and must not gate by itself."""
        self.assertFalse(self._gated("Foraren"))

    def test_a_short_definite_plural_is_below_the_floor_and_that_is_known(self):
        """`Städarna` folds to eight characters and `_MIN_COMPOUND` is nine.

        Written down rather than fixed. Lowering the floor to reach it would
        make a suffix test fire on ordinary words, and the form does not occur:
        `stadarna`, `forarna`, `saljarna` and `kockarna` have **zero hits**
        between them across all 288,498 live titles. The indefinite plurals
        that do occur -- `montorer`, `chaufforer`, `skoterskor` -- are heads in
        their own right for exactly this reason.
        """
        self.assertFalse(self._gated("Städarna till Solna"))


class MarketsTitleIsNotUnknownTest(unittest.TestCase):
    """**A title that names a markets desk is not a posting nothing looked at.**

    The reader's complaint about the Swedish and Danish board was "too much
    junk, e.g. inköpare, and too little jobs", and the two halves turned out to
    be one fault. 176 of the 199 Nordic cards were `relevance: unknown`, and
    that bucket held both `Inköpare för UBW Inköp support` and `Commodities
    Sales to FICC Markets | SEB` -- so on a board that sorts by fit they sat in
    the same block, and the real seats were underneath the purchasers.

    `lexicon.MARKETS` had the right words the whole time and nothing read them
    for relevance. The branch runs last, after `judge`, so it can only ever
    convert an `unknown`.
    """

    def _relevance(self, title, department=None, description=None):
        return _tags(title=title, department=department,
                     description=description)["relevance"]

    def test_a_markets_desk_in_the_title_reaches_adjacent(self):
        for title in ("Commodities Sales to FICC Markets",
                      "Market Data Specialist",
                      "Backoffice Administrator - Mutual Funds",
                      "APO to Group Treasury",
                      "Net developer to the Portfolio Solutions and "
                      "Derivatives Clearing Tech team"):
            with self.subTest(title=title):
                self.assertEqual(self._relevance(title), {"adjacent"})

    def test_it_never_overturns_a_rejection(self):
        """The placement is the safety property. Every exclusion, every hard
        gate and the whole occupation lexicon have already had their say by the
        time this runs, so it cannot rescue a posting they removed."""
        for title in ("Receptionist, Trading Floor",
                      "Sjuksköterska till Capital Markets",
                      "Head of Fixed Income"):
            with self.subTest(title=title):
                self.assertEqual(self._relevance(title), {"rejected"})

    def test_it_reads_the_title_and_never_the_body(self):
        """A body naming markets is the employer describing itself, which is
        the failure mode this file records against every body-matched rule."""
        body = ("We are a systematic trading firm active in fixed income and "
                "foreign exchange across every capital market. " * 8)
        self.assertEqual(self._relevance("Inköpare för UBW Inköp support",
                                         description=body),
                         {"rejected"})

    def test_a_hotel_front_office_is_not_a_trading_floor(self):
        """`front office` is one of the strongest words on `MARKETS` and 209
        titles carry it -- all but a handful genuine desks. The shift word is
        the discriminator, not the phrase."""
        self.assertNotEqual(
            self._relevance("Shiftleader Front Office, Scandic Spectrum"),
            {"adjacent"},
        )


class NordicVocabularyTest(unittest.TestCase):
    """Swedish and Danish, in both directions, read off the board the reader
    complained about."""

    def _tagged(self, title, **kw):
        return _tags(title=title, **kw)

    def test_the_occupations_the_reader_named_are_gated(self):
        """`Inköpare` alone was thirteen of the 199 Nordic cards, from six
        consultancies advertising the same `UBW Inköpssupport` seat."""
        for title in ("Inköpare för UBW Inköp support", "Inköpsansvarig",
                      "Operativ inköpare till Apotea | Stockholm",
                      "IT-upphandlare till Solna stad",
                      "Kategoriansvarig med kommersiellt driv till Apotea",
                      "Fastighetsingenjör", "Miljökonsult inom förorenad mark",
                      "Logistikkoordinator", "Servicekoordinator til Vores Bolig"):
            with self.subTest(title=title):
                self.assertIn("off_industry",
                              self._tagged(title)["exclusion_reason"])

    def test_the_corporate_functions_are_excluded_in_nordic_too(self):
        """The English words rejected an `HR Business Partner` and said nothing
        about `HR-ansvarig`. A corporate function is the same job in any
        language."""
        for title in ("HR-ansvarig", "Kampanjkoordinator till Dagab",
                      "Marknadskoordinator", "Lönekonsult på 50%",
                      "Fotograf till Svenskt Kosttillskott"):
            with self.subTest(title=title):
                self.assertEqual(self._tagged(title)["relevance"], {"rejected"})

    def test_forvaltare_is_a_caretaker_and_ranteforvaltare_is_not(self):
        """**The one word this whole exercise turns on.** Swedish `förvaltare`
        is a property caretaker in `Teknisk förvaltare` and a portfolio manager
        in `Ränteförvaltare till Swedbank Robur`, and the second is a posting
        this board exists to find. Only the qualified compounds are markets
        words; the bare head is on neither list."""
        self.assertIn("off_industry",
                      self._tagged("Teknisk förvaltare till Lennart Ericsson "
                                   "Fastigheter AB")["exclusion_reason"])
        self.assertNotIn("rejected",
                         self._tagged("Ränteförvaltare till Swedbank Robur")["relevance"])
        self.assertNotIn("rejected",
                         self._tagged("AP3 söker två globala "
                                      "aktieförvaltare")["relevance"])

    def test_bare_handel_is_commerce_and_is_not_a_markets_word(self):
        """`CLAUDE.md` has said so for a long time and `lexicon.MARKETS` kept
        the bare word anyway -- invisible while it was only ever the second
        half of a two-sided test. 85 live titles carry it and they are
        supermarket and wine-shop staff."""
        self.assertIsNone(
            lexicon.first(lexicon.normalize("Butiksmedarbetare, team "
                                            "kolonial/e-handel, Willys"),
                          lexicon.MARKETS)
        )

    def test_swedish_developer_compounds_reach_the_engineering_rule(self):
        """A Swedish job title is one token, so the `utvecklare` needle that
        has been on `ENGINEERING` for a long time could not see
        `Fullstackutvecklare`. Same shape as `_TRADE_HEADS` one module over."""
        for title in ("Fullstackutvecklare till en e-handelsplattform",
                      "Javautvecklare sökes", "Backendutvecklare",
                      "Lösningsarkitekt till IT"):
            with self.subTest(title=title):
                self.assertEqual(lexicon.judge(title).reason, "pure_engineering")

    def test_the_engineering_rule_stays_two_sided_in_swedish_too(self):
        """Which is what makes a broad compound head safe: `ENGINEERING` never
        rejects on its own."""
        self.assertEqual(
            lexicon.judge("Systemutvecklare till SEB Markets, fixed income").verdict,
            "keep",
        )


class RankDoesNotPromoteAnUnreadPostingTest(unittest.TestCase):
    """`stretch` outranks `unknown` on the board, so a rank word must not lift
    a posting nobody has read above one that was.

    While `senior_6_10` was a gate this was unreachable -- those postings never
    got to `_fit`. Taking the gate off made it reachable, and 290 of the 466
    Nordic cards became `Senior <IT consultant>` sitting above every genuine
    markets posting still at `unknown`."""

    def test_a_senior_title_with_no_verdict_stays_unknown(self):
        """A title no list places, which in this corpus is most of a national
        board. `Senior Javautvecklare` will not do -- the Swedish engineering
        compounds reject now, and that is a verdict -- and neither will any
        named occupation, for the same reason."""
        tags = _tags(title="Senior Grid Specialist")
        self.assertEqual(tags["relevance"], {"unknown"})
        self.assertEqual(tags["fit"], {"unknown"})

    def test_a_senior_title_with_a_verdict_still_caps_at_stretch(self):
        self.assertEqual(
            _tags(title="Senior Quantitative Researcher")["fit"], {"stretch"}
        )
