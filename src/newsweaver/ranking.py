"""Modular article scoring with freshness, quality, novelty, and diversity."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Protocol

from .clustering import article_id, build_event_clusters, jaccard, lexical_terms, parse_published_at, text_tokens
from .fetcher.base import Article


DEFAULT_SOURCE_QUALITY = {
    "reuters": 1.0,
    "associated press": 0.98,
    "ap": 0.98,
    "bbc": 0.95,
    "financial times": 0.95,
    "the guardian": 0.90,
    "36kr": 0.82,
    "ithome": 0.80,
    "infoq": 0.84,
}


class RankingStrategy(Protocol):
    def rank(self, articles: list[Article], keywords: list[str]) -> list[Article]: ...


class DiverseArticleRanker:
    """Greedy multiplicative scorer with event/source diversity penalties."""

    def __init__(
        self,
        source_quality: dict[str, float] | None = None,
        freshness_half_life_hours: float = 72.0,
    ):
        self.source_quality = {**DEFAULT_SOURCE_QUALITY, **{key.lower(): value for key, value in (source_quality or {}).items()}}
        self.freshness_half_life_hours = freshness_half_life_hours

    def rank(self, articles: list[Article], keywords: list[str]) -> list[Article]:
        if not articles:
            return []
        relevance = bm25_relevance(articles, keywords)
        freshness = freshness_scores(articles, self.freshness_half_life_hours)
        clusters = build_event_clusters(articles)
        event_by_article = {
            record.get("article_id"): cluster.get("event_id")
            for cluster in clusters
            for record in cluster.get("articles", [])
        }
        remaining = list(articles)
        selected: list[Article] = []
        event_seen: Counter[str] = Counter()
        source_seen: Counter[str] = Counter()
        while remaining:
            candidates = []
            for article in remaining:
                aid = article_id(article)
                event_id = event_by_article.get(aid, aid)
                novelty = 1.0 / (1.0 + 1.6 * event_seen[event_id])
                source_diversity = 1.0 / (1.0 + 0.45 * source_seen[(article.source or "").lower()])
                similarity = max(
                    (jaccard(text_tokens(article.title), text_tokens(item.title)) for item in selected),
                    default=0.0,
                )
                diversity = max(0.35, 1.0 - 0.65 * similarity)
                quality = self._source_quality(article.source)
                final = relevance[aid] * freshness[aid] * quality * novelty * source_diversity * diversity
                components = {
                    "relevance": round(relevance[aid], 4),
                    "freshness": round(freshness[aid], 4),
                    "source_quality": round(quality, 4),
                    "novelty": round(novelty, 4),
                    "source_diversity": round(source_diversity, 4),
                    "diversity": round(diversity, 4),
                    "final_score": round(final, 6),
                    "event_id": event_id,
                }
                candidates.append((final, article.published_at or "", aid, article, components))
            _score, _date, _aid, winner, components = max(candidates, key=lambda item: (item[0], item[1], item[2]))
            winner.metadata.setdefault("ranking", {}).update(components)
            selected.append(winner)
            event_seen[components["event_id"]] += 1
            source_seen[(winner.source or "").lower()] += 1
            remaining.remove(winner)
        return selected

    def _source_quality(self, source: str) -> float:
        normalized = (source or "").lower().strip()
        if normalized in self.source_quality:
            return max(0.1, min(1.0, float(self.source_quality[normalized])))
        for known, score in self.source_quality.items():
            if known and known in normalized:
                return max(0.1, min(1.0, float(score)))
        return 0.75


def bm25_relevance(articles: list[Article], keywords: list[str]) -> dict[str, float]:
    """Small BM25 baseline normalized to (0, 1], with phrase boosts."""
    query_tokens = set().union(*(text_tokens(keyword) for keyword in keywords if keyword))
    if not query_tokens:
        return {article_id(article): 0.6 for article in articles}
    documents = {}
    lengths = []
    document_frequency: Counter[str] = Counter()
    for article in articles:
        tokens = lexical_terms(f"{article.title} {article.summary} {article.full_text}")
        counts = Counter(tokens)
        documents[article_id(article)] = counts
        lengths.append(sum(counts.values()))
        document_frequency.update(counts.keys())
    avg_length = sum(lengths) / max(1, len(lengths))
    raw_scores = {}
    total_documents = len(articles)
    for article in articles:
        aid = article_id(article)
        counts = documents[aid]
        length = sum(counts.values())
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (total_documents - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * length / max(1, avg_length))
            score += idf * frequency * 2.2 / denominator
        title = article.title.lower()
        phrase_boost = sum(1.0 for keyword in keywords if keyword and keyword.lower() in title)
        raw_scores[aid] = score + phrase_boost
    maximum = max(raw_scores.values(), default=1.0)
    if maximum <= 0:
        return {aid: 0.05 for aid in raw_scores}
    return {aid: max(0.05, score / maximum) for aid, score in raw_scores.items()}


def freshness_scores(articles: list[Article], half_life_hours: float = 72.0) -> dict[str, float]:
    parsed = [parse_published_at(article.published_at) for article in articles]
    aware = [value for value in parsed if value is not None]
    reference = max(aware) if aware else datetime.now(timezone.utc)
    scores = {}
    for article, published in zip(articles, parsed):
        if published is None:
            score = 0.5
        else:
            try:
                age = max(0.0, (reference - published).total_seconds() / 3600)
            except TypeError:
                score = 0.5
            else:
                score = math.exp(-math.log(2) * age / max(1.0, half_life_hours))
        scores[article_id(article)] = max(0.05, score)
    return scores


def rank_articles(
    articles: list[Article],
    keywords: list[str],
    strategy: RankingStrategy | None = None,
    source_quality: dict[str, float] | None = None,
) -> list[Article]:
    return (strategy or DiverseArticleRanker(source_quality=source_quality)).rank(articles, keywords)
