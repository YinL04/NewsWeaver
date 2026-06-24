import unittest

from newsweaver.fetcher.base import Article
from newsweaver.pipeline import (
    build_fact_pack,
    build_quality_report,
    dedupe_articles,
    normalize_url,
    rank_articles,
)


def article(title, url, source="source", summary="AI chip update", full_text=""):
    return Article(
        title=title,
        url=url,
        source=source,
        published_at="2026-06-24T00:00:00+00:00",
        summary=summary,
        full_text=full_text,
    )


class PipelineTest(unittest.TestCase):
    def test_normalize_url_removes_tracking_params(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.com/news/?utm_source=rss&id=1#frag"),
            "https://example.com/news?id=1",
        )

    def test_dedupe_articles_prefers_richer_content(self):
        short = article("Same title", "https://example.com/a?utm_source=rss", full_text="short")
        rich = article("Same title", "https://example.com/a", full_text="much longer article body")

        result = dedupe_articles([short, rich])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].full_text, "much longer article body")

    def test_rank_articles_uses_keyword_relevance(self):
        low = article("Market note", "https://example.com/1", summary="general update")
        high = article("NVIDIA AI chip launch", "https://example.com/2", summary="AI chip update")

        result = rank_articles([low, high], ["NVIDIA", "AI chip"])

        self.assertEqual(result[0].title, "NVIDIA AI chip launch")

    def test_fact_pack_and_quality_report(self):
        articles = [
            article("NVIDIA AI chip launch", "https://example.com/1", source="A", full_text="NVIDIA released a new AI chip. It targets data centers."),
            article("AMD update", "https://example.com/2", source="B", full_text="AMD shared a product roadmap."),
            article("Cloud demand", "https://example.com/3", source="C", summary="Cloud providers increased AI infrastructure spending."),
        ]

        facts = build_fact_pack("AI", articles)
        quality = build_quality_report("AI", articles, facts)

        self.assertEqual(facts["article_count"], 3)
        self.assertEqual(facts["source_count"], 3)
        self.assertEqual(len(facts["facts"]), 3)
        self.assertGreaterEqual(quality["score"], 50)


if __name__ == "__main__":
    unittest.main()
