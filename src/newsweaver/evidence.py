"""Claim-level fact packs and deterministic citation auditing."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .clustering import article_id, build_event_clusters, extract_named_entities, jaccard, text_tokens
from .fetcher.base import Article


CITATION_RE = re.compile(r"\[(F\d{3,})\]")
# Every numeric assertion is high risk. Headings and source lists are excluded by
# _report_statements, so a broad rule is safer than an incomplete unit allowlist.
HIGH_RISK_RE = re.compile(r"\d")
FACTUAL_VERBS = (
    "发布", "宣布", "表示", "称", "报道", "推出", "收购", "融资", "起诉", "批准", "禁止", "增长", "下降",
    "launch", "announce", "said", "reported", "release", "acquire", "raise", "sue", "approve", "ban", "increase", "decrease",
    "grew", "rose", "fell", "reached", "achieved",
)
BOILERPLATE = ("登录", "注册", "分享到", "打开微信", "copyright", "all rights reserved", "cookie")
MIN_CITATION_SUPPORT = 0.18


def split_atomic_claims(text: str, max_claims: int = 40) -> list[dict]:
    """Split an article into small, independently citable evidence spans."""
    cleaned = re.sub(r"[\t\r ]+", " ", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z\u4e00-\u9fff])|\n{2,}", cleaned)
    claims: list[dict] = []
    seen: set[str] = set()
    for sentence in sentences:
        source_span = re.sub(r"\s+", " ", sentence).strip(" -\n")
        if not source_span or any(marker in source_span.lower() for marker in BOILERPLATE):
            continue
        parts = re.split(r"[；;]+", source_span)
        comma_parts = [part.strip() for part in re.split(r"[，,]", source_span) if part.strip()]
        factual_parts = [
            part for part in comma_parts
            if any(verb.lower() in part.lower() for verb in FACTUAL_VERBS)
        ]
        if len(factual_parts) >= 2:
            parts = comma_parts
        if len(source_span) > 360 and len(parts) == 1:
            if sum(len(part) >= 18 for part in comma_parts) >= 2:
                parts = comma_parts
        for part in parts:
            claim = re.sub(r"\s+", " ", part).strip(" -，,")
            if len(claim) < 8 and not HIGH_RISK_RE.search(claim):
                continue
            if len(claim) > 420:
                claim = claim[:417].rstrip() + "..."
            fingerprint = re.sub(r"\W+", "", claim.lower())
            if not fingerprint or fingerprint in seen:
                continue
            seen.add(fingerprint)
            claims.append({"claim": claim, "source_span": source_span})
            if len(claims) >= max_claims:
                return claims
    return claims


def build_fact_pack(topic_name: str, articles: list[Article], event_clusters: list[dict] | None = None) -> dict:
    """Build a backward-compatible claim-level evidence package."""
    clusters = event_clusters if event_clusters is not None else build_event_clusters(articles)
    article_events = {
        record.get("article_id"): cluster.get("event_id", "")
        for cluster in clusters
        for record in cluster.get("articles", [])
    }
    facts: list[dict] = []
    for article in articles:
        aid = article_id(article)
        evidence_text = article.full_text or article.summary or article.title
        atomic_claims = split_atomic_claims(evidence_text)
        if not atomic_claims:
            atomic_claims = [{"claim": article.title, "source_span": article.title}]
        base_confidence = 0.76 if article.full_text and article.full_text != article.summary else 0.62
        for item in atomic_claims:
            fact_id = f"F{len(facts) + 1:03d}"
            facts.append(
                {
                    "id": fact_id,  # v1 compatibility
                    "fact_id": fact_id,
                    "claim": item["claim"],
                    "article_id": aid,
                    "source_title": article.title,  # v1 compatibility
                    "source": article.source,
                    "url": article.url,
                    "published_at": article.published_at,
                    "source_span": item["source_span"],
                    "confidence": base_confidence,
                    "corroborating_sources": [],
                    "event_id": article_events.get(aid, ""),
                }
            )
    _attach_corroboration(facts)
    source_counts = Counter(article.source for article in articles if article.source)
    return {
        "schema_version": 2,
        "topic": topic_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count": len(articles),
        "source_count": len(source_counts),
        "claim_count": len(facts),
        "event_count": len(clusters),
        "sources": dict(source_counts),
        "facts": facts,
    }


def _attach_corroboration(facts: list[dict]) -> None:
    by_event: dict[str, list[dict]] = defaultdict(list)
    for fact in facts:
        if fact.get("event_id"):
            by_event[fact["event_id"]].append(fact)
    for group in by_event.values():
        for fact in group:
            corroborating = set()
            for other in group:
                if other is fact or not other.get("source") or other.get("source") == fact.get("source"):
                    continue
                if claim_support_score(fact.get("claim", ""), other) >= 0.34:
                    corroborating.add(other["source"])
            fact["corroborating_sources"] = sorted(corroborating)
            if corroborating:
                fact["confidence"] = round(min(0.96, float(fact["confidence"]) + 0.07 * len(corroborating)), 2)


def claim_support_score(statement: str, fact: dict) -> float:
    statement_clean = CITATION_RE.sub("", statement or "").strip()
    evidence = f"{fact.get('claim', '')} {fact.get('source_span', '')}"
    if not statement_clean or not evidence.strip():
        return 0.0
    statement_norm = re.sub(r"\W+", "", statement_clean.lower())
    evidence_norm = re.sub(r"\W+", "", evidence.lower())
    if statement_norm and (statement_norm in evidence_norm or evidence_norm in statement_norm):
        return 1.0

    statement_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", statement_clean))
    evidence_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", evidence))
    if statement_numbers and not statement_numbers.issubset(evidence_numbers):
        return 0.0
    token_score = jaccard(text_tokens(statement_clean), text_tokens(evidence))
    entity_score = jaccard(extract_named_entities(statement_clean), extract_named_entities(evidence))
    number_score = 1.0 if statement_numbers and statement_numbers.issubset(evidence_numbers) else 0.0
    return round(0.72 * token_score + 0.18 * entity_score + 0.10 * number_score, 4)


def audit_report(report: str, fact_pack: dict) -> dict:
    """Return a structured, deterministic evidence audit for a Markdown report."""
    facts = fact_pack.get("facts", []) if isinstance(fact_pack, dict) else []
    by_id = {(fact.get("fact_id") or fact.get("id")): fact for fact in facts if fact.get("fact_id") or fact.get("id")}
    valid_ids = set(by_id)
    all_cited = set(CITATION_RE.findall(report or ""))
    invalid_ids = sorted(all_cited - valid_ids)
    cited_ids = sorted(all_cited & valid_ids)
    uncited_claims: list[str] = []
    unsupported_claims: list[dict] = []
    high_risk_without_evidence: list[str] = []

    for statement in _report_statements(report or ""):
        citations = CITATION_RE.findall(statement)
        factual = _is_key_factual_statement(statement)
        high_risk = bool(HIGH_RISK_RE.search(CITATION_RE.sub("", statement)))
        if factual and not citations:
            uncited_claims.append(_excerpt(statement))
        if high_risk and not any(citation in valid_ids for citation in citations):
            high_risk_without_evidence.append(_excerpt(statement))
        supported_ids = []
        support_scores = {}
        for citation in citations:
            if citation not in by_id:
                continue
            score = claim_support_score(statement, by_id[citation])
            support_scores[citation] = score
            if score >= MIN_CITATION_SUPPORT:
                supported_ids.append(citation)
        if citations and not supported_ids and any(citation in valid_ids for citation in citations):
            unsupported_claims.append(
                {
                    "claim": _excerpt(statement),
                    "citation_ids": [citation for citation in citations if citation in valid_ids],
                    "support_scores": support_scores,
                }
            )

    uncited_claims = _dedupe(uncited_claims)[:20]
    high_risk_without_evidence = _dedupe(high_risk_without_evidence)[:20]
    unsupported_claims = unsupported_claims[:20]
    failure_reasons = []
    if invalid_ids:
        failure_reasons.append({"code": "invalid_citation_id", "message": "存在 Fact Pack 中不存在的引用编号", "items": invalid_ids})
    if uncited_claims:
        failure_reasons.append({"code": "uncited_key_claim", "message": "存在没有引用的关键事实陈述", "items": uncited_claims})
    if unsupported_claims:
        failure_reasons.append({"code": "citation_not_supporting_claim", "message": "引用与对应陈述缺少可验证的文本支持", "items": unsupported_claims})
    if high_risk_without_evidence:
        failure_reasons.append({"code": "high_risk_without_evidence", "message": "数字、日期或金额等高风险信息缺少有效证据", "items": high_risk_without_evidence})

    checks = {
        "citation_ids_exist": {"passed": not invalid_ids, "count": len(invalid_ids), "items": invalid_ids},
        "key_claims_cited": {"passed": not uncited_claims, "count": len(uncited_claims), "items": uncited_claims},
        "citations_support_claims": {"passed": not unsupported_claims, "count": len(unsupported_claims), "items": unsupported_claims},
        "fact_pack_only": {"passed": not uncited_claims, "count": len(uncited_claims), "items": uncited_claims},
        "high_risk_evidence": {"passed": not high_risk_without_evidence, "count": len(high_risk_without_evidence), "items": high_risk_without_evidence},
    }
    passed = not failure_reasons
    warnings = [reason["message"] for reason in failure_reasons]
    coverage = round(len(cited_ids) / max(1, len(valid_ids)) * 100)
    return {
        "schema_version": 2,
        "status": "pass" if passed else "failed",
        "passed": passed,
        "valid": passed,  # v1 compatibility
        "citation_coverage": coverage,
        "cited_ids": cited_ids,
        "invalid_ids": invalid_ids,
        "uncited_claims": uncited_claims,
        "unsupported_claims": unsupported_claims,
        "outside_fact_pack_claims": uncited_claims,
        "high_risk_without_evidence": high_risk_without_evidence,
        "numeric_without_citation": high_risk_without_evidence,  # v1 compatibility
        "checks": checks,
        "failure_reasons": failure_reasons,
        "warnings": warnings,
    }


def finalize_audit(audit: dict, repair_attempts: int, history: list[dict] | None = None) -> dict:
    result = dict(audit)
    result["repair_attempts"] = repair_attempts
    result["audit_history"] = history or []
    if result.get("passed"):
        result["status"] = "repaired" if repair_attempts else "pass"
        result["valid"] = True
    else:
        result["status"] = "needs_review"
        result["valid"] = False
    return result


def audit_allows_memory(audit: dict | None) -> bool:
    return bool(audit and audit.get("passed") and audit.get("status") in {"pass", "repaired"})


def _report_statements(report: str) -> list[str]:
    statements = []
    in_sources = False
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            in_sources = any(label in line.lower() for label in ("参考来源", "references", "sources"))
            continue
        if in_sources or not line or line.startswith("#") or re.fullmatch(r"\|?\s*[-:| ]+", line):
            continue
        if re.match(r"^-\s+\[[^]]+\]\(https?://", line):
            continue
        line = re.sub(r"^[>|*\-\s]+", "", line)
        # Treat citations immediately after punctuation as belonging to that sentence.
        line = re.sub(
            r"([。！？.!?])\s+(\[F\d{3,}\](?:\s*\[F\d{3,}\])*)",
            r" \2\1",
            line,
        )
        if "|" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
            line = "；".join(cells)
        for part in re.split(r"(?<=[。！？!?])\s+|\n+", line):
            if part.strip():
                statements.append(part.strip())
    return statements


def _is_key_factual_statement(statement: str) -> bool:
    clean = CITATION_RE.sub("", statement).strip()
    if len(clean) < 6:
        return False
    if HIGH_RISK_RE.search(clean):
        return True
    lowered = clean.lower()
    has_verb = any(verb.lower() in lowered for verb in FACTUAL_VERBS)
    has_entity = bool(extract_named_entities(clean)) or bool(re.search(r"\b[A-Z][A-Za-z0-9_.+-]{1,}\b", clean))
    direct_quote = bool(re.search(r"[\"“”‘’'][^\"“”‘’']{3,}[\"“”‘’']", clean))
    return has_entity and (has_verb or direct_quote)


def _excerpt(value: str, limit: int = 220) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
