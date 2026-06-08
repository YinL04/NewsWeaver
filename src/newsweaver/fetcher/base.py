"""信源抽象基类 + Article 数据结构"""

from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: str  # ISO 8601
    summary: str = ""
    full_text: str = ""
    language: str = "zh"


class BaseFetcher(ABC):
    """信源适配器抽象基类"""

    @abstractmethod
    def fetch(
        self,
        keywords: list[str],
        exclude_words: list[str] | None = None,
        limit: int = 10,
        days_back: int = 1,
    ) -> list[Article]:
        """根据关键词搜索新闻，返回文章列表"""
        ...

    def _filter_articles(
        self,
        articles: list[Article],
        keywords: list[str],
        exclude_words: list[str],
        limit: int,
    ) -> list[Article]:
        """关键词匹配 + 排除词过滤 + 数量限制"""
        result = []
        for a in articles:
            text = (a.title + " " + a.summary).lower()
            # 排除词过滤
            if any(w.lower() in text for w in exclude_words):
                continue
            # 关键词匹配（任一关键词出现在标题或摘要中）
            if any(k.lower() in text for k in keywords):
                result.append(a)
            if len(result) >= limit:
                break
        return result
