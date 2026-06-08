"""Bing News Search API 适配器（可选增强）"""

from datetime import datetime, timedelta, timezone

import requests

from .base import BaseFetcher, Article
from ..utils import logger

BING_NEWS_ENDPOINT = "https://api.bing.microsoft.com/v7.0/news/search"


class BingFetcher(BaseFetcher):
    """Bing News Search API 适配器"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.timeout = 15

    def fetch(
        self,
        keywords: list[str],
        exclude_words: list[str] | None = None,
        limit: int = 10,
        days_back: int = 1,
    ) -> list[Article]:
        exclude_words = exclude_words or []
        query = " ".join(keywords)
        freshness = f"Day{days_back}" if days_back <= 7 else "Week"

        try:
            resp = requests.get(
                BING_NEWS_ENDPOINT,
                headers={"Ocp-Apim-Subscription-Key": self.api_key},
                params={
                    "q": query,
                    "count": limit * 2,  # 多取一些，后续过滤
                    "freshness": freshness,
                    "mkt": "zh-CN",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Bing News 请求失败: {e}")
            return []

        data = resp.json()
        articles = []
        for item in data.get("value", []):
            title = item.get("name", "").strip()
            url = item.get("url", "").strip()
            if not title or not url:
                continue

            published = item.get("datePublished", datetime.now(timezone.utc).isoformat())
            description = item.get("description", "")
            source_name = item.get("provider", [{}])[0].get("name", "Bing News")

            articles.append(Article(
                title=title,
                url=url,
                source=source_name,
                published_at=published,
                summary=description[:500],
                full_text="",
                language="zh",
            ))

        articles.sort(key=lambda a: a.published_at, reverse=True)
        return self._filter_articles(articles, keywords, exclude_words, limit)
