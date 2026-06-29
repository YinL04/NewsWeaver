"""新闻生成主流程编排"""

from datetime import datetime
from pathlib import Path

import click

from .exporter import export_report_bundle
from .llm.client import LLMClient
from .llm.prompts import build_user_prompt, SYSTEM_PROMPT
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
from .utils import atomic_write_json, get_output_dir, logger


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
    """执行完整的生成流程：fetch → 读记忆 → LLM → 输出 → 更新记忆"""
    topic_name = topic_obj["name"]

    # ── 1. 采集新闻 ──
    click.echo(f'>>> 正在搜索 "{topic_name}" 相关新闻...')
    notify = progress or (lambda _stage, _percent, _message: None)
    articles = prepared_articles or _fetch_articles(config, topic_obj, limit, progress=notify)
    if not articles:
        raise RuntimeError("未找到任何文章")

    articles = rank_articles(dedupe_articles(articles), topic_obj.get("keywords", []))[:limit]
    fact_pack = build_fact_pack(topic_name, articles)
    quality_report = build_quality_report(topic_name, articles, fact_pack)
    event_clusters = build_event_clusters(articles)
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
    audit = audit_report(report, fact_pack)

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

    # ── 5. 更新 L2 记忆 ──
    click.echo(">>> 更新记忆...")
    add_structured_recent_memory(topic_name, articles_dicts, fact_pack, quality_report, report)
    click.echo(">>> 结构化记忆已更新")
    notify("complete", 100, "报告已生成并完成引用审计")

    return out_file


def _fetch_articles(config: dict, topic_obj: dict, limit: int, progress=None) -> list:
    """采集新闻文章"""
    articles = prepare_articles(config, topic_obj, limit, progress=progress)
    click.echo(f">>> 找到 {len(articles)} 篇文章")
    return articles
