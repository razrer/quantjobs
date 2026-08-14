"""Regression tests for the rejection lexicon.

Every case here is a posting that really is in the corpus, and most of them are
mistakes this module made before the rule that now covers them. The point is
the same as `test_workday.py`'s: removing a protection has to fail a test, not
merely change a number nobody reads.
"""

from __future__ import annotations

import unittest

from quantscraper import lexicon


class Normalization(unittest.TestCase):
    def test_matches_whole_tokens_only(self):
        """`administrator` contains "strat", and it is a real title here."""
        role = lexicon.normalize("Corporate Administrator")
        self.assertIsNone(lexicon.first(role, ("strat",)))
        self.assertIsNotNone(lexicon.first(role, ("administrator",)))

    def test_alpha_the_platform_is_not_alpha_the_signal(self):
        """State Street's custody platform is called Alpha; 'alpha research'
        must not match a posting that only says 'Alpha'."""
        role = lexicon.normalize("Alpha Account Services Data Analyst, Officer")
        self.assertIsNone(lexicon.first(role, lexicon.QUANT))

    def test_keeps_plus_and_hash(self):
        self.assertIn(" c++ ", lexicon.normalize("Strong C++ skills"))

    def test_strips_markup_and_bounds_the_body(self):
        self.assertNotIn("div", lexicon.normalize("<div class='x'>hello</div>"))
        self.assertLessEqual(len(lexicon.normalize("a" * 500_000)), lexicon.MAX_BODY + 2)

    def test_empty_input_is_not_a_match_for_anything(self):
        self.assertIsNone(lexicon.first(lexicon.normalize(None), lexicon.QUANT))


class NamedOccupations(unittest.TestCase):
    """A title that names the whole occupation is decidable without a body."""

    def test_rejects_the_obvious(self):
        for title in (
            "Corporate Receptionist",
            "Housekeeper - The Lucille Waco",
            "Maintenance Technician - Pax Place at Cascades",
            "Automotive Mechanic (B Tech) - Budget Truck - FT",
            "Certified Nurse Midwife (CNM) (Full-Time)",
            "Assistant Community Manager - Fort Lee, New Jersey Area",
        ):
            with self.subTest(title=title):
                call = lexicon.judge(title)
                self.assertEqual(call.verdict, "reject")
                self.assertIsNotNone(call.evidence)

    def test_a_quant_word_in_the_title_downgrades_to_a_read(self):
        """`Lead Technical Recruiter (Quant Engineering)` is a recruiter -- but
        rejecting it outright is the one failure this project calls expensive,
        so it becomes a read rather than a decision."""
        call = lexicon.judge("Lead Technical Recruiter (Quant Engineering)")
        self.assertEqual(call.verdict, "undecided")

    def test_body_boilerplate_cannot_rescue_an_occupation(self):
        """A quant fund's description says "systematic trading firm" on its
        receptionist posting too. Only the title speaks for the role."""
        call = lexicon.judge(
            "Receptionist",
            description="We are a systematic trading firm. " + "Alpha research. " * 40,
        )
        self.assertEqual(call.verdict, "reject")
        self.assertEqual(call.reason, "unrelated_occupation")


class SwedishCompounds(unittest.TestCase):
    """Swedish builds occupations by compounding, so token matching alone
    cannot see the job: `chaufför` does not match `skåpbilschaufför`."""

    def test_compound_occupations_are_rejected(self):
        for title in (
            "Skåpbilschaufför Skellefteå, Tidsbegränsad anställning",
            "Jobba som mellanstadielärare på Sveriges mest personliga skola",
            "Undersköterska till natten",
            "Butikssäljare sökes till Vellinge",
        ):
            with self.subTest(title=title):
                self.assertEqual(lexicon.judge(title).verdict, "reject")

    def test_a_short_word_is_not_a_compound(self):
        self.assertIsNone(lexicon.compound(lexicon.normalize("förare")))

    def test_analytiker_is_not_an_occupational_head(self):
        """`kvantitativ analytiker` is the job we are looking for. If a suffix
        rule ever swallowed `-analytiker`, Stockholm would go silent."""
        self.assertIsNone(lexicon.compound(lexicon.normalize("kvantitativ analytiker")))


class PureProgramming(unittest.TestCase):
    """The two-sided rule: an engineering title is judged on whether markets
    appear, and on *where* they appear."""

    def test_engineering_without_markets_is_rejected(self):
        call = lexicon.judge("Senior Backend Engineer, Payments Platform")
        self.assertEqual(call.verdict, "reject")
        self.assertEqual(call.reason, "pure_engineering")

    def test_engineering_with_markets_in_the_title_is_kept(self):
        call = lexicon.judge("Senior Back-End Java Developer — Trading Platforms")
        self.assertEqual(call.verdict, "keep")

    def test_markets_in_the_body_only_reaches_undecided(self):
        """AlphaSense's every backend engineer came out as a markets hire
        because the body describes the product -- "equity research, company
        filings, expert calls" -- not the role."""
        call = lexicon.judge(
            "Staff Software Engineer",
            description="Our universe of content includes equity research, "
            "company filings and expert calls. " * 10,
        )
        self.assertEqual(call.verdict, "undecided")

    def test_a_quant_body_still_keeps_an_engineer(self):
        call = lexicon.judge(
            "Senior Software Engineer, C++",
            description="You will work with researchers on backtesting "
            "infrastructure for statistical arbitrage. " * 5,
        )
        self.assertEqual(call.verdict, "keep")
        self.assertEqual(call.confidence, "strong")


class OrdinaryEnglishIsNotEvidence(unittest.TestCase):
    """`portfolio`, `equity`, `options` and `execution` mean something else in a
    job advertisement, and with them in the markets list every engineer eleven
    venture boards were hiring came out as a markets role."""

    def test_venture_portfolio_language_does_not_rescue(self):
        call = lexicon.judge(
            "Staff Cloud Platform Engineer",
            description="Join one of our portfolio companies. Generous equity "
            "and stock options. Focus on execution. " * 10,
        )
        self.assertEqual(call.verdict, "reject")

    def test_quantitative_skills_boilerplate_does_not_keep(self):
        """"Strong quantitative skills" is in half the job specs ever written."""
        call = lexicon.judge(
            "Regional VP of P&C Operations",
            description="We need strong quantitative skills. " * 30,
        )
        self.assertNotEqual(call.verdict, "keep")


class NonQuantitativeFinance(unittest.TestCase):
    def test_relationship_roles_are_rejected(self):
        for title in (
            "Assistant Relationship Manager, DBS Private Bank",
            "Mortgage Advisor",
            "Personal Financial Consultant",
            "Bilingual Customer Service Associate",
        ):
            with self.subTest(title=title):
                self.assertEqual(lexicon.judge(title).verdict, "reject")

    def test_economists_are_never_rejected_on_a_title(self):
        """The user's own example. `Economist` is quantitative at one firm and
        commentary at the next, so the title alone must not decide it."""
        for title in ("Economist", "Financial Analyst", "Credit Analyst",
                      "Investment Analyst", "Data Scientist"):
            with self.subTest(title=title):
                self.assertEqual(lexicon.judge(title).verdict, "undecided")

    def test_a_body_with_no_markets_language_settles_it(self):
        call = lexicon.judge(
            "Economist",
            description="You will advise municipalities on budget planning "
            "and produce briefing notes for policy staff. " * 10,
        )
        self.assertEqual(call.verdict, "reject")
        self.assertEqual(call.confidence, "weak")

    def test_a_quantitative_body_keeps_the_same_title(self):
        call = lexicon.judge(
            "Economist",
            description="You will build econometric models of order book "
            "dynamics and backtest them. " * 10,
        )
        self.assertEqual(call.verdict, "keep")


class Seniority(unittest.TestCase):
    def test_vice_president_is_a_bank_grade_not_an_officer(self):
        """State Street and Citi stamp VP on five-year hires. Rejecting on it
        would throw away thousands of relevant postings -- and bare `president`
        in the head list did exactly that, because it is a token of it."""
        for title in ("Quantitative Analyst, Vice President",
                      "Digital PM Analyst, Assistant Vice President"):
            with self.subTest(title=title):
                self.assertNotEqual(lexicon.judge(title).reason, "too_senior")

    def test_heads_and_mds_are_rejected(self):
        for title in ("Head of Quantitative Research",
                      "Managing Director, Systematic Strategies"):
            with self.subTest(title=title):
                call = lexicon.judge(title)
                self.assertEqual(call.verdict, "reject")
                self.assertEqual(call.reason, "too_senior")

    def test_a_department_is_not_a_grade(self):
        """`Associate - Fund Governance` sits in a department called "Director
        Services - RFS - CD0303", and was rejected as too senior for it."""
        call = lexicon.judge("Associate – Fund Governance",
                             department="Director Services - RFS - CD0303")
        self.assertNotEqual(call.reason, "too_senior")

    def test_associate_director_is_not_a_director(self):
        self.assertNotEqual(lexicon.judge("Associate Director, Research").reason,
                            "too_senior")


class QuantitativeRolesSurvive(unittest.TestCase):
    """The expensive failure is a false rejection, so this is the class that
    matters most. Every title is one really in the corpus."""

    def test_real_quant_postings_are_kept(self):
        for title in (
            "Quantitative Researcher (Full-Time - PhD+)",
            "Equity Derivatives Quant Developer, Equity Derivatives",
            "Linear Rates Quant (Associate Level)",
            "Quantitative Trader",
            "Senior Software Engineer, Quantitative Research",
            "Graduate Quantitative Trader",
            "Kvantitativ analytiker till Riskkontroll",
            "Execution Quant, Trading",
        ):
            with self.subTest(title=title):
                self.assertEqual(lexicon.judge(title).verdict, "keep")

    def test_a_graduate_role_is_not_a_student_role(self):
        """The user has graduated but has under a year of experience, so
        graduate-track postings are in scope and only a *future* graduation
        date is not."""
        self.assertEqual(lexicon.judge("Graduate Trader").verdict, "keep")

    def test_an_enrolment_requirement_rejects(self):
        call = lexicon.judge(
            "Quantitative Research Intern",
            description="You must be currently enrolled in a PhD programme "
            "and graduating in 2028. " * 5,
        )
        self.assertEqual(call.verdict, "reject")
        self.assertEqual(call.reason, "student_only")


class BoardProfile(unittest.TestCase):
    """A board's own postings are the only honest evidence of whose board it
    is. LaSalle really is a Singapore Capital Markets Services Licensee and its
    domain resolves to `jll.com`, which is 2,021 property-management jobs."""

    def test_a_board_of_somebody_elses_jobs(self):
        profile, evidence = lexicon.board_profile(keep=0, undecided=0, rejected=91)
        self.assertEqual(profile, "non_markets")
        self.assertIn("0/91", evidence)

    def test_a_trading_firms_board(self):
        self.assertEqual(lexicon.board_profile(12, 20, 8)[0], "markets")

    def test_too_few_postings_to_judge(self):
        """The same hole `ats.py` refuses to leave: no answer must be
        distinguishable from a confident wrong one."""
        self.assertIsNone(lexicon.board_profile(0, 0, 3))

    def test_undecided_counts_towards_relevance(self):
        """A board of ambiguous finance titles is a finance employer nobody has
        read yet; a board of housekeepers is not. If undecided did not count,
        this would only measure how many bodies we happened to fetch."""
        self.assertEqual(lexicon.board_profile(0, 50, 10)[0], "markets")


class EveryRejectionCarriesItsReason(unittest.TestCase):
    def test_reasons_are_declared(self):
        """`REASONS` is what a caller enumerates. A reason the rules can emit
        but the tuple does not name is a filter nobody can build a chip for."""
        emitted = set()
        for title, body in (
            ("Receptionist", None),
            ("Marketing Manager", None),
            ("Head of Trading", None),
            ("Relationship Manager", None),
            ("Backend Engineer", None),
            ("Blockchain Developer", None),
            ("Warehouse Picker", "Lift boxes all day in our depot. " * 20),
            ("Ställare", "Du kommer att arbeta i vår produktion. " * 20),
        ):
            call = lexicon.judge(title, description=body)
            if call.reason:
                emitted.add(call.reason)
        self.assertTrue(emitted <= set(lexicon.REASONS), emitted - set(lexicon.REASONS))

    def test_a_rejection_always_says_what_decided_it(self):
        call = lexicon.judge("Corporate Receptionist")
        self.assertEqual(call.evidence, "receptionist")


if __name__ == "__main__":
    unittest.main()
