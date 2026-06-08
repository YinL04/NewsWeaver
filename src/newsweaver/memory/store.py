"""记忆存储引擎：L2/L3 JSON 读写"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..utils import get_memory_dir, atomic_write_json, read_json, logger


class MemoryStore:
    """单主题记忆存储"""

    def __init__(self, topic_name: str):
        self.topic_name = topic_name
        self.file_path = get_memory_dir() / f"{topic_name}.json"

    def load(self) -> dict:
        data = read_json(self.file_path)
        if not data:
            data = {
                "topic": self.topic_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "recent": [],
                "long_term": [],
            }
        return data

    def save(self, data: dict) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self.file_path, data)

    def add_recent(self, summary: str, sentiment: float, top_entities: list[str]) -> None:
        """添加 L2 记录，并清理超过 7 天的旧记录"""
        data = self.load()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        entry = {
            "date": today,
            "summary": summary,
            "sentiment": round(sentiment, 2),
            "top_entities": top_entities[:5],
        }
        data.setdefault("recent", []).append(entry)

        # 清理超过 7 天的记录
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        data["recent"] = [r for r in data["recent"] if r["date"] >= cutoff]

        # 上限 30 条
        if len(data["recent"]) > 30:
            data["recent"] = data["recent"][-30:]

        self.save(data)
        logger.debug(f"L2 记忆已更新: {self.topic_name}")

    def add_long_term(self, week_start: str, article_count: int, avg_sentiment: float, top_entities: list[str]) -> None:
        """添加 L3 记录"""
        data = self.load()
        entry = {
            "week_start": week_start,
            "article_count": article_count,
            "avg_sentiment": round(avg_sentiment, 2),
            "top_entities": top_entities[:5],
        }
        data.setdefault("long_term", []).append(entry)

        # 淘汰超过 52 周的记录
        if len(data["long_term"]) > 52:
            data["long_term"] = data["long_term"][-52:]

        self.save(data)
