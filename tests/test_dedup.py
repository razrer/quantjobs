"""The fingerprint two copies of one advertisement share.

The failure this guards is not "duplicates got through" -- it is the opposite
one, a de-duplicator hiding a real opening because two offices were sent the
same boilerplate.
"""

from __future__ import annotations

import unittest

from quantscraper import dedup

BODY = (
    "We are looking for a quantitative researcher to join the desk. You will "
    "build models, backtest them and take them into production. Python is the "
    "working language and the team is small. "
) * 4


class FingerprintTest(unittest.TestCase):
    def test_the_same_advertisement_twice_is_one_key(self):
        """Anradus reposts `Quant Researcher #77900` every five days under a
        new MyCareersFuture id with a byte-identical description. Four cards,
        one job."""
        first = dedup.fingerprint(
            "~anradus pte. ltd.", "Singapore", "Quant Researcher #77900", BODY)
        again = dedup.fingerprint(
            "~anradus pte. ltd.", "Singapore", "Quant Researcher #77900", BODY)
        self.assertEqual(first, again)

    def test_the_same_role_in_two_offices_is_two_keys(self):
        """**The reason the location is in the key.** Jane Street writes one
        description per role and posts it in every office, so hashing the body
        alone merges Hong Kong with London and the London opening disappears --
        a real job hidden by a de-duplicator, which is worse than seeing an
        advertisement twice."""
        hk = dedup.fingerprint("janestreet.com", "Hong Kong", "Software Engineer", BODY)
        ldn = dedup.fingerprint("janestreet.com", "London", "Software Engineer", BODY)
        self.assertNotEqual(hk, ldn)

    def test_two_firms_are_never_one_key(self):
        a = dedup.fingerprint("janestreet.com", "Singapore", "Trader", BODY)
        b = dedup.fingerprint("optiver.com", "Singapore", "Trader", BODY)
        self.assertNotEqual(a, b)

    def test_casing_and_punctuation_do_not_split_a_cluster(self):
        a = dedup.fingerprint("x.com", "Singapore", "Quant Researcher", BODY)
        b = dedup.fingerprint("x.com", "  singapore ", "quant researcher!", BODY)
        self.assertEqual(a, b)

    def test_a_short_body_falls_back_to_the_title(self):
        """`MIN_BODY` exists because a two-line "we are hiring, apply within"
        is identical across postings with nothing else in common."""
        stub, other = "Apply within.", "Send us a CV."
        self.assertEqual(
            dedup.fingerprint("x.com", "SG", "Trader", stub),
            dedup.fingerprint("x.com", "SG", "Trader", other),
        )
        self.assertNotEqual(
            dedup.fingerprint("x.com", "SG", "Trader", stub),
            dedup.fingerprint("x.com", "SG", "Analyst", stub),
        )

    def test_a_missing_description_is_not_a_crash(self):
        self.assertTrue(dedup.fingerprint("x.com", None, "Trader", None))
        self.assertTrue(dedup.fingerprint(None, None, None, None))


class CollapseTest(unittest.TestCase):
    def test_it_keeps_one_and_counts_the_rest(self):
        cards = [{"t": "a", "fp": "X"}, {"t": "b", "fp": "X"}, {"t": "c", "fp": "Y"}]
        out = dedup.collapse(cards)
        self.assertEqual([c["t"] for c in out], ["a", "c"])
        self.assertEqual(out[0]["dup"], 2)

    def test_a_card_standing_alone_carries_no_count(self):
        """`dup` is omitted rather than written as 1, the same rule the rest of
        `data.js` follows for a value on its default."""
        out = dedup.collapse([{"t": "a", "fp": "X"}])
        self.assertNotIn("dup", out[0])

    def test_the_fingerprint_never_reaches_the_page(self):
        out = dedup.collapse([{"t": "a", "fp": "X"}, {"t": "b", "fp": "X"}])
        self.assertNotIn("fp", out[0])

    def test_a_card_with_no_fingerprint_is_never_folded(self):
        cards = [{"t": "a", "fp": None}, {"t": "b", "fp": None}]
        self.assertEqual(len(dedup.collapse(cards)), 2)

    def test_order_is_the_callers(self):
        """`build_data` sorts newest-first before calling this, so keeping the
        first of a cluster keeps the freshest -- a recruiter's oldest repost is
        the one most likely to have been filled."""
        cards = [{"t": "new", "fp": "X"}, {"t": "old", "fp": "X"}]
        self.assertEqual([c["t"] for c in dedup.collapse(cards)], ["new"])


def _card(title, hubs, names, portal, **rest):
    card = {"t": title, "xs": {"t": title, "hubs": frozenset(hubs),
                               "names": tuple(names), "portal": portal}}
    card.update(rest)
    return card


# Fit first, then the firm's own board, then the newest -- the same key
# `build_data` passes.
def _rank(card):
    return ({"apply_now": 4, "strong": 3, "plausible": 2}.get(card.get("fit"), 0),
            0 if card["xs"]["portal"] else 1,
            card.get("posted", ""))


class SameCompanyTest(unittest.TestCase):
    """The test that carries the whole cross-source fold.

    Every pair here is a real one off the board. The `False` half is the half
    that matters: those are two employers who happen to advertise the same
    title in the same city, and folding them would delete somebody's opening.
    """

    SAME = [
        ("BARCLAYS BANK PLC", "Barclays Bank PLC"),
        ("SQUAREPOINT SERVICES SINGAPORE PTE. LTD.", "Squarepoint Ops"),
        ("AIRWALLEX (SINGAPORE) PTE. LTD.", "Airwallex (Netherlands)"),
        ("BROOKFIELD SINGAPORE PTE. LTD.", "Brookfield Singapore"),
        ("Swedbank AB", "Swedbank AB (Publ)"),
        ("STATE STREET FUND SERVICES (SINGAPORE) PTE. LIMITED", "State Street Liquidity"),
        ("BANK OF SINGAPORE LIMITED", "Bank of Singapore"),
        ("EASTSPRING INVESTMENTS (SINGAPORE) LIMITED", "Eastspring Investments"),
        ("TP ICAP MANAGEMENT SERVICES (SINGAPORE) PTE LTD", "TP Icap EU MTF"),
        ("Nordea", "Nordea"),
    ]
    DIFFERENT = [
        ("CUMBERLAND SG PTE. LTD.", "DRW"),
        ("FRAGMENT WORKS PTE. LTD.", "DRW"),
        ("CHEVRON SINGAPORE PTE. LTD.", "Blockchain Capital"),
        ("Amendo", "Ap4"),
        ("Danica Pension - Aktier", "Danske Bank"),
        # The one that proves `board_domains` is load-bearing rather than
        # cosmetic: while Barclays' Workday board was filed under
        # `cards.barclaycardus.com`, the name the fold would have to match was
        # not there and the internship stayed on the board twice.
        ("BARCLAYS BANK PLC", "Barclaycardus"),
    ]

    def test_one_employer_under_two_names(self):
        for left, right in self.SAME:
            with self.subTest(left=left):
                self.assertTrue(dedup.same_company([left], [right]))

    def test_two_employers_are_never_one(self):
        for left, right in self.DIFFERENT:
            with self.subTest(left=left):
                self.assertFalse(dedup.same_company([left], [right]))

    def test_a_lone_generic_word_is_not_an_identity(self):
        """`Capital`, `Global` and `Markets` are half of finance. This is the
        `bamboohr/blackrock` rule: one shared word has to be a name."""
        for left, right in (("Capital Group", "Capital Dynamics"),
                            ("Global Trading Systems", "Global Payments"),
                            ("Markets Media", "Markets Group")):
            with self.subTest(left=left):
                self.assertFalse(dedup.same_company([left], [right]))

    def test_a_shared_word_at_the_wrong_end_is_not_a_match(self):
        """A name reads outside in, so the run has to be a leading one --
        otherwise every `... Capital Management` is every other."""
        self.assertFalse(dedup.same_company(["Tower Research Capital"],
                                            ["Squarepoint Capital"]))

    def test_any_name_on_either_side_may_match(self):
        """A firm's own board is known by whatever the registries called its
        domain, so every name held for it is offered."""
        self.assertTrue(dedup.same_company(
            ["BARCLAYS BANK PLC"], ["Barclaycardus", "Barclays Bank PLC"]))


class CollapseAcrossSourcesTest(unittest.TestCase):
    def test_a_portal_copy_folds_into_the_firms_own_board(self):
        cards = [_card("quant researcher", ["singapore"], ["Squarepoint Ops"], False),
                 _card("quant researcher", ["singapore"],
                       ["SQUAREPOINT SERVICES SINGAPORE PTE. LTD."], True)]
        out = dedup.collapse_across_sources(cards, rank=_rank)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["dup"], 2)

    def test_two_firms_sharing_a_title_are_left_alone(self):
        """The dangerous population, and the reason the firm test exists: 13
        groups on the live board hold three or more firms under `trader`,
        `software engineer`, `quantitative researcher`."""
        cards = [_card("trader", ["singapore"], ["DRW"], False),
                 _card("trader", ["singapore"], ["CUMBERLAND SG PTE. LTD."], True),
                 _card("trader", ["singapore"], ["ITOCHU SINGAPORE PTE LTD"], True)]
        self.assertEqual(len(dedup.collapse_across_sources(cards, rank=_rank)), 3)

    def test_one_firm_advertising_twice_on_one_source_is_left_alone(self):
        """Two seats, not two copies. Within a source the description rule in
        `fingerprint` decides, and Jane Street really does advertise two
        `Software Engineer` openings in one office."""
        cards = [_card("software engineer", ["hong kong"], ["Jane Street"], False),
                 _card("software engineer", ["hong kong"], ["Jane Street"], False)]
        self.assertEqual(len(dedup.collapse_across_sources(cards, rank=_rank)), 2)

    def test_the_same_title_in_another_city_is_another_job(self):
        cards = [_card("quant researcher", ["hong kong"], ["Squarepoint Ops"], False),
                 _card("quant researcher", ["singapore"],
                       ["SQUAREPOINT SERVICES SINGAPORE PTE. LTD."], True)]
        self.assertEqual(len(dedup.collapse_across_sources(cards, rank=_rank)), 2)

    def test_the_survivor_is_the_card_the_board_rates_highest(self):
        """The two copies are tagged separately and disagree: Barclays'
        internship is `apply_now` on Workday, which publishes no description
        for it, and `strong` on MyCareersFuture, which publishes 7,875
        characters. Burying the higher-rated card is the outcome to avoid."""
        own = _card("internship", ["singapore"], ["Barclays Bank PLC"], False, fit="plausible")
        portal = _card("internship", ["singapore"], ["BARCLAYS BANK PLC"], True, fit="apply_now")
        out = dedup.collapse_across_sources([own, portal], rank=_rank)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fit"], "apply_now")

    def test_a_tie_goes_to_the_firms_own_board(self):
        """An aggregator is a discovery net, never the primary content source."""
        own = _card("internship", ["singapore"], ["Barclays Bank PLC"], False, fit="strong",
                    ats="workday")
        portal = _card("internship", ["singapore"], ["BARCLAYS BANK PLC"], True, fit="strong",
                       ats="mycareersfuture")
        out = dedup.collapse_across_sources([own, portal], rank=_rank)
        self.assertEqual(out[0]["ats"], "workday")

    def test_the_closing_date_crosses_over(self):
        """MyCareersFuture publishes one on every row and an ATS almost never
        does, so keeping the ATS card would throw away a real deadline for the
        opening being kept -- on a board that orders on deadlines."""
        own = _card("internship", ["singapore"], ["Barclays Bank PLC"], False, fit="apply_now")
        portal = _card("internship", ["singapore"], ["BARCLAYS BANK PLC"], True,
                       fit="strong", due="2026-09-06")
        out = dedup.collapse_across_sources([own, portal], rank=_rank)
        self.assertEqual(out[0]["due"], "2026-09-06")

    def test_a_date_the_survivor_already_has_is_not_overwritten(self):
        own = _card("internship", ["singapore"], ["Barclays Bank PLC"], False,
                    fit="apply_now", due="2026-10-01")
        portal = _card("internship", ["singapore"], ["BARCLAYS BANK PLC"], True,
                       fit="strong", due="2026-09-06")
        out = dedup.collapse_across_sources([own, portal], rank=_rank)
        self.assertEqual(out[0]["due"], "2026-10-01")

    def test_the_key_never_reaches_the_page(self):
        cards = [_card("a", ["singapore"], ["Nordea"], False),
                 _card("b", ["singapore"], ["Nordea"], True)]
        for card in dedup.collapse_across_sources(cards, rank=_rank):
            self.assertNotIn("xs", card)

    def test_a_card_with_no_key_is_never_folded(self):
        cards = [{"t": "a"}, {"t": "b"}]
        self.assertEqual(len(dedup.collapse_across_sources(cards, rank=_rank)), 2)

    def test_counts_from_the_first_pass_survive_the_second(self):
        """`collapse` runs first and may already have folded reposts into a
        card; the badge has to end up saying the whole number."""
        own = _card("internship", ["singapore"], ["Barclays Bank PLC"], False,
                    fit="apply_now", dup=3)
        portal = _card("internship", ["singapore"], ["BARCLAYS BANK PLC"], True, dup=2)
        out = dedup.collapse_across_sources([own, portal], rank=_rank)
        self.assertEqual(out[0]["dup"], 5)


if __name__ == "__main__":
    unittest.main()
