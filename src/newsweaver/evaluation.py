"""Small reproducible evaluation harness for evidence and retrieval changes."""

from __future__ import annotations

import math
import re
from collections import Counter

from .fetcher.base import Article
from .pipeline import audit_report, build_event_clusters


EVAL_METRICS = (
    "citation_validity",
    "unsupported_claim_rate",
    "claim_coverage",
    "duplicate_event_rate",
    "important_event_recall",
    "source_diversity",
    "trend_consistency",
    "extraction_success_rate",
    "token_usage",
    "estimated_generation_cost",
    "latency_seconds",
)


def evaluate_fixture(payload: dict) -> dict:
    articles = [_article_from_dict(item) for item in payload.get("articles", [])]
    by_url = {article.url: article for article in articles}
    selected_urls = payload.get("selected_urls") or list(by_url)
    selected = [by_url[url] for url in selected_urls if url in by_url]
    fact_pack = payload.get("fact_pack", {})
    report = payload.get("report", "")
    audit = audit_report(report, fact_pack)

    cited = re.findall(r"\[(F\d{3,})\]", report)
    valid_ids = {fact.get("fact_id") or fact.get("id") for fact in fact_pack.get("facts", [])}
    citation_validity = sum(citation in valid_ids for citation in cited) / max(1, len(cited))
    issue_count = len(audit.get("uncited_claims", [])) + len(audit.get("unsupported_claims", []))
    factual_count = max(1, _estimated_factual_claim_count(report))
    claim_coverage = len(set(cited) & valid_ids) / max(1, len(valid_ids))

    clusters = build_event_clusters(selected)
    duplicate_count = sum(max(0, cluster.get("article_count", 0) - 1) for cluster in clusters)
    duplicate_event_rate = duplicate_count / max(1, len(selected))
    important = set(payload.get("important_event_urls", []))
    important_recall = len(important & set(selected_urls)) / max(1, len(important))

    sources = Counter(article.source for article in selected if article.source)
    source_diversity = normalized_source_entropy(sources)
    success_count = sum(
        1
        for article in articles
        if article.metadata.get("extraction", {}).get("status") == "success"
    )
    usage = payload.get("usage", {})
    input_tokens = int(usage.get("input_tokens") or max(1, len(str(fact_pack)) // 4))
    output_tokens = int(usage.get("output_tokens") or max(1, len(report) // 4))
    input_rate = float(usage.get("input_cost_per_million", 0.0) or 0.0)
    output_rate = float(usage.get("output_cost_per_million", 0.0) or 0.0)
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    metrics = {
        "citation_validity": round(citation_validity, 4),
        "unsupported_claim_rate": round(issue_count / factual_count, 4),
        "claim_coverage": round(claim_coverage, 4),
        "duplicate_event_rate": round(duplicate_event_rate, 4),
        "important_event_recall": round(important_recall, 4),
        "source_diversity": round(source_diversity, 4),
        "trend_consistency": round(trend_consistency(payload.get("trend_claims", [])), 4),
        "extraction_success_rate": round(success_count / max(1, len(articles)), 4),
        "token_usage": {"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens},
        "estimated_generation_cost": round(cost, 6),
        "latency_seconds": round(float(usage.get("latency_seconds", 0.0) or 0.0), 3),
    }
    return {
        "fixture": payload.get("name", "unnamed"),
        "metrics": metrics,
        "audit_status": audit.get("status"),
        "article_count": len(articles),
        "selected_article_count": len(selected),
        "event_count": len(clusters),
    }


def normalized_source_entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total <= 1:
        return 1.0 if total == 1 else 0.0
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return entropy / math.log(total)


def trend_consistency(claims: list[dict]) -> float:
    if not claims:
        return 1.0
    allowed = {"new", "corroborated", "disputed", "superseded", "fulfilled", "expired"}
    valid = 0
    for claim in claims:
        status = claim.get("status")
        relationships = claim.get("relationships", [])
        relation_ok = all(item.get("type") in {"corroborates", "contradicts", "supersedes", "fulfills"} for item in relationships)
        if status in allowed and relation_ok:
            valid += 1
    return valid / len(claims)


def _article_from_dict(item: dict) -> Article:
    return Article(
        title=item.get("title", ""),
        url=item.get("url", ""),
        source=item.get("source", ""),
        published_at=item.get("published_at", ""),
        summary=item.get("summary", ""),
        full_text=item.get("full_text", ""),
        language=item.get("language", "zh"),
        metadata={"extraction": item.get("extraction", {})},
    )


def _estimated_factual_claim_count(report: str) -> int:
    count = 0
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or re.match(r"^-\s+\[[^]]+\]\(https?://", stripped):
            continue
        count += max(1, len(re.findall(r"[。.!?](?:\s|$)", stripped)))
    return count
