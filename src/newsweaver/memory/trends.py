"""Structured trend memory: events, entities, metrics, and judgments."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from ..pipeline import first_sentence
from .store import MemoryStore


ENTITY_STOPWORDS = {
    "AI",
    "RSS",
    "API",
    "GPT",
    "LLM",
    "CEO",
    "CFO",
    "CTO",
}

METRIC_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|亿美元|亿元|亿|万美元|万元|万|tokens?|Token|倍|家|款|个|天|周|月|年)"
)


def build_structured_recent_entry(
    topic_name: str,
    articles: list[dict],
    fact_pack: dict | None = None,
    quality_report: dict | None = None,
    report_text: str = "",
) -> dict:
    """Create an L2 memory entry with events/entities/metrics/judgments."""
    now = datetime.now(timezone.utc)
    facts = (fact_pack or {}).get("facts", [])
    events = []
    for index, article in enumerate(articles[:12], 1):
        evidence = article.get("full_text") or article.get("summary") or article.get("title", "")
        events.append(
            {
                "id": f"E{index:03d}",
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "url": article.get("url", ""),
                "published_at": article.get("published_at", ""),
                "evidence": first_sentence(evidence),
            }
        )

    text_blob = "\n".join(
        [
            " ".join(
                [
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("full_text", "")[:800],
                ]
            )
            for article in articles
        ]
    )

    entities = extract_entities(text_blob, topic_name)
    metrics = extract_metrics(text_blob, articles)
    judgments = build_judgments(topic_name, events, facts, quality_report or {})

    return {
        "schema_version": 2,
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "topic": topic_name,
        "summary": summarize_events(events),
        "sentiment": estimate_sentiment(text_blob),
        "top_entities": [entity["name"] for entity in entities[:5]],
        "events": events,
        "entities": entities[:20],
        "metrics": metrics[:20],
        "judgments": judgments[:8],
        "quality": quality_report or {},
        "report_excerpt": first_sentence(report_text) if report_text else "",
    }


def add_structured_recent_memory(
    topic_name: str,
    articles: list[dict],
    fact_pack: dict | None = None,
    quality_report: dict | None = None,
    report_text: str = "",
) -> dict:
    store = MemoryStore(topic_name)
    entry = build_structured_recent_entry(topic_name, articles, fact_pack, quality_report, report_text)
    store.add_recent_entry(entry)
    auto_compact_memory(topic_name)
    return entry


def auto_compact_memory(topic_name: str, keep_recent_days: int = 7) -> int:
    """Compact older L2 entries into weekly L3 trend memory automatically."""
    store = MemoryStore(topic_name)
    data = store.load()
    recent = data.get("recent", [])
    if not recent:
        return 0

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=keep_recent_days)
    compactable = []
    remaining = []
    for entry in recent:
        entry_date = parse_date(entry.get("date"))
        if entry_date and entry_date < cutoff:
            compactable.append(entry)
        else:
            remaining.append(entry)

    if not compactable:
        return 0

    weekly_groups: dict[str, list[dict]] = defaultdict(list)
    for entry in compactable:
        entry_date = parse_date(entry.get("date"))
        if not entry_date:
            remaining.append(entry)
            continue
        week_start = entry_date - timedelta(days=entry_date.weekday())
        weekly_groups[week_start.isoformat()].append(entry)

    long_term = data.setdefault("long_term", [])
    existing_by_week = {item.get("week_start"): item for item in long_term}
    compacted_count = 0
    for week_start, entries in weekly_groups.items():
        weekly = aggregate_week(topic_name, week_start, entries)
        existing_by_week[week_start] = merge_week(existing_by_week.get(week_start), weekly)
        compacted_count += len(entries)

    data["long_term"] = sorted(existing_by_week.values(), key=lambda item: item.get("week_start", ""))[-52:]
    data["recent"] = remaining[-90:]
    store.save(data)
    return compacted_count


def compact_all_recent(topic_name: str) -> int:
    """Force compact all L2 entries into L3; useful for maintenance and tests."""
    store = MemoryStore(topic_name)
    data = store.load()
    recent = data.get("recent", [])
    if not recent:
        return 0

    weekly_groups: dict[str, list[dict]] = defaultdict(list)
    for entry in recent:
        entry_date = parse_date(entry.get("date"))
        if not entry_date:
            continue
        week_start = entry_date - timedelta(days=entry_date.weekday())
        weekly_groups[week_start.isoformat()].append(entry)

    existing_by_week = {item.get("week_start"): item for item in data.get("long_term", [])}
    compacted_count = 0
    for week_start, entries in weekly_groups.items():
        existing_by_week[week_start] = merge_week(existing_by_week.get(week_start), aggregate_week(topic_name, week_start, entries))
        compacted_count += len(entries)

    data["long_term"] = sorted(existing_by_week.values(), key=lambda item: item.get("week_start", ""))[-52:]
    data["recent"] = []
    store.save(data)
    return compacted_count


def aggregate_week(topic_name: str, week_start: str, entries: list[dict]) -> dict:
    entity_counter: Counter[str] = Counter()
    event_titles = []
    metrics = []
    judgments = []
    sentiments = []
    sources: Counter[str] = Counter()

    for entry in entries:
        sentiments.append(float(entry.get("sentiment", 0.5)))
        for entity in entry.get("entities", []):
            entity_counter[entity.get("name", "")] += int(entity.get("mentions", 1) or 1)
        for event in entry.get("events", []):
            if event.get("title"):
                event_titles.append(event["title"])
            if event.get("source"):
                sources[event["source"]] += 1
        metrics.extend(entry.get("metrics", []))
        judgments.extend(entry.get("judgments", []))

    top_entities = [{"name": name, "mentions": count} for name, count in entity_counter.most_common(10)]
    recurring_players = [item["name"] for item in top_entities[:6]]
    turning_points = infer_turning_points(event_titles, metrics, judgments)

    return {
        "schema_version": 2,
        "topic": topic_name,
        "week_start": week_start,
        "week_end": (parse_date(week_start) + timedelta(days=6)).isoformat(),
        "article_count": sum(len(entry.get("events", [])) for entry in entries),
        "event_count": len(event_titles),
        "avg_sentiment": round(sum(sentiments) / len(sentiments), 2) if sentiments else 0.5,
        "top_entities": [item["name"] for item in top_entities[:5]],
        "entities": top_entities,
        "recurring_players": recurring_players,
        "trend_conclusion": build_weekly_conclusion(recurring_players, event_titles),
        "turning_points": turning_points,
        "metrics": summarize_metrics(metrics),
        "judgments": judgments[:12],
        "sources": dict(sources),
        "sample_events": event_titles[:8],
    }


def merge_week(existing: dict | None, new: dict) -> dict:
    if not existing:
        return new
    merged_entries = [existing, new]
    proxy_entries = []
    for item in merged_entries:
        proxy_entries.append(
            {
                "sentiment": item.get("avg_sentiment", 0.5),
                "events": [{"title": title, "source": ""} for title in item.get("sample_events", [])],
                "entities": item.get("entities", []),
                "metrics": item.get("metrics", []),
                "judgments": item.get("judgments", []),
            }
        )
    return aggregate_week(new.get("topic", existing.get("topic", "")), new["week_start"], proxy_entries)


def build_trend_cards(topic_name: str) -> dict:
    store = MemoryStore(topic_name)
    data = store.load()
    recent = data.get("recent", [])
    long_term = data.get("long_term", [])
    recent_entities = Counter()
    recent_events = []
    recent_metrics = []
    recent_judgments = []

    for entry in recent[-14:]:
        for entity in entry.get("entities", []):
            recent_entities[entity.get("name", "")] += int(entity.get("mentions", 1) or 1)
        recent_events.extend([event.get("title", "") for event in entry.get("events", []) if event.get("title")])
        recent_metrics.extend(entry.get("metrics", []))
        recent_judgments.extend(entry.get("judgments", []))

    latest_week = long_term[-1] if long_term else {}
    previous_week = long_term[-2] if len(long_term) > 1 else {}
    latest_players = set(latest_week.get("recurring_players", []))
    previous_players = set(previous_week.get("recurring_players", []))

    return {
        "topic": topic_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "memory_depth": {
            "recent_entries": len(recent),
            "weekly_trends": len(long_term),
        },
        "current_hotspots": recent_events[:6],
        "recurring_players": [name for name, _ in recent_entities.most_common(8)] or latest_week.get("recurring_players", []),
        "change_since_last_period": {
            "new_players": sorted(latest_players - previous_players),
            "fading_players": sorted(previous_players - latest_players),
            "sentiment_delta": round(
                float(latest_week.get("avg_sentiment", 0.5)) - float(previous_week.get("avg_sentiment", 0.5)),
                2,
            )
            if latest_week and previous_week
            else 0,
        },
        "turning_points": latest_week.get("turning_points", []) or infer_turning_points(recent_events, recent_metrics, recent_judgments),
        "trend_conclusion": latest_week.get("trend_conclusion") or build_weekly_conclusion([name for name, _ in recent_entities.most_common(5)], recent_events),
        "metrics": summarize_metrics(recent_metrics)[:8] or latest_week.get("metrics", [])[:8],
        "judgments": recent_judgments[:8] or latest_week.get("judgments", [])[:8],
    }


def format_trend_cards(cards: dict) -> str:
    change = cards.get("change_since_last_period", {})
    lines = [
        f"# {cards.get('topic', '')} 趋势卡片",
        "",
        f"> 记忆深度：L2 {cards.get('memory_depth', {}).get('recent_entries', 0)} 条，L3 {cards.get('memory_depth', {}).get('weekly_trends', 0)} 周。",
        "",
        "## 趋势结论",
        cards.get("trend_conclusion") or "暂无足够趋势数据。",
        "",
        "## 本期热点",
    ]
    lines.extend([f"- {item}" for item in cards.get("current_hotspots", [])] or ["- 暂无近期热点。"])
    lines.extend(["", "## 反复出现的玩家"])
    lines.extend([f"- {item}" for item in cards.get("recurring_players", [])] or ["- 暂无稳定玩家。"])
    lines.extend(["", "## 和上一周期相比"])
    lines.append(f"- 新出现玩家：{', '.join(change.get('new_players', [])) or '暂无'}")
    lines.append(f"- 降温玩家：{', '.join(change.get('fading_players', [])) or '暂无'}")
    lines.append(f"- 情绪变化：{change.get('sentiment_delta', 0):+}")
    lines.extend(["", "## 拐点信号"])
    lines.extend([f"- {item}" for item in cards.get("turning_points", [])] or ["- 暂无明显拐点。"])
    lines.extend(["", "## 关键指标"])
    lines.extend([f"- {m.get('name')}: {m.get('value')} {m.get('unit')}（{m.get('context', '')}）" for m in cards.get("metrics", [])] or ["- 暂无可结构化指标。"])
    lines.extend(["", "## 可用判断"])
    lines.extend([f"- {j.get('claim')}（置信度 {j.get('confidence', 'medium')}）" for j in cards.get("judgments", [])] or ["- 暂无判断。"])
    return "\n".join(lines).strip() + "\n"


def render_memory_for_prompt(memory_data: dict) -> str:
    recent = memory_data.get("recent", [])
    long_term = memory_data.get("long_term", [])
    if not recent and not long_term:
        return ""

    lines = ["## 历史趋势记忆（结构化）", ""]
    if recent:
        lines.append("### 最近事件 / 实体 / 判断")
        for entry in recent[-5:]:
            events = "；".join(event.get("title", "") for event in entry.get("events", [])[:3])
            entities = ", ".join(entity.get("name", "") for entity in entry.get("entities", [])[:5])
            judgments = "；".join(judgment.get("claim", "") for judgment in entry.get("judgments", [])[:2])
            lines.append(f"- {entry.get('date')}: {entry.get('summary', '')}")
            if events:
                lines.append(f"  事件：{events}")
            if entities:
                lines.append(f"  高频实体：{entities}")
            if judgments:
                lines.append(f"  历史判断：{judgments}")
    if long_term:
        lines.extend(["", "### 周趋势"])
        for week in long_term[-4:]:
            lines.append(f"- {week.get('week_start')}：{week.get('trend_conclusion', '')}")
            lines.append(f"  反复玩家：{', '.join(week.get('recurring_players', [])) or '暂无'}")
            lines.append(f"  拐点：{'；'.join(week.get('turning_points', [])) or '暂无'}")
    lines.extend(["", "请在报告中单独写一节“本期和过去相比变化了什么”，明确说明延续、变化和新信号。"])
    return "\n".join(lines)


def extract_entities(text: str, topic_name: str) -> list[dict]:
    candidates = []
    candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,20}\b", text))
    candidates.extend(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}(?:公司|集团|科技|智能|资本|汽车|能源|芯片|模型|平台)", text))
    counter = Counter(
        item.strip()
        for item in candidates
        if item.strip()
        and item.strip() not in ENTITY_STOPWORDS
        and item.strip().lower() != topic_name.lower()
    )
    return [{"name": name, "mentions": count} for name, count in counter.most_common(20)]


def extract_metrics(text: str, articles: list[dict]) -> list[dict]:
    metrics = []
    for match in METRIC_RE.finditer(text):
        start = max(0, match.start() - 42)
        end = min(len(text), match.end() + 42)
        context = re.sub(r"\s+", " ", text[start:end]).strip()
        metrics.append(
            {
                "name": infer_metric_name(context),
                "value": match.group("value"),
                "unit": match.group("unit"),
                "context": context,
                "source_url": find_source_for_context(context, articles),
            }
        )
    return dedupe_metrics(metrics)


def infer_metric_name(context: str) -> str:
    if "%" in context:
        return "比例/增速"
    if any(token in context for token in ["美元", "亿元", "万元", "亿", "万"]):
        return "金额/规模"
    if any(token in context for token in ["Token", "token"]):
        return "Token 指标"
    return "数量指标"


def find_source_for_context(context: str, articles: list[dict]) -> str:
    for article in articles:
        blob = f"{article.get('title', '')} {article.get('summary', '')} {article.get('full_text', '')}"
        if context[:18] and context[:18] in blob:
            return article.get("url", "")
    return articles[0].get("url", "") if articles else ""


def dedupe_metrics(metrics: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for metric in metrics:
        key = (metric.get("value"), metric.get("unit"), metric.get("name"))
        if key in seen:
            continue
        seen.add(key)
        result.append(metric)
    return result


def summarize_metrics(metrics: list[dict]) -> list[dict]:
    return dedupe_metrics(metrics)[:10]


def build_judgments(topic_name: str, events: list[dict], facts: list[dict], quality: dict) -> list[dict]:
    claims = []
    if events:
        claims.append(
            {
                "claim": f"{topic_name} 本期主要由 {events[0].get('title', '')} 等事件驱动。",
                "basis": events[0].get("url", ""),
                "confidence": "high" if quality.get("source_count", 0) >= 2 else "medium",
            }
        )
    if quality.get("score", 0) < 60:
        claims.append(
            {
                "claim": "本期素材基础偏弱，趋势判断需要谨慎使用。",
                "basis": "quality_report",
                "confidence": "high",
            }
        )
    for fact in facts[:5]:
        claims.append(
            {
                "claim": fact.get("claim", ""),
                "basis": fact.get("url", ""),
                "confidence": "medium",
            }
        )
    return [claim for claim in claims if claim.get("claim")]


def infer_turning_points(event_titles: list[str], metrics: list[dict], judgments: list[dict]) -> list[str]:
    text = " ".join(event_titles + [j.get("claim", "") for j in judgments])
    signals = []
    signal_words = ["发布", "融资", "上市", "裁员", "监管", "涨价", "降价", "突破", "合作", "收购", "亏损", "盈利"]
    for word in signal_words:
        if word in text:
            signals.append(f"出现“{word}”相关信号，可能代表阶段性变化。")
    if metrics:
        signals.append("本期出现可量化指标，适合持续追踪。")
    return signals[:5]


def build_weekly_conclusion(players: list[str], events: list[str]) -> str:
    if players and events:
        return f"本周围绕 {', '.join(players[:3])} 的动态最密集，核心事件包括：{'；'.join(events[:3])}。"
    if events:
        return f"本周核心事件包括：{'；'.join(events[:3])}。"
    return "本周记忆数据较少，尚不足以形成稳定趋势。"


def summarize_events(events: list[dict]) -> str:
    titles = [event.get("title", "") for event in events[:3] if event.get("title")]
    return "；".join(titles) if titles else "暂无可总结事件。"


def estimate_sentiment(text: str) -> float:
    positive = sum(text.count(word) for word in ["增长", "突破", "发布", "融资", "盈利", "合作", "提升", "领先"])
    negative = sum(text.count(word) for word in ["下滑", "亏损", "裁员", "监管", "风险", "失败", "下降", "危机"])
    score = 0.5 + (positive - negative) * 0.03
    return round(max(0.0, min(1.0, score)), 2)


def parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
