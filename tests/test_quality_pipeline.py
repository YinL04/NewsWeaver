import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from newsweaver.extractor import extract_article_detailed
from newsweaver.evaluation import EVAL_METRICS, evaluate_fixture
from newsweaver.fetcher.base import Article
from newsweaver.llm.prompts import select_facts_for_prompt
from newsweaver.memory.trends import update_claim_lifecycle
from newsweaver.pipeline import build_fact_pack, prepare_articles, rank_articles


def make_article(title, url, source="Source", published="2026-06-24T00:00:00+00:00", body="AI chip update"):
    return Article(title, url, source, published, body, body)


class RankingTest(unittest.TestCase):
    def test_ranking_covers_distinct_events_before_duplicates(self):
        articles = [
            make_article("Company X launches AI chip Y", "https://a.example/1", "Reuters"),
            make_article("AI chip Y launched by Company X", "https://b.example/2", "BBC"),
            make_article("Government approves new AI safety rules", "https://c.example/3", "AP"),
            make_article("Company X launches AI chip Y details", "https://d.example/4", "Reuters"),
        ]

        ranked = rank_articles(articles, ["AI"])

        self.assertTrue(any("safety" in item.title for item in ranked[:2]))
        self.assertTrue(all("final_score" in item.metadata["ranking"] for item in ranked))
        self.assertTrue(all("source_quality" in item.metadata["ranking"] for item in ranked))

    def test_freshness_is_a_multiplicative_component(self):
        old = make_article("AI policy update", "https://a.example/old", published="2026-06-01T00:00:00+00:00")
        new = make_article("AI product update", "https://a.example/new", published="2026-06-24T00:00:00+00:00")
        ranked = rank_articles([old, new], ["AI"])
        self.assertEqual(ranked[0], new)
        self.assertGreater(new.metadata["ranking"]["freshness"], old.metadata["ranking"]["freshness"])


class ExtractionTest(unittest.TestCase):
    def test_extraction_keeps_full_text_canonical_url_and_cache_metadata(self):
        response = Mock()
        response.text = (
            '<html><head><link rel="canonical" href="/canonical"></head><body><article>'
            + ("Important reporting sentence. " * 240)
            + "</article></body></html>"
        )
        response.url = "https://example.com/original"
        response.status_code = 200
        response.apparent_encoding = "utf-8"
        response.encoding = "utf-8"
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tmp, patch("newsweaver.extractor.requests.Session.get", return_value=response) as get:
            first = extract_article_detailed("https://example.com/story", cache_dir=Path(tmp))
            second = extract_article_detailed("https://example.com/story", cache_dir=Path(tmp))

        self.assertGreater(len(first.text), 2000)
        self.assertEqual(first.metadata["canonical_url"], "https://example.com/canonical")
        self.assertFalse(first.metadata["cached"])
        self.assertTrue(second.metadata["cached"])
        self.assertEqual(get.call_count, 1)

    def test_extraction_retries_and_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "newsweaver.extractor.requests.Session.get",
            side_effect=requests.RequestException("timeout"),
        ), patch("newsweaver.extractor.time.sleep"):
            result = extract_article_detailed(
                "https://example.com/fail",
                max_retries=2,
                cache_dir=Path(tmp),
                cache_max_age=timedelta(0),
            )
        self.assertEqual(result.text, "")
        self.assertEqual(result.metadata["status"], "failed")
        self.assertEqual(result.metadata["attempts"], 3)

    @patch("newsweaver.pipeline.collect_articles")
    @patch("newsweaver.extractor.extract_article_detailed", side_effect=RuntimeError("parser failed"))
    def test_one_extraction_failure_does_not_crash_pipeline(self, _extract, collect):
        collect.return_value = [Article("AI item", "https://example.com/1", "A", "2026-06-24T00:00:00+00:00", "fallback summary")]
        result = prepare_articles({}, {"keywords": ["AI"]}, 1)
        self.assertEqual(result[0].full_text, "fallback summary")
        self.assertEqual(result[0].metadata["extraction"]["status"], "failed")


class PromptBudgetTest(unittest.TestCase):
    def test_high_risk_tail_claim_survives_prompt_budget_selection(self):
        body = " ".join(f"Routine context sentence {index}." for index in range(25))
        body += " Revenue reached 99 million dollars in the final quarter."
        article = make_article("Long report", "https://example.com/long", body=body)
        facts = build_fact_pack("AI", [article])["facts"]
        selected = select_facts_for_prompt(facts, max_chars=1200)
        self.assertTrue(any("99 million" in fact["claim"] for fact in selected))


class ClaimLifecycleTest(unittest.TestCase):
    def test_claims_can_be_fulfilled_disputed_superseded_and_expired(self):
        prior = {
            "recent": [
                {
                    "date": "2026-06-01",
                    "claims": [
                        {"claim_id": "P1", "claim": "Company X plans to launch Product Y in Q4.", "status": "new", "observed_at": "2026-06-01T00:00:00+00:00"},
                        {"claim_id": "P2", "claim": "Company X will launch Product Z.", "status": "new", "observed_at": "2026-06-01T00:00:00+00:00"},
                        {"claim_id": "P3", "claim": "Revenue reached 10 million dollars.", "status": "new", "observed_at": "2026-06-01T00:00:00+00:00"},
                        {"claim_id": "P4", "claim": "An old unresolved claim.", "status": "new", "observed_at": "2020-01-01T00:00:00+00:00"},
                    ],
                }
            ]
        }
        current = {
            "claims": [
                {"claim_id": "C1", "claim": "Company X launched Product Y in Q4.", "status": "new"},
                {"claim_id": "C2", "claim": "Company X will not launch Product Z.", "status": "new"},
                {"claim_id": "C3", "claim": "Revenue was updated to 12 million dollars.", "status": "new"},
            ]
        }

        update_claim_lifecycle(prior, current)
        statuses = {claim["claim_id"]: claim["status"] for claim in prior["recent"][0]["claims"]}

        self.assertEqual(statuses["P1"], "fulfilled")
        self.assertEqual(statuses["P2"], "disputed")
        self.assertEqual(statuses["P3"], "superseded")
        self.assertEqual(statuses["P4"], "expired")


class EvaluationTest(unittest.TestCase):
    def test_fixed_eval_fixture_reports_all_required_metrics(self):
        fixture_path = Path(__file__).parent / "fixtures" / "eval" / "baseline.json"
        result = evaluate_fixture(json.loads(fixture_path.read_text(encoding="utf-8")))
        self.assertTrue(set(EVAL_METRICS).issubset(result["metrics"]))
        self.assertEqual(result["metrics"]["citation_validity"], 1.0)
        self.assertEqual(result["metrics"]["important_event_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
