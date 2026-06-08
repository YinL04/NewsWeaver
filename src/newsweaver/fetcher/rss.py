"""RSS 适配器：使用 feedparser 解析 RSS 源"""

from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .base import BaseFetcher, Article
from ..utils import logger

# 预置中文科技媒体 RSS 源
DEFAULT_RSS_SOURCES = {
    "36kr": "https://36kr.com/feed",
    "huxiu": "https://www.huxiu.com/rss/0.xml",
    "ithome": "https://www.ithome.com/rss/",
    "sspai": "https://sspai.com/feed",
    "infoq": "https://www.infoq.cn/feed",
    "ifanr": "https://www.ifanr.com/feed",
}


class RssFetcher(BaseFetcher):
    """RSS 订阅源适配器"""

    def __init__(self, feed_url: str | None = None):
        self.feed_url = feed_url
        self.timeout = 15

    def fetch(
        self,
        keywords: list[str],
        exclude_words: list[str] | None = None,
        limit: int = 10,
        days_back: int = 1,
    ) -> list[Article]:
        exclude_words = exclude_words or []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        if self.feed_url:
            # 单个自定义 RSS 源
            articles = self._fetch_single(self.feed_url)
        else:
            # 所有预置源
            articles = []
            for name, url in DEFAULT_RSS_SOURCES.items():
                try:
                    fetched = self._fetch_single(url, source_name=name)
                    articles.extend(fetched)
                except Exception as e:
                    logger.warning(f"RSS 源 {name} 获取失败: {e}")

        # 按时间倒序
        articles.sort(key=lambda a: a.published_at, reverse=True)

        # 时间过滤
        articles = [a for a in articles if a.published_at >= cutoff.isoformat()]

        return self._filter_articles(articles, keywords, exclude_words, limit)

    def _fetch_single(self, url: str, source_name: str = "") -> list[Article]:
        try:
            resp = requests.get(url, timeout=self.timeout, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"RSS 请求失败 {url}: {e}")
            return []

        feed = feedparser.parse(resp.content)
        articles = []
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # 解析发布时间
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                except Exception:
                    published = datetime.now(timezone.utc).isoformat()
            else:
                published = datetime.now(timezone.utc).isoformat()

            # 摘要
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary
            elif hasattr(entry, "description"):
                summary = entry.description
            # 清除 HTML 标签
            summary = self._strip_html(summary)

            src = source_name or (feed.feed.get("title", "") or url)

            articles.append(Article(
                title=title,
                url=link,
                source=src,
                published_at=published,
                summary=summary[:500],
                full_text="",
                language="zh",
            ))

        return articles

    @staticmethod
    def _strip_html(text: str) -> str:
        """简单去除 HTML 标签"""
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
