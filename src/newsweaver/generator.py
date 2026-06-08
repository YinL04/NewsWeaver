"""新闻生成主流程编排"""

import json
import re
from datetime import datetime
from pathlib import Path

import click

from .config import find_topic
from .fetcher.rss import RssFetcher
from .fetcher.bing import BingFetcher
from .extractor import extract_article
from .llm.client import LLMClient
from .llm.prompts import build_user_prompt, build_memory_prompt, SYSTEM_PROMPT
from .memory.store import MemoryStore
from .utils import get_output_dir, logger


def run_generate(config: dict, topic_obj: dict, model: str, limit: int) -> Path:
    """执行完整的生成流程：fetch → 读记忆 → LLM → 输出 → 更新记忆"""
    topic_name = topic_obj["name"]

    # ── 1. 采集新闻 ──
    click.echo(f'>>> 正在搜索 "{topic_name}" 相关新闻...')
    articles = _fetch_articles(config, topic_obj, limit)
    if not articles:
        raise RuntimeError("未找到任何文章")

    # 正文提取
    click.echo(f">>> 正文提取: 共 {len(articles)} 篇")
    for a in articles:
        if not a.full_text or a.full_text == a.summary:
            a.full_text = extract_article(a.url) or a.summary

    # ── 2. 读取记忆 ──
    click.echo(">>> 读取记忆...")
    memory_store = MemoryStore(topic_name)
    memory_data = memory_store.load()
    recent = memory_data.get("recent", [])
    long_term = memory_data.get("long_term", [])
    click.echo(f">>> L2 ({len(recent)} 条记录)，L3 ({len(long_term)} 周数据)")

    # ── 3. 调用 LLM ──
    click.echo(f">>> 调用 LLM ({model}) 生成报道...")
    llm = LLMClient(
        api_key=config["llm"]["api_key"],
        base_url=config["llm"]["base_url"],
        model=model,
    )

    articles_dicts = [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
            "summary": a.summary,
            "full_text": a.full_text,
        }
        for a in articles
    ]

    user_prompt = build_user_prompt(
        topic_name=topic_name,
        articles=articles_dicts,
        recent_memory=recent[-7:] if recent else None,
        long_term_memory=long_term[-4:] if long_term else None,
    )

    report = llm.generate(SYSTEM_PROMPT, user_prompt, model=model)

    # ── 4. 保存输出 ──
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = get_output_dir()
    out_file = out_dir / f"{topic_name}_{today}.md"
    out_file.write_text(report, encoding="utf-8")
    click.echo(">>> 报道生成完成")
    click.echo(f"\n{'='*50}")
    click.echo(report[:1000] + ("..." if len(report) > 1000 else ""))
    click.echo(f"{'='*50}\n")

    # ── 5. 更新 L2 记忆 ──
    click.echo(">>> 更新记忆...")
    _update_memory(llm, topic_name, articles_dicts, memory_store)

    return out_file


def _fetch_articles(config: dict, topic_obj: dict, limit: int) -> list:
    """采集新闻文章"""
    days = config["search"]["days_back"]
    articles = []

    rss_sources = topic_obj.get("sources", [])
    if not rss_sources:
        rss_sources = ["rss"]

    # 默认 RSS 源
    if "rss" in rss_sources:
        rss = RssFetcher()
        articles.extend(rss.fetch(
            keywords=topic_obj["keywords"],
            exclude_words=topic_obj.get("exclude_words", []),
            limit=limit,
            days_back=days,
        ))

    # 自定义 RSS 源
    for src in rss_sources:
        if src.startswith("rss:"):
            url = src[4:]
            rss = RssFetcher(feed_url=url)
            articles.extend(rss.fetch(
                keywords=topic_obj["keywords"],
                exclude_words=topic_obj.get("exclude_words", []),
                limit=limit,
                days_back=days,
            ))

    # Bing News
    bing_key = config["search"].get("bing_api_key", "")
    if bing_key and "bing" in rss_sources:
        bing = BingFetcher(api_key=bing_key)
        articles.extend(bing.fetch(
            keywords=topic_obj["keywords"],
            exclude_words=topic_obj.get("exclude_words", []),
            limit=limit,
            days_back=days,
        ))

    click.echo(f">>> 找到 {len(articles)} 篇文章")
    return articles


def _update_memory(llm: LLMClient, topic_name: str, articles: list, store: MemoryStore) -> None:
    """用 LLM 提取记忆摘要并更新 L2"""
    try:
        memory_prompt = build_memory_prompt(topic_name, articles)
        raw = llm.generate("你是一个数据分析助手，只输出 JSON，不要其他内容。", memory_prompt)

        # 提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if not json_match:
            logger.warning("记忆提取失败：LLM 未返回有效 JSON")
            return

        data = json.loads(json_match.group())
        store.add_recent(
            summary=data.get("summary", ""),
            sentiment=float(data.get("sentiment", 0.5)),
            top_entities=data.get("top_entities", []),
        )
        click.echo(">>> 记忆已更新")
    except Exception as e:
        logger.warning(f"记忆更新失败: {e}")
