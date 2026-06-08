"""记忆压缩：L2 → L3 按周聚合"""

from collections import defaultdict
from datetime import datetime, timezone

from .store import MemoryStore


def compact_memory(topic_name: str) -> int:
    """将 L2 中的旧记录按周聚合到 L3，返回压缩的记录数"""
    store = MemoryStore(topic_name)
    data = store.load()

    recent = data.get("recent", [])
    if not recent:
        return 0

    # 按周分组（以周一为周起始日）
    weekly_groups: dict[str, list] = defaultdict(list)
    remaining = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for r in recent:
        # 保留最近 2 天的记录在 L2
        if r["date"] >= today:
            remaining.append(r)
            continue
        # 计算周起始日
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        monday = dt - __import__("datetime").timedelta(days=dt.weekday())
        week_key = monday.strftime("%Y-%m-%d")
        weekly_groups[week_key].append(r)

    if not weekly_groups:
        return 0

    # 聚合每组
    compacted_count = 0
    for week_start, entries in weekly_groups.items():
        if not entries:
            continue
        sentiments = [e["sentiment"] for e in entries if "sentiment" in e]
        all_entities = []
        for e in entries:
            all_entities.extend(e.get("top_entities", []))

        # 统计高频实体
        entity_freq: dict[str, int] = defaultdict(int)
        for ent in all_entities:
            entity_freq[ent] += 1
        top_entities = sorted(entity_freq, key=entity_freq.get, reverse=True)[:5]

        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.5

        store.add_long_term(
            week_start=week_start,
            article_count=len(entries),
            avg_sentiment=avg_sentiment,
            top_entities=top_entities,
        )
        compacted_count += len(entries)

    # 更新 L2：只保留未压缩的记录
    data["recent"] = remaining
    store.save(data)

    return compacted_count
