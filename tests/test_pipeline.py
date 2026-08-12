import unittest
from unittest.mock import patch

from newsweaver.fetcher.base import Article
from newsweaver.pipeline import (
    build_event_clusters,
    build_fact_pack,
    build_quality_report,
    audit_report,
    dedupe_articles,
    normalize_url,
    prepare_articles,
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
        self.assertGreater(len(facts["facts"]), 3)
        self.assertEqual(facts["schema_version"], 2)
        first = facts["facts"][0]
        self.assertEqual(first["id"], first["fact_id"])
        self.assertTrue(first["article_id"].startswith("A"))
        self.assertTrue(first["source_span"])
        self.assertTrue(first["event_id"].startswith("E"))
        self.assertIn("confidence", first)
        self.assertIn("corroborating_sources", first)
        self.assertGreaterEqual(quality["score"], 50)
        self.assertTrue(quality["ready"])

    def test_fact_pack_splits_multiple_numeric_claims_in_one_sentence(self):
        articles = [article("Results", "https://example.com/results", full_text="Revenue grew 30%, profit reached 5 million dollars.")]
        facts = build_fact_pack("Markets", articles)["facts"]
        self.assertTrue(any("Revenue grew 30%" in fact["claim"] for fact in facts))
        self.assertTrue(any("profit reached 5 million" in fact["claim"] for fact in facts))
        self.assertTrue(all("Revenue grew 30%, profit reached 5 million dollars." in fact["source_span"] for fact in facts))

    def test_quality_gate_explains_blockers(self):
        articles = [article("Only item", "https://example.com/1", source="A", full_text="body")]
        quality = build_quality_report("AI", articles, build_fact_pack("AI", articles))
        self.assertFalse(quality["ready"])
        self.assertIn("至少需要 3 篇相关文章", quality["blockers"])
        self.assertIn("至少需要 2 个独立来源", quality["blockers"])

    def test_audit_report_detects_invalid_and_uncited_numbers(self):
        articles = [article("Launch", "https://example.com/1", full_text="Revenue grew 30%.")]
        facts = build_fact_pack("AI", articles)
        audit = audit_report("收入增长 30%。\n有据可查 [F999]", facts)
        self.assertFalse(audit["valid"])
        self.assertEqual(audit["invalid_ids"], ["F999"])
        self.assertTrue(audit["numeric_without_citation"])

    def test_audit_report_checks_support_and_fact_pack_only_claims(self):
        articles = [article("Product Y launch", "https://example.com/1", full_text="Company X announced Product Y on August 10.")]
        facts = build_fact_pack("AI", articles)

        passed = audit_report("Company X announced Product Y on August 10 [F001].", facts)
        unsupported = audit_report("Company X acquired rival Z [F001].", facts)
        uncited = audit_report("Company X announced Product Y.", facts)

        self.assertTrue(passed["passed"])
        self.assertFalse(unsupported["checks"]["citations_support_claims"]["passed"])
        self.assertFalse(uncited["checks"]["fact_pack_only"]["passed"])

    def test_same_source_different_events_do_not_cluster(self):
        articles = [
            article("Company X launches Product Y", "https://example.com/1", source="Reuters", summary="Company X unveiled Product Y."),
            article("Central bank cuts interest rates", "https://example.com/2", source="Reuters", summary="The central bank reduced its policy rate."),
        ]
        self.assertEqual(len(build_event_clusters(articles)), 2)

    def test_different_sources_same_event_cluster_together(self):
        articles = [
            article("Company X launches Product Y on August 10", "https://example.com/1", source="Reuters", summary="Company X announced Product Y on August 10."),
            article("Product Y unveiled by Company X on August 10", "https://example.com/2", source="BBC", summary="Company X launched Product Y on August 10."),
        ]
        clusters = build_event_clusters(articles)
        reversed_clusters = build_event_clusters(list(reversed(articles)))
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["sources"], ["BBC", "Reuters"])
        self.assertEqual(clusters[0]["event_id"], reversed_clusters[0]["event_id"])

        facts = build_fact_pack("AI", articles, event_clusters=clusters)
        self.assertTrue(any("BBC" in fact["corroborating_sources"] for fact in facts["facts"] if fact["source"] == "Reuters"))

    def test_similar_titles_far_apart_do_not_cluster(self):
        recent = article("Company X launches Product Y", "https://example.com/1", source="Reuters")
        old = article("Company X launches Product Y", "https://example.com/2", source="AP")
        recent.published_at = "2026-06-24T00:00:00+00:00"
        old.published_at = "2026-06-10T00:00:00+00:00"
        self.assertEqual(len(build_event_clusters([recent, old])), 2)

    @patch("newsweaver.pipeline.collect_articles")
    def test_prepare_articles_applies_required_words(self, collect):
        collect.return_value = [
            article("AI policy", "https://example.com/1", full_text="AI regulation update"),
            article("AI product", "https://example.com/2", full_text="AI launch update"),
        ]
        result = prepare_articles({}, {"keywords": ["AI"], "required_words": ["regulation"]}, 10)
        self.assertEqual([item.title for item in result], ["AI policy"])


if __name__ == "__main__":
    unittest.main()
