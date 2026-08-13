import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from newsweaver.fetcher.base import Article
from newsweaver.generator import audit_and_repair_report, run_generate
from newsweaver.pipeline import build_fact_pack


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate(self, _system, _user, model=None):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return "Company X stated revenue was 99 billion dollars without evidence."


def sample_articles():
    return [
        Article("Product Y launch", "https://a.example/1", "Reuters", "2026-06-24T00:00:00+00:00", "Company X announced Product Y on August 10.", "Company X announced Product Y on August 10."),
        Article("Product Y unveiled", "https://b.example/2", "BBC", "2026-06-24T01:00:00+00:00", "Company X launched Product Y on August 10.", "Company X launched Product Y on August 10."),
        Article("Market context", "https://c.example/3", "AP", "2026-06-24T02:00:00+00:00", "Analysts discussed demand for Product Y.", "Analysts discussed demand for Product Y."),
    ]


class GenerationAuditTest(unittest.TestCase):
    def test_failed_audit_is_repaired_and_audited_again(self):
        facts = build_fact_pack("AI", sample_articles()[:1])
        llm = FakeLLM(["Company X announced Product Y on August 10 [F001]."])

        report, audit = audit_and_repair_report(
            llm,
            "Company X announced Product Y for 99 billion dollars.",
            facts,
        )

        self.assertIn("[F001]", report)
        self.assertEqual(audit["status"], "repaired")
        self.assertEqual(audit["repair_attempts"], 1)
        self.assertEqual(len(audit["audit_history"]), 2)

    def test_repairs_stop_after_two_attempts(self):
        facts = build_fact_pack("AI", sample_articles()[:1])
        llm = FakeLLM(["Unsupported revenue was 99 billion dollars."] * 2)

        _report, audit = audit_and_repair_report(
            llm,
            "Unsupported revenue was 99 billion dollars.",
            facts,
        )

        self.assertEqual(llm.calls, 2)
        self.assertEqual(audit["status"], "needs_review")
        self.assertEqual(audit["repair_attempts"], 2)
        self.assertEqual(len(audit["audit_history"]), 3)

    def test_repair_api_failure_keeps_draft_for_review(self):
        class FailingLLM:
            def generate(self, *args, **kwargs):
                raise RuntimeError("repair unavailable")

        facts = build_fact_pack("AI", sample_articles()[:1])
        original = "Unsupported revenue was 99 billion dollars."
        report, audit = audit_and_repair_report(FailingLLM(), original, facts)
        self.assertEqual(report, original)
        self.assertEqual(audit["status"], "needs_review")
        self.assertTrue(any(reason["code"] == "repair_call_failed" for reason in audit["failure_reasons"]))

    def test_empty_repair_does_not_erase_original_draft(self):
        facts = build_fact_pack("AI", sample_articles()[:1])
        original = "Unsupported revenue was 99 billion dollars."
        report, audit = audit_and_repair_report(FakeLLM([""]), original, facts)

        self.assertEqual(report, original)
        self.assertEqual(audit["status"], "needs_review")
        self.assertTrue(any(reason["code"] == "repair_call_failed" for reason in audit["failure_reasons"]))

    def test_failed_report_cannot_contaminate_trend_memory(self):
        class AlwaysBadClient:
            def __init__(self, *args, **kwargs):
                pass

            def generate(self, *args, **kwargs):
                return "Company X revenue was 99 billion dollars without evidence."

        class EmptyMemoryStore:
            def __init__(self, _topic):
                pass

            def load(self):
                return {"recent": [], "long_term": []}

        config = {"llm": {"api_key": "test", "base_url": "https://example.com", "model": "test"}, "search": {}}
        topic = {"name": "AuditIsolation", "keywords": ["Product Y"]}
        with tempfile.TemporaryDirectory() as tmp, patch("newsweaver.generator.get_output_dir", return_value=Path(tmp)), patch(
            "newsweaver.generator.LLMClient", AlwaysBadClient
        ), patch("newsweaver.generator.MemoryStore", EmptyMemoryStore), patch(
            "newsweaver.generator.auto_compact_memory", return_value=0
        ), patch("newsweaver.generator.export_report_bundle", return_value={"html": "report.html", "publish": "report.publish.json"}), patch(
            "newsweaver.generator.add_structured_recent_memory"
        ) as add_memory:
            output = run_generate(config, topic, "test", 3, prepared_articles=sample_articles(), force=True)
            audit = json.loads(output.with_suffix(".audit.json").read_text(encoding="utf-8"))

        self.assertEqual(audit["status"], "needs_review")
        add_memory.assert_not_called()

    def test_empty_generation_is_not_saved_as_a_report(self):
        class EmptyClient:
            def __init__(self, *args, **kwargs):
                pass

            def generate(self, *args, **kwargs):
                return ""

        class EmptyMemoryStore:
            def __init__(self, _topic):
                pass

            def load(self):
                return {"recent": [], "long_term": []}

        config = {"llm": {"api_key": "test", "base_url": "https://example.com", "model": "test"}, "search": {}}
        topic = {"name": "NoBlankArtifact", "keywords": ["Product Y"]}
        with tempfile.TemporaryDirectory() as tmp, patch("newsweaver.generator.get_output_dir", return_value=Path(tmp)), patch(
            "newsweaver.generator.LLMClient", EmptyClient
        ), patch("newsweaver.generator.MemoryStore", EmptyMemoryStore), patch(
            "newsweaver.generator.auto_compact_memory", return_value=0
        ), patch("newsweaver.generator.add_structured_recent_memory") as add_memory:
            with self.assertRaisesRegex(RuntimeError, "未生成可保存的报告正文"):
                run_generate(config, topic, "test", 3, prepared_articles=sample_articles(), force=True)
            self.assertEqual(list(Path(tmp).glob("*.md")), [])

        add_memory.assert_not_called()

    def test_passed_report_is_allowed_into_trend_memory(self):
        facts = build_fact_pack("AI", sample_articles()[:1])
        llm = FakeLLM([])
        report, audit = audit_and_repair_report(
            llm,
            "Company X announced Product Y on August 10 [F001].",
            facts,
        )
        self.assertEqual(report, "Company X announced Product Y on August 10 [F001].")
        self.assertEqual(audit["status"], "pass")
        self.assertTrue(audit["passed"])


if __name__ == "__main__":
    unittest.main()
