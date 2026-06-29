import unittest

from newsweaver.webapp import _extract_section, split_sources


class WebAppHelpersTest(unittest.TestCase):
    def test_split_sources_supports_builtin_and_custom_rss(self):
        self.assertEqual(
            split_sources("rss, bing, https://example.com/feed.xml"),
            ["rss", "bing", "rss:https://example.com/feed.xml"],
        )

    def test_extract_section_stops_at_next_heading(self):
        report = "# Report\n\n## 核心事件\n内容 [F001]\n\n## 深度分析\n分析"
        self.assertEqual(_extract_section(report, "核心事件"), "## 核心事件\n内容 [F001]")


if __name__ == "__main__":
    unittest.main()
