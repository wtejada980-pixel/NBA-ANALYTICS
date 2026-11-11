import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import context_sources


class FoxNewsTests(unittest.TestCase):
    def test_fox_nba_feed_titles_keep_attribution_and_publish_date(self):
        feed = b'''<?xml version="1.0"?><rss><channel><item>
          <title>NBA headline</title>
          <link>https://www.foxsports.com/stories/nba/test-story</link>
          <pubDate>Tue, 10 Nov 2026 20:00:00 GMT</pubDate>
        </item></channel></rss>'''
        requested = []

        def request(url):
            requested.append(url)
            return feed

        items = context_sources.fox_nba_news(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "FOX Sports")
        self.assertEqual(items[0]["title"], "NBA headline")
        self.assertIn("tags=fs%2Fnba", requested[0])

    def test_feed_discards_non_https_and_unapproved_domains(self):
        feed = b'''<rss><channel>
          <item><title>Bad scheme</title><link>http://www.foxsports.com/a</link></item>
          <item><title>Bad host</title><link>https://example.com/story</link></item>
          <item><title>Good</title><link>https://www.foxsports.com/stories/nba/good</link></item>
        </channel></rss>'''
        items = context_sources.feed_titles(feed, 10, "FOX Sports")
        self.assertEqual([item["title"] for item in items], ["Good"])

    def test_fox_news_excludes_betting_and_other_sports(self):
        items = [
            {"title": "NBA game recap", "url": "https://www.foxsports.com/stories/nba/recap"},
            {"title": "NBA Finals odds update", "url": "https://www.foxsports.com/stories/nba/odds"},
            {"title": "NFL game recap", "url": "https://www.foxsports.com/stories/nfl/recap"},
        ]
        self.assertEqual([item["title"] for item in context_sources.filter_fox_nba(items)],
                         ["NBA game recap"])


if __name__ == "__main__":
    unittest.main()
