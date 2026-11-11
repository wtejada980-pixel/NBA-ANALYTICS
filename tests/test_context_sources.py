import sys
import unittest
from unittest.mock import patch
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
            {"title": "NBA game recap", "url": "https://www.foxsports.com/stories/nba/recap",
             "published": "Tue, 10 Nov 2026 20:00:00 GMT"},
            {"title": "NBA Finals odds update", "url": "https://www.foxsports.com/stories/nba/odds",
             "published": "Tue, 10 Nov 2026 20:00:00 GMT"},
            {"title": "NFL game recap", "url": "https://www.foxsports.com/stories/nfl/recap",
             "published": "Tue, 10 Nov 2026 20:00:00 GMT"},
        ]
        self.assertEqual([item["title"] for item in context_sources.filter_fox_nba(items)],
                         ["NBA game recap"])

    def test_old_headlines_are_not_marked_as_current(self):
        self.assertFalse(context_sources.is_recent_news({
            "published": "Thu, 13 Aug 2026 18:14:14 -0500"
        }))

    def test_nba_headline_filter_requires_clear_basketball_context(self):
        self.assertTrue(context_sources.is_nba_headline(
            "Phoenix Suns vs Los Angeles Clippers. Live updates, NBA analysis"))
        self.assertTrue(context_sources.is_nba_headline(
            "NBA Trade Machine Rankings: Nikola Jokic and Domantas Sabonis"))
        self.assertFalse(context_sources.is_nba_headline(
            "Technology company announces new wireless partnership"))

    def test_google_news_discards_vague_and_technology_results(self):
        feed = b'''<rss><channel>
          <item><title>Phoenix Suns vs Los Angeles Clippers NBA analysis</title>
            <link>https://news.google.com/rss/articles/abc</link><pubDate>Wed, 11 Nov 2026 20:00:00 GMT</pubDate>
          </item>
          <item><title>Charlotte Hornets hoop NBA wireless first with Wi-Fi 7</title>
            <link>https://news.google.com/rss/articles/def</link><pubDate>Wed, 11 Nov 2026 20:00:00 GMT</pubDate>
          </item>
          <item><title>(LIVESTREA.Ms!) Phoenix Suns vs San Antonio Spurs Live Free NBA Basketball Game On TV Channel - SooLeader.com</title>
            <source>SooLeader.com</source><link>https://news.google.com/rss/articles/jkl</link>
            <pubDate>Wed, 11 Nov 2026 20:00:00 GMT</pubDate>
          </item>
          <item><title>Business leaders meet in Milwaukee</title>
            <link>https://news.google.com/rss/articles/ghi</link><pubDate>Wed, 11 Nov 2026 20:00:00 GMT</pubDate>
          </item>
        </channel></rss>'''
        with patch.object(context_sources, "is_recent_news", return_value=True):
            items = context_sources.google_nba_news(lambda _url: feed)
        self.assertEqual([item["title"] for item in items],
                         ["Phoenix Suns vs Los Angeles Clippers NBA analysis"])

    def test_feed_removes_publisher_suffix_without_losing_attribution(self):
        feed = b'''<rss><channel><item>
          <title>NBA game recap - Sports Network</title>
          <source>Sports Network</source>
          <link>https://news.google.com/rss/articles/abc</link>
        </item></channel></rss>'''
        item = context_sources.feed_titles(feed, 1, "Google News")[0]
        self.assertEqual(item["title"], "NBA game recap")
        self.assertEqual(item["source"], "Sports Network")

    def test_source_label_reports_only_feeds_with_headlines(self):
        result = context_sources.collect([], [], get_token=lambda: "",
            get_fox_news=lambda: [{"title": "NBA story", "feed": "Google News"}])
        self.assertEqual(result["news_source"], "Google News RSS")


if __name__ == "__main__":
    unittest.main()
