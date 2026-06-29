"""Shared product pipeline helpers for collection, evidence, and quality."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetcher.base import Article
from .utils import atomic_write_json


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

    return rank_articles(dedupe_articles(articles), topic_obj.get("keywords", []))[:limit]


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
    total = max(1, len(articles))
    for index, article in enumerate(articles, 1):
        if not article.full_text or article.full_text == article.summary:
            from .extractor import extract_article
            article.full_text = extract_article(article.url) or article.summary
        notify("extract", 28 + int(index / total * 27), f"正文提取 {index}/{len(articles)}")

    required = [word.lower() for word in topic_obj.get("required_words", []) if word]
    if required:
        articles = [
            article for article in articles
            if all(word in f"{article.title} {article.summary} {article.full_text}".lower() for word in required)
        ]
    notify("analyze", 60, "正在去重、排序并构建证据")
    return rank_articles(dedupe_articles(articles), topic_obj.get("keywords", []))[: limit or 10]


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


def rank_articles(articles: list[Article], keywords: list[str]) -> list[Article]:
    return sorted(
        articles,
        key=lambda article: (
            relevance_score(article, keywords),
            article.published_at or "",
        ),
        reverse=True,
    )


def article_to_dict(article: Article, keywords: list[str] | None = None) -> dict:
    return {
        "title": article.title,
        "url": article.url,
        "normalized_url": normalize_url(article.url),
        "source": article.source,
        "published_at": article.published_at,
        "summary": article.summary,
        "full_text": article.full_text,
        "language": article.language,
        "relevance_score": relevance_score(article, keywords or []),
    }


def build_fact_pack(topic_name: str, articles: list[Article]) -> dict:
    """Build a source-backed evidence package for the generated report."""
    facts = []
    source_counts = Counter(a.source for a in articles if a.source)
    for index, article in enumerate(articles, 1):
        evidence_text = first_sentence(article.full_text or article.summary or article.title)
        facts.append(
            {
                "id": f"F{index:03d}",
                "claim": evidence_text,
                "source_title": article.title,
                "source": article.source,
                "url": article.url,
                "published_at": article.published_at,
            }
        )

    return {
        "topic": topic_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count": len(articles),
        "source_count": len(source_counts),
        "sources": dict(source_counts),
        "facts": facts,
    }


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
    """Check citation validity and flag numeric claims without an evidence id."""
    valid_ids = {fact.get("id") for fact in facts.get("facts", []) if fact.get("id")}
    cited = set(re.findall(r"\[(F\d{3})\]", report or ""))
    invalid = sorted(cited - valid_ids)
    numeric_without_citation = []
    for raw in (report or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("- ["):
            continue
        if re.search(r"\d+(?:\.\d+)?(?:%|％|亿|万|美元|元|人|家|款|倍)", line) and not re.search(r"\[F\d{3}\]", line):
            numeric_without_citation.append(line[:180])
    coverage = round(len(cited & valid_ids) / max(1, len(valid_ids)) * 100)
    warnings = []
    if invalid:
        warnings.append("存在无效证据编号")
    if numeric_without_citation:
        warnings.append("存在未标注证据的数字陈述")
    if coverage < 50 and valid_ids:
        warnings.append("证据引用覆盖率偏低")
    return {
        "valid": not invalid and not numeric_without_citation,
        "citation_coverage": coverage,
        "cited_ids": sorted(cited & valid_ids),
        "invalid_ids": invalid,
        "numeric_without_citation": numeric_without_citation[:12],
        "warnings": warnings,
    }


def build_event_clusters(articles: list[Article]) -> list[dict]:
    """Create lightweight event clusters using shared source and title terms."""
    clusters: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        key = article.source or first_token(article.title) or "general"
        clusters[key].append(article)

    return [
        {
            "cluster": key,
            "article_count": len(group),
            "titles": [article.title for article in group[:5]],
        }
        for key, group in sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True)
    ]


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
