import unittest
from datetime import datetime

from newsweaver.memory.trends import build_structured_recent_entry, format_trend_cards
from newsweaver.scheduler import compute_next_run
from newsweaver.templates import get_topic_template, list_topic_templates


class TrendMemoryTest(unittest.TestCase):
    def test_structured_recent_entry_has_four_memory_types(self):
        articles = [
            {
                "title": "NVIDIA 发布新 AI 芯片，性能提升 30%",
                "source": "Example",
                "url": "https://example.com/nvidia",
                "published_at": "2026-06-25T00:00:00+00:00",
                "summary": "NVIDIA 发布新 AI 芯片，面向数据中心。",
                "full_text": "NVIDIA 发布新 AI 芯片，性能提升 30%，数据中心客户将率先使用。",
            }
        ]

        entry = build_structured_recent_entry(
            "芯片半导体",
            articles,
            fact_pack={"facts": [{"claim": "NVIDIA 发布新 AI 芯片", "url": "https://example.com/nvidia"}]},
            quality_report={"score": 80, "source_count": 1},
        )

        self.assertTrue(entry["events"])
        self.assertTrue(entry["entities"])
        self.assertTrue(entry["metrics"])
        self.assertTrue(entry["judgments"])

    def test_trend_cards_format(self):
        text = format_trend_cards(
            {
                "topic": "AI",
                "memory_depth": {"recent_entries": 1, "weekly_trends": 1},
                "trend_conclusion": "AI 公司开始从模型竞赛转向商业闭环。",
                "current_hotspots": ["模型降价"],
                "recurring_players": ["OpenAI"],
                "change_since_last_period": {"new_players": ["DeepSeek"], "fading_players": [], "sentiment_delta": 0.1},
                "turning_points": ["出现降价信号"],
                "metrics": [],
                "judgments": [],
            }
        )

        self.assertIn("趋势卡片", text)
        self.assertIn("DeepSeek", text)


class TemplateAndScheduleTest(unittest.TestCase):
    def test_templates_include_p3_categories(self):
        ids = {item["id"] for item in list_topic_templates()}
        self.assertTrue({"ai", "chip", "ev", "global", "fintech"}.issubset(ids))
        self.assertEqual(get_topic_template("fintech")["name"], "金融科技")

    def test_compute_next_run_moves_past_time_forward(self):
        now = datetime(2026, 6, 25, 10, 0)
        result = compute_next_run("daily", 9, 0, now=now)
        self.assertEqual(result.date().isoformat(), "2026-06-26")


if __name__ == "__main__":
    unittest.main()
