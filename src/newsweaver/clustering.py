"""Deterministic event clustering for cross-source news coverage."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime
from typing import Protocol

from .fetcher.base import Article


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9&_.+-]{1,30}\b|[\u4e00-\u9fffA-Za-z0-9]{2,16}(?:公司|集团|科技|汽车|银行|政府|委员会|模型|平台|产品)")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "to", "was", "were", "will", "with", "after", "new",
    "news", "report", "reports", "says", "said", "its", "their", "this", "about",
}


class EventClusterer(Protocol):
    """Interface reserved for deterministic or embedding-backed clusterers."""

    def cluster(self, articles: list[Article]) -> list[dict]: ...


def article_id(article: Article) -> str:
    """Return a stable provenance id without depending on input ordering."""
    from .pipeline import normalize_url

    identity = normalize_url(article.url) or normalize_text(article.title)
    return "A" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12].upper()


def normalize_text(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower(), flags=re.UNICODE).strip()


def text_tokens(text: str) -> set[str]:
    """Tokenize English words and Chinese character n-grams without extra dependencies."""
    return set(lexical_terms(text))


def lexical_terms(text: str) -> list[str]:
    """Return repeat-preserving terms for BM25-style scoring."""
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        token = raw.lower().strip("._+-")
        if not token or token in STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 3:
                tokens.append(token)
            else:
                tokens.extend(token[index:index + 2] for index in range(len(token) - 1))
                tokens.extend(token[index:index + 3] for index in range(len(token) - 2))
        elif len(token) >= 2 or token.isdigit():
            tokens.append(token)
    return tokens


def extract_named_entities(text: str) -> set[str]:
    entities = {match.group(0).strip().lower() for match in ENTITY_RE.finditer(text or "")}
    return {entity for entity in entities if entity not in STOPWORDS}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class DeterministicEventClusterer:
    """Agglomerative baseline using entities, lexical overlap, and time proximity."""

    def __init__(self, similarity_threshold: float = 0.36, time_window_hours: int = 72):
        self.similarity_threshold = similarity_threshold
        self.time_window_hours = time_window_hours

    def similarity(self, left: Article, right: Article) -> float:
        left_title = text_tokens(left.title)
        right_title = text_tokens(right.title)
        title_score = jaccard(left_title, right_title)
        left_context = text_tokens(f"{left.title} {left.summary} {(left.full_text or '')[:1200]}")
        right_context = text_tokens(f"{right.title} {right.summary} {(right.full_text or '')[:1200]}")
        content_score = jaccard(left_context, right_context)
        left_entities = extract_named_entities(f"{left.title} {left.summary}")
        right_entities = extract_named_entities(f"{right.title} {right.summary}")
        entity_score = jaccard(left_entities, right_entities)

        left_time = parse_published_at(left.published_at)
        right_time = parse_published_at(right.published_at)
        hours = None
        if left_time and right_time:
            try:
                hours = abs((left_time - right_time).total_seconds()) / 3600
            except TypeError:
                hours = None
        time_score = math.exp(-hours / max(1, self.time_window_hours)) if hours is not None else 0.5

        # Require a semantic anchor. Outlet/source is deliberately excluded.
        shared_anchor = bool(left_title & right_title) or bool(left_entities & right_entities)
        if not shared_anchor:
            return 0.0
        score = 0.55 * title_score + 0.15 * content_score + 0.18 * entity_score + 0.12 * time_score
        if hours is not None and hours > self.time_window_hours:
            score *= max(0.12, self.time_window_hours / hours)
        return round(score, 6)

    def cluster(self, articles: list[Article]) -> list[dict]:
        groups: list[list[Article]] = []
        ordered = sorted(
            articles,
            key=lambda article: (
                _timestamp(parse_published_at(article.published_at)),
                article_id(article),
            ),
        )
        for article in ordered:
            best_index = -1
            best_score = 0.0
            for index, group in enumerate(groups):
                score = max(self.similarity(article, member) for member in group)
                if score > best_score:
                    best_index, best_score = index, score
            if best_index >= 0 and best_score >= self.similarity_threshold:
                groups[best_index].append(article)
            else:
                groups.append([article])

        clusters = [self._serialize(group) for group in groups]
        return sorted(clusters, key=lambda item: (-item["article_count"], item["event_id"]))

    def _serialize(self, group: list[Article]) -> dict:
        ids = sorted(article_id(article) for article in group)
        event_id = "E" + hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:12].upper()
        representative = self._representative(group)
        dated = sorted(value for value in (article.published_at for article in group) if value)
        entity_counts: Counter[str] = Counter()
        for article in group:
            entity_counts.update(extract_named_entities(f"{article.title} {article.summary}"))
        article_records = [
            {
                "article_id": article_id(article),
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "published_at": article.published_at,
            }
            for article in sorted(group, key=lambda item: article_id(item))
        ]
        return {
            "schema_version": 1,
            "event_id": event_id,
            "cluster": event_id,  # v1 compatibility
            "article_count": len(group),
            "articles": article_records,
            "sources": sorted({article.source for article in group if article.source}),
            "entities": [name for name, _count in entity_counts.most_common(20)],
            "published_at_range": {
                "start": dated[0] if dated else "",
                "end": dated[-1] if dated else "",
            },
            "representative_title": representative.title,
            "titles": [record["title"] for record in article_records],  # v1 compatibility
        }

    def _representative(self, group: list[Article]) -> Article:
        if len(group) == 1:
            return group[0]
        scored = []
        for candidate in group:
            similarities = [jaccard(text_tokens(candidate.title), text_tokens(other.title)) for other in group if other is not candidate]
            scored.append((sum(similarities) / max(1, len(similarities)), article_id(candidate), candidate))
        return max(scored, key=lambda item: (item[0], item[1]))[2]


def build_event_clusters(
    articles: list[Article],
    clusterer: EventClusterer | None = None,
) -> list[dict]:
    """Cluster articles about the same event across media outlets."""
    return (clusterer or DeterministicEventClusterer()).cluster(articles)


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    try:
        return value.timestamp()
    except (OSError, OverflowError, ValueError):
        return float("-inf")
