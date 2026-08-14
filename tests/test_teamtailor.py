"""Regression tests for the Teamtailor extractor.

Teamtailor is the system this project singled out as load-bearing: it is what
Stockholm and Copenhagen mid-market firms hire through, and no generic scraper
covers it. The fields tested here are the ones that make a posting rankable --
without `location` a Nordic board is just noise in a US-dominated table.

Run with: python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest
from unittest import mock

from quantscraper import extract

_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel>
    <title>Pareto Securities</title>
    <link>https://paretosecurities.teamtailor.com/jobs</link>
    <item>
      <title>Quantitative Analyst</title>
      <description>&lt;p&gt;Signal &lt;b&gt;research&lt;/b&gt;.&lt;/p&gt;</description>
      <pubDate>Tue, 11 Aug 2026 10:27:38 +0200</pubDate>
      <link>https://paretosecurities.teamtailor.com/jobs/8203309-quant</link>
      <guid>29c943d1-1a07-46ee-a9ce-033c2bc56d5f</guid>
      <tt:locations>
        <tt:location>
          <tt:name></tt:name>
          <tt:city>Stockholm</tt:city>
          <tt:country>Sweden</tt:country>
        </tt:location>
      </tt:locations>
      <tt:department>Markets</tt:department>
    </item>
    <item>
      <title>Accounting Controller</title>
      <pubDate>Mon, 10 Aug 2026 09:00:00 +0200</pubDate>
      <link>https://paretosecurities.teamtailor.com/jobs/8203310-accounting</link>
      <guid>7d1c1a4e-0000-4000-8000-000000000000</guid>
      <tt:locations>
      </tt:locations>
      <tt:department/>
    </item>
  </channel>
</rss>
""".encode()

_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations">
  <channel><title>ABG Sundal Collier</title></channel>
</rss>
"""


class TeamtailorTest(unittest.TestCase):
    def _jobs(self, body: bytes):
        with mock.patch.object(extract.http, "get", return_value=body):
            return extract.teamtailor("paretosecurities")

    def test_reads_the_fields_a_posting_is_ranked_on(self):
        job = self._jobs(_FEED)[0]

        self.assertEqual(job.ats, "teamtailor")
        self.assertEqual(job.job_id, "29c943d1-1a07-46ee-a9ce-033c2bc56d5f")
        self.assertEqual(job.title, "Quantitative Analyst")
        self.assertEqual(job.url, "https://paretosecurities.teamtailor.com/jobs/8203309-quant")
        self.assertEqual(job.department, "Markets")
        self.assertEqual(job.description, "Signal research .")

    def test_location_comes_from_the_namespaced_extension(self):
        """`tt:` is a namespace, so a plain `find("tt:city")` finds nothing and
        every Nordic posting silently loses the field this project ranks on."""
        self.assertEqual(self._jobs(_FEED)[0].location, "Stockholm, Sweden")

    def test_an_empty_locations_block_is_none_not_blank(self):
        self.assertIsNone(self._jobs(_FEED)[1].location)
        self.assertIsNone(self._jobs(_FEED)[1].department)

    def test_a_board_with_no_openings_is_not_a_failure(self):
        """Unlike a broken parser, a firm that is simply not hiring returns
        zero items with HTTP 200, and that is a true answer."""
        self.assertEqual(self._jobs(_EMPTY), [])

    def test_a_response_without_a_channel_is_loud(self):
        with self.assertRaises(ValueError):
            self._jobs(b"<rss version='2.0'></rss>")

    def test_it_is_registered(self):
        self.assertIs(extract.EXTRACTORS["teamtailor"], extract.teamtailor)


if __name__ == "__main__":
    unittest.main()
