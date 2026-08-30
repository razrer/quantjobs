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


if __name__ == "__main__":
    unittest.main()
