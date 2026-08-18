"""Regression tests for board discovery.

The failure this pins is a *plausible* wrong answer. A guessed token that
happens to name a live board yields a well-formed resolution, a real feed and
somebody else's postings -- the `heyrowan` failure from Stage 5, which filed 90
jewellery-retail listings under a credit manager's domain. Two such boards
turned up inside the first sixty candidates here, so the corroboration rule is
the module and everything else is plumbing.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest
from unittest import mock

from quantscraper import ats, discover, extract, resolve
from quantscraper.discover import Discovery
from quantscraper.models import Job


def job(title: str, description: str = "", department: str | None = None) -> Job:
    return Job(
        ats="greenhouse",
        token="whatever",
        job_id="1",
        title=title,
        url="https://boards.greenhouse.io/whatever/jobs/1",
        department=department,
        description=description,
    )


class TokenCandidateTest(unittest.TestCase):
    def test_the_run_together_full_name_is_tried_first(self):
        """Board tokens are overwhelmingly the whole name with the spaces out.

        `quberesearchandtechnologies` is a real board and no shorter form of
        that firm's name reaches it.
        """
        candidates = discover.token_candidates("qube research and technologies")
        self.assertEqual(candidates[0], "quberesearchandtechnologies")

    def test_short_tokens_are_never_offered(self):
        """A three-letter token is a coin flip that costs a false board.

        `_needles` will not build a needle shorter than four characters either,
        so such a token could not be verified even if it were probed.
        """
        for candidate in discover.token_candidates("sig susquehanna"):
            self.assertGreaterEqual(len(candidate), discover._MIN_TOKEN)

    def test_a_three_letter_token_is_allowed(self):
        """IMC's board is `imc`, and a four-character floor cost 165 postings.

        Token length is not the safety check -- corroboration is. The needle
        here is `imc trading`, which is long enough to mean something.
        """
        self.assertIn("imc", discover.token_candidates("imc trading"))


class ProbePlanTest(unittest.TestCase):
    def test_the_plan_is_bounded_however_many_names_are_offered(self):
        """One firm must not be able to spend the whole sweep's budget."""
        plan = discover.probe_plan(
            tuple(f"alpha{n} beta{n} gamma{n}" for n in range(10))
        )
        self.assertLessEqual(len(plan), discover._MAX_TOKENS)

    def test_a_token_reached_from_two_names_is_probed_once(self):
        """`Akuna` and `AKUNA CAPITAL LLC` both offer `akuna`."""
        plan = discover.probe_plan(("Akuna", "AKUNA CAPITAL LLC"))
        tokens = [token for _, token in plan]
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertIn("akunacapital", tokens)

    def test_the_full_legal_name_supplies_the_token_the_short_one_cannot(self):
        """The whole reason a target carries more than one name.

        The roster says `Squarepoint`; the board is `squarepointcapital`.
        """
        short = [token for _, token in discover.probe_plan(("Squarepoint",))]
        self.assertNotIn("squarepointcapital", short)

        both = [
            token
            for _, token in discover.probe_plan(
                ("Squarepoint", "Squarepoint Capital LLP")
            )
        ]
        self.assertIn("squarepointcapital", both)

    def test_corroboration_uses_the_name_the_token_came_from(self):
        """A wider search must not become a looser test.

        Each token is paired with the normalized name that produced it, so the
        needle checked against a board is the one for that spelling.
        """
        plan = discover.probe_plan(("Qube", "Qube Research and Technologies"))
        by_token = dict((token, name) for name, token in plan)
        self.assertEqual(by_token["qube"], "qube")
        self.assertEqual(
            by_token["quberesearchandtechnologies"], "qube research and technologies"
        )


class CorroborationTest(unittest.TestCase):
    def test_a_board_naming_the_firm_is_accepted(self):
        evidence = discover.corroborate(
            "jane street",
            [job("Quantitative Trader", "Jane Street is a research-driven firm.")],
            "Jane Street",
        )
        self.assertIsNotNone(evidence)
        self.assertIn("jane street", evidence)

    def test_a_live_board_for_another_firm_is_rejected(self):
        """`greenhouse/cfm` is a real board of nine postings.

        The first three are `Account Executive - Air Distribution`. It is a
        heating company, and nothing about the token says so.
        """
        self.assertIsNone(
            discover.corroborate(
                "capital fund management",
                [
                    job("Account Executive - Air Distribution"),
                    job("Account Executive - End User Sales"),
                ],
                None,
            )
        )

    def test_one_word_of_a_multi_word_name_is_not_enough(self):
        """The weak-needle rule from `domains.py`, carried down a layer.

        A posting mentioning "radix" proves nothing about Radix Trading -- and
        `recruitee/radix` is a live board belonging to somebody else.
        """
        self.assertIsNone(
            discover.corroborate(
                "radix trading",
                [job("Forward Deployed Engineer (API & Data)", "Radix builds APIs.")],
                None,
            )
        )

    def test_the_token_cannot_prove_itself(self):
        """Evidence must be a spaced phrase, never the run-together guess.

        `marketfrance.com` verified itself by printing the domain we had just
        guessed. A board whose every posting URL carries the token would do the
        same thing if the URL were read.
        """
        self.assertIsNone(
            discover.corroborate(
                "akuna capital",
                [
                    Job(
                        ats="greenhouse",
                        token="akunacapital",
                        job_id="1",
                        title="Broker Trader",
                        url="https://boards.greenhouse.io/akunacapital/jobs/1",
                        description="A trading firm.",
                    )
                ],
                None,
            )
        )

    def test_the_employer_naming_itself_in_a_title_counts(self):
        """The other side of the same rule -- this one must still pass.

        "Akuna Capital's Talent Community" is the firm writing its own name,
        which is evidence. The token `akunacapital` is not, and the space is
        the whole difference between them.
        """
        evidence = discover.corroborate(
            "akuna capital", [job("Akuna Capital's Talent Community")], None
        )
        self.assertIsNotNone(evidence)


class ProbeTest(unittest.TestCase):
    def test_an_empty_board_is_treated_as_absent(self):
        """A token yielding nothing today would poll silence forever."""
        with mock.patch.dict(extract.EXTRACTORS, {"greenhouse": lambda token: []}):
            self.assertIsNone(discover.probe("greenhouse", "nobody"))

    def test_a_broken_board_does_not_raise(self):
        def explode(token):
            raise ValueError("malformed payload")

        with mock.patch.dict(extract.EXTRACTORS, {"greenhouse": explode}):
            self.assertIsNone(discover.probe("greenhouse", "nobody"))

    def test_discovery_stops_at_the_first_proven_board(self):
        calls: list[str] = []

        def extractor(token):
            calls.append(token)
            return [job("Quantitative Researcher", "Optiver is a market maker.")]

        with mock.patch.dict(
            extract.EXTRACTORS, {name: extractor for name in discover.DISCOVERABLE}
        ), mock.patch.object(discover, "board_name", return_value=None):
            found = discover.discover_name("Optiver", "optiver.com")

        self.assertTrue(found.found)
        self.assertEqual(found.ats, discover.DISCOVERABLE[0])
        self.assertEqual(len(calls), 1)

    def test_a_miss_records_why_rather_than_nothing(self):
        """"Nothing found" and "found three boards owned by other firms" are
        different answers, and the second one is how the next reader learns."""
        with mock.patch.dict(
            extract.EXTRACTORS,
            {name: lambda token: [job("Air Conditioning Installer")]
             for name in discover.DISCOVERABLE},
        ), mock.patch.object(discover, "board_name", return_value=None):
            found = discover.discover_name("Capital Fund Management", "cfm.fr")

        self.assertFalse(found.found)
        self.assertIn("named another firm", found.evidence)


class RecordTest(unittest.TestCase):
    """A discovery may fill an empty slot. It may never displace a live board.

    The domain attached to a discovery comes from a fuzzy roster match --
    "Millennium" finds *Millennium New Horizons Management* at `mnh.vc`. A
    wrong domain mis-attributes postings, which is cheap. Overwriting a working
    board with them loses a feed, which is the false merge principle 3 refuses.
    """

    def setUp(self):
        from quantscraper import db

        self.connection = db.connect(":memory:")
        self.connection.executescript(discover.SCHEMA)
        self.connection.executescript(ats.SCHEMA)

    def tearDown(self):
        self.connection.close()

    def tier(self, domain: str):
        return self.connection.execute(
            "SELECT ats, token, tier FROM ats_resolution WHERE domain = ?", (domain,)
        ).fetchone()

    def test_a_working_board_is_left_alone(self):
        self.connection.execute(
            "INSERT INTO ats_resolution (domain, ats, token, tier, checked_at)"
            " VALUES ('mnh.vc', 'greenhouse', 'therealboard', 'A', '2026-01-01')"
        )
        discover.record(
            self.connection,
            [Discovery("Millennium", "mnh.vc", "greenhouse", "millennium", "proof")],
        )
        self.assertEqual(self.tier("mnh.vc")["token"], "therealboard")

    def test_a_tier_b_row_is_upgraded(self):
        self.connection.execute(
            "INSERT INTO ats_resolution (domain, tier, checked_at)"
            " VALUES ('janestreet.com', 'B', '2026-01-01')"
        )
        discover.record(
            self.connection,
            [Discovery("Jane Street", "janestreet.com", "greenhouse", "janestreet", "proof")],
        )
        row = self.tier("janestreet.com")
        self.assertEqual((row["tier"], row["token"]), ("A", "janestreet"))

    def test_tier_a_with_no_token_is_filled_in(self):
        """AQR sat in exactly this state with 48 live postings behind it."""
        self.connection.execute(
            "INSERT INTO ats_resolution (domain, ats, token, tier, checked_at)"
            " VALUES ('aqr.com', 'greenhouse', NULL, 'A', '2026-01-01')"
        )
        discover.record(
            self.connection,
            [Discovery("AQR", "aqr.com", "greenhouse", "aqr", "proof")],
        )
        self.assertEqual(self.tier("aqr.com")["token"], "aqr")

    def test_a_platform_domain_is_never_attached(self):
        """Point72's 229 postings landed on `linkedin.com` before this.

        Over 4,000 Form ADV filers give a LinkedIn page as their website, so
        the first firm to be discovered there would own a host belonging to
        everybody -- and the no-clobber guard would then lock it in.
        """
        for junk in ("linkedin.com", "uk.linkedin.com", "x.com", "youtube.com"):
            self.assertTrue(resolve.is_platform_domain(junk), junk)
        for real in ("janestreet.com", "linkedin-partners.com", "tower-research.com"):
            self.assertFalse(resolve.is_platform_domain(real), real)

    def test_a_miss_is_cached_so_it_is_not_re_probed(self):
        discover.record(self.connection, [Discovery("Nobody", "nobody.com", None, None, "no board")])
        row = self.connection.execute(
            "SELECT ats, evidence FROM board_lookups WHERE query = 'Nobody'"
        ).fetchone()
        self.assertIsNone(row["ats"])
        self.assertEqual(row["evidence"], "no board")
        self.assertIsNone(self.tier("nobody.com"))


class WorkdayHostTest(unittest.TestCase):
    """Two hosts, three parts, and they are ordered differently."""

    def test_the_usual_host_still_yields_a_three_part_token(self):
        found = ats.fingerprint(
            'src="https://lseg.wd3.myworkdayjobs.com/en-US/LSEG_Careers/job/x"'
        )
        self.assertEqual(found[0], "workday")
        self.assertEqual(found[1], "lseg|wd3|LSEG_Careers")

    def test_myworkdaysite_puts_the_tenant_in_the_path(self):
        """Brevan Howard, which tiered B with fifteen live postings behind it.

        Joining these captures by position produced `wd3|brevanhoward|
        BH_ExternalCareers` -- a well-formed token addressing nothing.
        """
        found = ats.fingerprint(
            'href="https://wd3.myworkdaysite.com/recruiting/brevanhoward'
            '/BH_ExternalCareers"'
        )
        self.assertEqual(found[0], "workday")
        self.assertEqual(
            found[1], "brevanhoward|wd3|BH_ExternalCareers|myworkdaysite.com"
        )

    def test_both_tokens_build_the_endpoint_they_came_from(self):
        seen: list[str] = []

        def capture(url, body, **kwargs):
            seen.append(url)
            return b'{"total": 0, "jobPostings": []}'

        with mock.patch.object(extract.http, "post_json", capture):
            extract.workday("lseg|wd3|LSEG_Careers")
            extract.workday("brevanhoward|wd3|BH_ExternalCareers|myworkdaysite.com")

        self.assertEqual(
            seen[0],
            "https://lseg.wd3.myworkdayjobs.com/wday/cxs/lseg/LSEG_Careers/jobs",
        )
        self.assertEqual(
            seen[1],
            "https://wd3.myworkdaysite.com/wday/cxs/brevanhoward"
            "/BH_ExternalCareers/jobs",
        )

    def test_a_token_that_is_not_pollable_is_still_refused(self):
        with self.assertRaises(ValueError):
            extract.workday("brevanhoward|wd3")


if __name__ == "__main__":
    unittest.main()


class CorroborationFieldsTest(unittest.TestCase):
    """Which posting fields may prove a board belongs to a firm."""

    def _job(self, **kwargs):
        from quantscraper.models import Job

        base = dict(ats="hailey", token="coeli", job_id="1", title="Private Equity Associate")
        base.update(kwargs)
        return Job(**base)

    def test_the_employing_entity_in_the_location_field_corroborates(self):
        """Hailey HR labels every card with a workplace, not a city.

        Coeli's eight postings say `Coeli Stockholm HK` and name the firm
        nowhere else -- the titles are ordinary and the bodies are Swedish
        prose about the role. Without the location the board was rejected as
        belonging to another firm, which is the opposite of the truth.
        """
        jobs = [self._job(location="Coeli Stockholm HK")]
        self.assertIsNotNone(discover.corroborate("coeli", jobs, None))

    def test_the_url_still_never_corroborates(self):
        """Every posting on a guessed board carries the guess in its link."""
        jobs = [self._job(url="https://coeli.careers.haileyhr.app/x", location="Stockholm")]
        self.assertIsNone(discover.corroborate("coeli", jobs, None))

    def test_a_lone_word_of_a_multi_word_firm_is_still_not_proof(self):
        """`_needles` grades it weak, which is what contains the location rule."""
        jobs = [self._job(location="Capital Stockholm")]
        self.assertIsNone(discover.corroborate("capital fund management", jobs, None))


class OneWordFirmNameTest(unittest.TestCase):
    """A one-word firm name is always a strong needle, and that is the hole.

    `bamboohr/blackrock` is BlackRock Asphalt of Tampa -- a live board, a
    well-formed token, and the wrong company. Its postings contain "blackrock"
    because that *is* the company's name, so no amount of text matching
    separates it from BlackRock the asset manager.
    """

    def _job(self, title, **kwargs):
        from quantscraper.models import Job

        base = dict(ats="bamboohr", token="blackrock", job_id="1", title=title)
        base.update(kwargs)
        return Job(**base)

    def test_an_asphalt_board_does_not_corroborate_an_asset_manager(self):
        jobs = [
            self._job("Asphalt Laborer - BlackRock Asphalt", location="Tampa"),
            self._job("Lowboy Driver", location="Tampa"),
            self._job("Milling Machine Operator - Tampa, FL", location="Tampa"),
        ]
        self.assertIsNone(discover.corroborate("blackrock", jobs, None))

    def test_a_one_word_firm_with_finance_postings_still_corroborates(self):
        """Voleon and Coeli are both one-word names and both are correct."""
        jobs = [
            self._job(
                "Senior Software Engineer, Trading Strategies",
                description="Voleon is a technology company applying machine "
                "learning to investment management.",
            ),
            self._job("Quantitative Researcher", description="At Voleon we..."),
        ]
        self.assertIsNotNone(discover.corroborate("voleon", jobs, None))

    def test_ordinary_asset_management_titles_are_enough(self):
        """Coeli's board is mostly `undecided`, and one row rejects on `chef`.

        Swedish for *manager*. Requiring a `keep` verdict would throw the board
        away; requiring merely "some rejection" would keep the asphalt one.
        What separates them is that these carry evidence at all.
        """
        jobs = [
            self._job("Private Equity Associate", location="Coeli Stockholm HK"),
            self._job("Investor Relations Analyst", location="Coeli Stockholm HK"),
            self._job(
                "Operativ chef for Business & Risk Operations",
                location="Coeli Stockholm HK",
            ),
        ]
        self.assertIsNotNone(discover.corroborate("coeli", jobs, None))

    def test_a_multi_word_needle_is_not_second_guessed(self):
        """The industry read only guards the case `_needles` leaves open."""
        jobs = [
            self._job(
                "Asphalt Laborer",
                description="Old Mission Capital is hiring.",
            )
        ]
        self.assertIsNotNone(
            discover.corroborate("old mission capital", jobs, None)
        )
