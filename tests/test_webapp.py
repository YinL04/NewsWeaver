import unittest

from newsweaver.webapp import _extract_section, build_health_report, enrich_quality_report, split_sources


class WebAppHelpersTest(unittest.TestCase):
    def test_split_sources_supports_builtin_and_custom_rss(self):
        self.assertEqual(
            split_sources("rss, bing, https://example.com/feed.xml"),
            ["rss", "bing", "rss:https://example.com/feed.xml"],
        )

    def test_extract_section_stops_at_next_heading(self):
        report = "# Report\n\n## 核心事件\n内容 [F001]\n\n## 深度分析\n分析"
        self.assertEqual(_extract_section(report, "核心事件"), "## 核心事件\n内容 [F001]")

    def test_enrich_quality_report_green_status(self):
        quality = enrich_quality_report({
            "score": 92,
            "ready": True,
            "article_count": 5,
            "source_count": 3,
            "full_text_count": 4,
            "warnings": [],
            "blockers": [],
        })
        self.assertEqual(quality["status"]["level"], "green")
        self.assertIn("可以生成", quality["advice"][0])

    def test_enrich_quality_report_red_status_has_actionable_advice(self):
        quality = enrich_quality_report({
            "score": 45,
            "ready": False,
            "article_count": 1,
            "source_count": 1,
            "full_text_count": 0,
            "warnings": [],
            "blockers": ["Too few articles"],
        })
        self.assertEqual(quality["status"]["level"], "red")
        self.assertTrue(any("放宽关键词" in item for item in quality["advice"]))

    def test_health_report_shape(self):
        health = build_health_report()
        self.assertIn("ready", health)
        self.assertIn("checks", health)
        self.assertTrue(any(check["name"] == "python" for check in health["checks"]))


if __name__ == "__main__":
    unittest.main()
