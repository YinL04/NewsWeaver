"""Shared product pipeline helpers for collection, evidence, and quality."""

from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetcher.base import Article
from .utils import atomic_write_json, logger


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
}


def collect_articles(config: dict, topic_obj: dict, limit: int | None = None) -> list[Article]:
    """Collect articles from the configured sources without extracting full text."""
    from .fetcher.bing import BingFetcher
    from .fetcher.rss import RssFetcher

    search_config = config.get("search", {})
    limit = limit or search_config.get("default_limit", 10)
    days = search_config.get("days_back", 1)
    sources = topic_obj.get("sources", []) or ["rss"]
    articles: list[Article] = []

    if "rss" in sources:
        articles.extend(
            RssFetcher().fetch(
                keywords=topic_obj["keywords"],
                exclude_words=topic_obj.get("exclude_words", []),
                limit=limit,
                days_back=days,
            )
        )

    for src in sources:
        if src.startswith("rss:"):
            articles.extend(
                RssFetcher(feed_url=src[4:]).fetch(
                    keywords=topic_obj["keywords"],
                    exclude_words=topic_obj.get("exclude_words", []),
                    limit=limit,
                    days_back=days,
                )
            )

    bing_key = search_config.get("bing_api_key", "")
    if bing_key and "bing" in sources:
        articles.extend(
            BingFetcher(api_key=bing_key).fetch(
                keywords=topic_obj["keywords"],
                exclude_words=topic_obj.get("exclude_words", []),
                limit=limit,
                days_back=days,
            )
        )

    return rank_articles(
        dedupe_articles(articles),
        topic_obj.get("keywords", []),
        source_quality=search_config.get("source_quality"),
    )[:limit]


def prepare_articles(
    config: dict,
    topic_obj: dict,
    limit: int | None = None,
    progress: Callable[[str, int, str], None] | None = None,
) -> list[Article]:
    """Run the canonical collection pipeline used by both preview and generation."""
    notify = progress or (lambda _stage, _percent, _message: None)
    notify("collect", 10, "正在采集资讯源")
    articles = collect_articles(config, topic_obj, limit)
    notify("extract", 28, f"正在提取 {len(articles)} 篇正文")
    targets = [article for article in articles if not article.full_text or article.full_text == article.summary]
    total = max(1, len(targets))
    if targets:
        from .extractor import extract_article_detailed

        workers = max(1, min(int(config.get("search", {}).get("extraction_workers", 4)), 8, len(targets)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="newsweaver-extract") as executor:
            futures = {executor.submit(extract_article_detailed, article.url): article for article in targets}
            for index, future in enumerate(as_completed(futures), 1):
                article = futures[future]
                try:
                    result = future.result()
                    article.full_text = result.text or article.summary
                    article.metadata["extraction"] = result.metadata
                    canonical_url = result.metadata.get("canonical_url")
                    if canonical_url:
                        article.url = canonical_url
                except Exception as exc:
                    article.full_text = article.summary
                    article.metadata["extraction"] = {
                        "status": "failed",
                        "method": "none",
                        "content_length": 0,
                        "cached": False,
                        "error": str(exc),
                    }
                    logger.warning(f"正文提取失败，已降级为摘要 {article.url}: {exc}")
                notify("extract", 28 + int(index / total * 27), f"正文提取 {index}/{len(targets)}")
    for article in articles:
        if article not in targets:
            article.metadata.setdefault(
                "extraction",
                {
                    "status": "success",
                    "method": "provided",
                    "content_length": len(article.full_text),
                    "cached": False,
                    "canonical_url": article.url,
                },
            )

    required = [word.lower() for word in topic_obj.get("required_words", []) if word]
    if required:
        articles = [
            article for article in articles
            if all(word in f"{article.title} {article.summary} {article.full_text}".lower() for word in required)
        ]
    notify("analyze", 60, "正在去重、排序并构建证据")
    return rank_articles(
        dedupe_articles(articles),
        topic_obj.get("keywords", []),
        source_quality=config.get("search", {}).get("source_quality"),
    )[: limit or 10]


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication while keeping the canonical target."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        ],
        doseq=True,
    )
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def title_fingerprint(title: str) -> str:
    normalized = re.sub(r"\W+", "", title.lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def dedupe_articles(articles: list[Article]) -> list[Article]:
    """Remove duplicate articles by normalized URL and title fingerprint."""
    by_key: dict[str, Article] = {}
    for article in articles:
        key = normalize_url(article.url) or title_fingerprint(article.title)
        title_key = f"title:{title_fingerprint(article.title)}"
        existing = by_key.get(key) or by_key.get(title_key)
        if existing:
            if len(article.full_text or article.summary) > len(existing.full_text or existing.summary):
                by_key[key] = article
                by_key[title_key] = article
            continue
        by_key[key] = article
        by_key[title_key] = article

    seen: set[int] = set()
    result: list[Article] = []
    for article in by_key.values():
        ident = id(article)
        if ident not in seen:
            seen.add(ident)
            result.append(article)
    return result


def relevance_score(article: Article, keywords: list[str]) -> int:
    title = article.title.lower()
    body = f"{article.summary} {article.full_text}".lower()
    score = 0
    for keyword in keywords:
        k = keyword.lower()
        if not k:
            continue
        if k in title:
            score += 5
        if k in body:
            score += 2
    if article.full_text and len(article.full_text) > len(article.summary):
        score += 1
    return score


def rank_articles(
    articles: list[Article],
    keywords: list[str],
    strategy=None,
    source_quality: dict[str, float] | None = None,
) -> list[Article]:
    from .ranking import rank_articles as rank_diverse_articles

    return rank_diverse_articles(articles, keywords, strategy=strategy, source_quality=source_quality)


def article_to_dict(article: Article, keywords: list[str] | None = None) -> dict:
    from .clustering import article_id

    return {
        "article_id": article_id(article),
        "title": article.title,
        "url": article.url,
        "normalized_url": normalize_url(article.url),
        "source": article.source,
        "published_at": article.published_at,
        "summary": article.summary,
        "full_text": article.full_text,
        "language": article.language,
        "relevance_score": relevance_score(article, keywords or []),
        "ranking": article.metadata.get("ranking", {}),
        "extraction": article.metadata.get("extraction", {}),
    }


def build_fact_pack(topic_name: str, articles: list[Article], event_clusters: list[dict] | None = None) -> dict:
    """Build a claim-level fact pack while preserving the v1 public API."""
    from .evidence import build_fact_pack as build_claim_fact_pack

    return build_claim_fact_pack(topic_name, articles, event_clusters=event_clusters)


def build_quality_report(topic_name: str, articles: list[Article], facts: dict) -> dict:
    """Score the evidence base before generation."""
    article_count = len(articles)
    source_count = len({a.source for a in articles if a.source})
    full_text_count = len([a for a in articles if a.full_text and len(a.full_text) > len(a.summary)])
    citation_count = len(facts.get("facts", []))

    score = 0
    score += min(article_count, 8) * 6
    score += min(source_count, 5) * 8
    score += min(full_text_count, 6) * 5
    score += 12 if citation_count >= article_count and article_count else 0
    score = min(score, 100)

    warnings = []
    if article_count < 3:
        warnings.append("Too few articles; the report may be shallow.")
    if source_count < 2:
        warnings.append("Only one source family is represented.")
    if full_text_count < max(1, article_count // 2):
        warnings.append("Many articles only have summaries, not extracted full text.")

    blockers = []
    if article_count < 3:
        blockers.append("至少需要 3 篇相关文章")
    if source_count < 2:
        blockers.append("至少需要 2 个独立来源")
    if full_text_count < max(1, (article_count + 1) // 2):
        blockers.append("至少一半文章需要成功提取正文")

    return {
        "topic": topic_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "article_count": article_count,
        "source_count": source_count,
        "full_text_count": full_text_count,
        "citation_count": citation_count,
        "warnings": warnings,
        "ready": not blockers,
        "blockers": blockers,
    }


def audit_report(report: str, facts: dict) -> dict:
    """Audit citations and factual support with a structured v2 result."""
    from .evidence import audit_report as audit_claim_report

    return audit_claim_report(report, facts)


def build_event_clusters(articles: list[Article], clusterer=None) -> list[dict]:
    """Build cross-source event clusters through the pluggable clustering API."""
    from .clustering import build_event_clusters as cluster_events

    return cluster_events(articles, clusterer=clusterer)


def write_artifacts(base_path: Path, facts: dict, quality: dict, clusters: list[dict]) -> dict:
    """Persist sidecar artifacts next to a report or preview file."""
    facts_path = base_path.with_suffix(".facts.json")
    quality_path = base_path.with_suffix(".quality.json")
    clusters_path = base_path.with_suffix(".clusters.json")
    atomic_write_json(facts_path, facts)
    atomic_write_json(quality_path, quality)
    atomic_write_json(clusters_path, {"clusters": clusters})
    return {
        "facts": str(facts_path),
        "quality": str(quality_path),
        "clusters": str(clusters_path),
    }


def first_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    match = re.search(r"(.+?[。.!?！？])\s*", text)
    return (match.group(1) if match else text[:180]).strip()


def first_token(text: str) -> str:
    match = re.search(r"[\w\u4e00-\u9fff]{2,}", text or "")
    return match.group(0) if match else ""
