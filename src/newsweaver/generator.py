"""新闻生成主流程编排"""

from datetime import datetime
from pathlib import Path

import click

from .exporter import export_report_bundle
from .llm.client import LLMClient
from .llm.prompts import (
    REPAIR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_user_prompt,
)
from .memory.store import MemoryStore
from .memory.trends import add_structured_recent_memory, auto_compact_memory, render_memory_for_prompt
from .pipeline import (
    article_to_dict,
    audit_report,
    build_event_clusters,
    build_fact_pack,
    build_quality_report,
    dedupe_articles,
    prepare_articles,
    rank_articles,
    write_artifacts,
)
from .evidence import audit_allows_memory, finalize_audit
from .utils import atomic_write_json, get_output_dir


class QualityGateError(RuntimeError):
    def __init__(self, quality: dict):
        self.quality = quality
        super().__init__("素材未达到生成门槛：" + "；".join(quality.get("blockers", [])))


def run_generate(
    config: dict,
    topic_obj: dict,
    model: str,
    limit: int,
    prepared_articles: list | None = None,
    force: bool = False,
    progress=None,
) -> Path:
    """执行完整流程：fetch → evidence → generate → audit/repair → save → memory。"""
    topic_name = topic_obj["name"]

    # ── 1. 采集新闻 ──
    click.echo(f'>>> 正在搜索 "{topic_name}" 相关新闻...')
    notify = progress or (lambda _stage, _percent, _message: None)
    articles = prepared_articles or _fetch_articles(config, topic_obj, limit, progress=notify)
    if not articles:
        raise RuntimeError("未找到任何文章")

    articles = rank_articles(
        dedupe_articles(articles),
        topic_obj.get("keywords", []),
        source_quality=config.get("search", {}).get("source_quality"),
    )[:limit]
    event_clusters = build_event_clusters(articles)
    fact_pack = build_fact_pack(topic_name, articles, event_clusters=event_clusters)
    quality_report = build_quality_report(topic_name, articles, fact_pack)
    click.echo(
        f">>> 质量评分: {quality_report['score']}/100 "
        f"({quality_report['article_count']} 篇, {quality_report['source_count']} 个来源)"
    )
    if not quality_report.get("ready") and not force:
        raise QualityGateError(quality_report)

    # ── 2. 读取记忆 ──
    click.echo(">>> 读取记忆...")
    notify("memory", 66, "正在读取历史趋势")
    memory_store = MemoryStore(topic_name)
    compacted = auto_compact_memory(topic_name)
    if compacted:
        click.echo(f">>> 自动压缩记忆: {compacted} 条 L2 -> L3")
    memory_data = memory_store.load()
    recent = memory_data.get("recent", [])
    long_term = memory_data.get("long_term", [])
    click.echo(f">>> L2 ({len(recent)} 条记录)，L3 ({len(long_term)} 周数据)")
    trend_memory = render_memory_for_prompt(memory_data)

    # ── 3. 调用 LLM ──
    click.echo(f">>> 调用 LLM ({model}) 生成报道...")
    notify("generate", 74, f"正在调用 {model} 生成报告")
    llm = LLMClient(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
        model=model,
    )

    articles_dicts = [article_to_dict(a, topic_obj.get("keywords", [])) for a in articles]

    user_prompt = build_user_prompt(
        topic_name=topic_name,
        articles=articles_dicts,
        recent_memory=recent[-7:] if recent else None,
        long_term_memory=long_term[-4:] if long_term else None,
        fact_pack=fact_pack,
        quality_report=quality_report,
        trend_memory=trend_memory,
        preferences=topic_obj.get("preferences", {}),
    )

    report = llm.generate(SYSTEM_PROMPT, user_prompt, model=model)
    notify("audit", 88, "正在检查引用与数字陈述")
    report, audit = audit_and_repair_report(llm, report, fact_pack, model=model, max_repairs=2, progress=notify)

    # ── 4. 保存输出 ──
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = get_output_dir()
    out_file = out_dir / f"{topic_name}_{today}.md"
    if out_file.exists():
        out_file = out_dir / f"{topic_name}_{today}_{datetime.now().strftime('%H%M%S')}.md"
    out_file.write_text(report, encoding="utf-8")
    artifact_paths = write_artifacts(out_file, fact_pack, quality_report, event_clusters)
    audit_path = out_file.with_suffix(".audit.json")
    atomic_write_json(audit_path, audit)
    export_paths = export_report_bundle(out_file, report, topic_name, fact_pack, quality_report)
    click.echo(">>> 报道生成完成")
    click.echo(f">>> 事实包: {artifact_paths['facts']}")
    click.echo(f">>> 质量报告: {artifact_paths['quality']}")
    click.echo(f">>> HTML: {export_paths['html']}")
    click.echo(f">>> 发布素材包: {export_paths['publish']}")
    click.echo(f"\n{'='*50}")
    click.echo(report[:1000] + ("..." if len(report) > 1000 else ""))
    click.echo(f"{'='*50}\n")

    # ── 5. 仅让审计通过的事实进入长期记忆 ──
    if audit_allows_memory(audit):
        click.echo(">>> 更新记忆...")
        add_structured_recent_memory(
            topic_name,
            articles_dicts,
            fact_pack,
            quality_report,
            report,
            audit_report=audit,
        )
        click.echo(">>> 结构化记忆已更新")
    else:
        click.echo(">>> 引用审计仍未通过：草稿已保存，未写入趋势记忆")
    notify(
        "complete",
        100,
        "报告已修复并通过审计" if audit.get("status") == "repaired" else (
            "报告已生成并通过审计" if audit.get("status") == "pass" else "草稿需要人工复核，未更新记忆"
        ),
    )

    return out_file


def _fetch_articles(config: dict, topic_obj: dict, limit: int, progress=None) -> list:
    """采集新闻文章"""
    articles = prepare_articles(config, topic_obj, limit, progress=progress)
    click.echo(f">>> 找到 {len(articles)} 篇文章")
    return articles


def audit_and_repair_report(
    llm,
    report: str,
    fact_pack: dict,
    model: str | None = None,
    max_repairs: int = 2,
    progress=None,
) -> tuple[str, dict]:
    """Audit, repair at most twice, and audit after every repair."""
    notify = progress or (lambda _stage, _percent, _message: None)
    history = []
    repair_attempts = 0
    current = report
    while True:
        audit = audit_report(current, fact_pack)
        history.append(
            {
                "attempt": repair_attempts,
                "status": audit.get("status"),
                "passed": audit.get("passed", False),
                "failure_reasons": audit.get("failure_reasons", []),
            }
        )
        if audit.get("passed") or repair_attempts >= max_repairs:
            return current, finalize_audit(audit, repair_attempts, history)
        repair_attempts += 1
        notify("repair", 88 + min(8, repair_attempts * 3), f"引用审计失败，正在自动修复 {repair_attempts}/{max_repairs}")
        try:
            current = llm.generate(
                REPAIR_SYSTEM_PROMPT,
                build_repair_prompt(current, fact_pack, audit),
                model=model,
            )
        except Exception as exc:
            audit = dict(audit)
            failure = {
                "code": "repair_call_failed",
                "message": "自动修复调用失败，保留原草稿供人工复核",
                "items": [str(exc)],
            }
            audit["failure_reasons"] = [*audit.get("failure_reasons", []), failure]
            audit["warnings"] = [*audit.get("warnings", []), failure["message"]]
            audit["passed"] = False
            audit["valid"] = False
            return current, finalize_audit(audit, repair_attempts, history)
