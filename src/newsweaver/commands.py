"""CLI 命令定义：config / fetch / generate / memory / publish / interactive"""

import json
from datetime import datetime
from pathlib import Path

import click

from .config import load_config, save_config, set_nested, get_nested, find_topic
from .utils import get_output_dir, logger


# ───────────────── config 命令组 ─────────────────

@click.group("config")
def config_group():
    """管理配置项"""
    pass


@config_group.command("set")
@click.option("--key", "-k", required=True, help="配置路径（如 llm.model）")
@click.option("--value", "-v", required=True, help="配置值")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def config_set(key, value, config_path):
    """修改配置项"""
    config = load_config(config_path)
    set_nested(config, key, value)
    save_config(config, config_path)
    click.echo(f"✓ {key} = {value}")


@config_group.command("show")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def config_show(config_path):
    """显示当前配置"""
    config = load_config(config_path)
    click.echo(json.dumps(config, ensure_ascii=False, indent=2))


# ───────────────── fetch 命令 ─────────────────

@click.command("fetch")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--limit", "-l", default=None, type=int, help="搜索数量")
@click.option("--days", "-d", default=None, type=int, help="时间范围天数")
@click.option("--config", "config_path", default=None, help="配置文件路径")
@click.pass_context
def fetch_cmd(ctx, topic, limit, days, config_path):
    """搜索并保存原始文章（调试用）"""
    from .fetcher.rss import RssFetcher
    from .fetcher.bing import BingFetcher
    from .extractor import extract_article

    config = load_config(config_path)
    topic_obj = find_topic(config, topic)
    if not topic_obj:
        click.echo(f"错误：主题 \"{topic}\" 不存在，请先使用 `newsweaver topic add` 添加", err=True)
        raise SystemExit(1)

    limit = limit or config["search"]["default_limit"]
    days = days or config["search"]["days_back"]

    click.echo(f'>>> 正在搜索 "{topic}" 相关新闻...')

    articles = []

    # RSS 源
    rss_sources = topic_obj.get("sources", [])
    if not rss_sources or any(s.startswith("rss:") or s in ("rss",) for s in rss_sources):
        rss = RssFetcher()
        rss_articles = rss.fetch(
            keywords=topic_obj["keywords"],
            exclude_words=topic_obj.get("exclude_words", []),
            limit=limit,
            days_back=days,
        )
        articles.extend(rss_articles)
        click.echo(f">>> RSS: 找到 {len(rss_articles)} 篇")

    # 自定义 RSS 源
    for src in rss_sources:
        if src.startswith("rss:"):
            url = src[4:]
            rss = RssFetcher(feed_url=url)
            custom_articles = rss.fetch(
                keywords=topic_obj["keywords"],
                exclude_words=topic_obj.get("exclude_words", []),
                limit=limit,
                days_back=days,
            )
            articles.extend(custom_articles)

    # Bing News
    bing_key = config["search"].get("bing_api_key", "")
    if bing_key and "bing" in rss_sources:
        bing = BingFetcher(api_key=bing_key)
        bing_articles = bing.fetch(
            keywords=topic_obj["keywords"],
            exclude_words=topic_obj.get("exclude_words", []),
            limit=limit,
            days_back=days,
        )
        articles.extend(bing_articles)
        click.echo(f">>> Bing: 找到 {len(bing_articles)} 篇")

    if not articles:
        click.echo("未找到任何文章，请检查主题关键词或信源配置")
        raise SystemExit(1)

    # 正文提取
    click.echo(f">>> 正文提取: 共 {len(articles)} 篇")
    for a in articles:
        if not a.full_text or a.full_text == a.summary:
            a.full_text = extract_article(a.url) or a.summary

    # 保存原始数据
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = get_output_dir() / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{topic}_{ts}.json"
    raw_data = {
        "topic": topic,
        "fetched_at": datetime.now().isoformat(),
        "count": len(articles),
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "published_at": a.published_at,
                "summary": a.summary,
                "full_text": a.full_text,
                "language": a.language,
            }
            for a in articles
        ],
    }
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    click.echo(f">>> 已保存至 {raw_file}")


# ───────────────── generate 命令 ─────────────────

@click.command("generate")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--model", "-m", default=None, help="覆盖配置中的 LLM 模型")
@click.option("--limit", "-l", default=None, type=int, help="搜索数量")
@click.option("--config", "config_path", default=None, help="配置文件路径")
@click.pass_context
def generate_cmd(ctx, topic, model, limit, config_path):
    """搜索 + 读记忆 + LLM 生成新闻报道"""
    from .generator import run_generate

    config = load_config(config_path)
    topic_obj = find_topic(config, topic)
    if not topic_obj:
        click.echo(f"错误：主题 \"{topic}\" 不存在", err=True)
        raise SystemExit(1)

    model = model or config["llm"]["model"]
    limit = limit or config["search"]["default_limit"]

    try:
        output_path = run_generate(config, topic_obj, model=model, limit=limit)
        click.echo(f">>> 报道已保存至 {output_path}")
    except Exception as e:
        click.echo(f"错误：生成失败 - {e}", err=True)
        raise SystemExit(1)


# ───────────────── memory 命令组 ─────────────────

@click.group("memory")
def memory_group():
    """管理三层记忆"""
    pass


@memory_group.command("show")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def memory_show(topic, config_path):
    """显示 L2 和 L3 记忆内容"""
    from .memory.store import MemoryStore

    store = MemoryStore(topic)
    data = store.load()

    recent = data.get("recent", [])
    long_term = data.get("long_term", [])

    click.echo(f"  [L2 近期记忆] {len(recent)} 条记录")
    for r in recent:
        entities = ", ".join(r.get("top_entities", []))
        click.echo(f"    {r['date']} | 情感: {r.get('sentiment', 'N/A')} | 实体: {entities}")

    click.echo(f"  [L3 长期趋势] {len(long_term)} 周")
    for lt in long_term:
        entities = ", ".join(lt.get("top_entities", []))
        click.echo(
            f"    {lt['week_start']} | {lt.get('article_count', 0)} 篇 | "
            f"均情感: {lt.get('avg_sentiment', 'N/A')} | 实体: {entities}"
        )


@memory_group.command("compact")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def memory_compact(topic, config_path):
    """手动将 L2 旧数据压缩到 L3"""
    from .memory.compact import compact_memory

    count = compact_memory(topic)
    click.echo(f"✓ 已将 {count} 条 L2 记录压缩至 L3")


# ───────────────── publish 命令 ─────────────────

@click.command("publish")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--platform", "-p", required=True, type=click.Choice(["twitter", "linkedin", "mastodon"]), help="目标平台")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def publish_cmd(topic, platform, config_path):
    """模拟发布到社交平台"""
    from .publisher import publish_to_social

    # 查找最新生成的 .md 文件
    out_dir = get_output_dir()
    md_files = sorted(out_dir.glob(f"{topic}_*.md"), reverse=True)
    if not md_files:
        click.echo(f"错误：未找到主题 \"{topic}\" 的已生成新闻文件", err=True)
        raise SystemExit(1)

    content = md_files[0].read_text(encoding="utf-8")
    result = publish_to_social(platform=platform, content=content)

    click.echo(f"[Mock] 发布到 {platform}，内容长度 {len(content)} 字符")
    click.echo(f"✓ 发布模拟成功，返回 ID: {result['post_id']}")


# ───────────────── interactive 命令 ─────────────────

@click.command("interactive")
@click.option("--config", "config_path", default=None, help="配置文件路径")
@click.pass_context
def interactive_cmd(ctx, config_path):
    """交互式模式：引导式操作"""
    click.echo("=" * 50)
    click.echo("  NewsWeaver 交互式模式")
    click.echo("=" * 50)
    click.echo()

    config = load_config(config_path)

    # 检查 LLM 配置
    api_key = config.get("llm", {}).get("api_key", "")
    if not api_key:
        click.echo("[提示] 尚未配置 LLM API Key")
        click.echo("  可以通过以下方式配置：")
        click.echo("  1. 创建 .env 文件，添加 NEWSWEAVER_LLM_API_KEY=your-key")
        click.echo("  2. 运行: newsweaver config set --key llm.api_key --value your-key")
        click.echo()

    while True:
        click.echo("-" * 50)
        click.echo("请选择操作：")
        click.echo("  1. 查看已有主题")
        click.echo("  2. 添加新主题")
        click.echo("  3. 删除主题")
        click.echo("  4. 采集新闻（fetch）")
        click.echo("  5. 生成报道（generate）")
        click.echo("  6. 查看记忆")
        click.echo("  7. 压缩记忆")
        click.echo("  8. 发布报道")
        click.echo("  0. 退出")
        click.echo()

        choice = click.prompt("请输入选项编号", type=click.Choice(["0", "1", "2", "3", "4", "5", "6", "7", "8"]), show_choices=False)

        if choice == "0":
            click.echo("再见！")
            break

        elif choice == "1":
            _interactive_list_topics(config)

        elif choice == "2":
            _interactive_add_topic(config, config_path)

        elif choice == "3":
            _interactive_remove_topic(config, config_path)

        elif choice == "4":
            _interactive_fetch(config)

        elif choice == "5":
            _interactive_generate(config)

        elif choice == "6":
            _interactive_memory_show()

        elif choice == "7":
            _interactive_memory_compact()

        elif choice == "8":
            _interactive_publish()

        click.echo()


def _interactive_list_topics(config: dict):
    """交互式：列出主题"""
    topics = config.get("topics", [])
    if not topics:
        click.echo("\n暂无主题，请先添加。")
        return
    click.echo(f"\n当前共有 {len(topics)} 个主题：")
    for i, t in enumerate(topics, 1):
        kw = ", ".join(t.get("keywords", []))
        click.echo(f"  {i}. {t['name']} (关键词: {kw})")


def _interactive_add_topic(config: dict, config_path: str | None):
    """交互式：添加主题"""
    click.echo()
    name = click.prompt("主题名称")
    if find_topic(config, name):
        click.echo(f'错误：主题 "{name}" 已存在')
        return
    keywords = click.prompt("关键词（逗号分隔）")
    exclude = click.prompt("排除词（逗号分隔，可留空）", default="")
    lang = click.prompt("语言", type=click.Choice(["zh", "en"]), default="zh")

    topic = {
        "name": name,
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
        "exclude_words": [w.strip() for w in exclude.split(",") if w.strip()] if exclude else [],
        "sources": [],
        "language": lang,
    }
    config.setdefault("topics", []).append(topic)
    save_config(config, config_path)
    click.echo(f'✓ 主题 "{name}" 已添加')


def _interactive_remove_topic(config: dict, config_path: str | None):
    """交互式：删除主题"""
    topics = config.get("topics", [])
    if not topics:
        click.echo("\n暂无主题。")
        return
    _interactive_list_topics(config)
    name = click.prompt("\n要删除的主题名称")
    if not find_topic(config, name):
        click.echo(f'错误：主题 "{name}" 不存在')
        return
    if not click.confirm(f'确定删除主题 "{name}" 及其关联记忆？'):
        return
    config["topics"] = [t for t in topics if t["name"] != name]
    save_config(config, config_path)
    from .utils import get_memory_dir
    mem_file = get_memory_dir() / f"{name}.json"
    if mem_file.exists():
        mem_file.unlink()
    click.echo(f'✓ 主题 "{name}" 已删除')


def _interactive_fetch(config: dict):
    """交互式：采集新闻"""
    topics = config.get("topics", [])
    if not topics:
        click.echo("\n暂无主题，请先添加。")
        return
    _interactive_list_topics(config)
    name = click.prompt("\n要采集的主题名称")
    topic_obj = find_topic(config, name)
    if not topic_obj:
        click.echo(f'错误：主题 "{name}" 不存在')
        return
    limit = click.prompt("采集数量", default=config["search"]["default_limit"], type=int)
    days = click.prompt("时间范围（天）", default=config["search"]["days_back"], type=int)

    click.echo()
    # 复用 fetch_cmd 的逻辑
    from .fetcher.rss import RssFetcher
    from .extractor import extract_article

    click.echo(f'>>> 正在搜索 "{name}" 相关新闻...')
    articles = []
    rss = RssFetcher()
    rss_articles = rss.fetch(
        keywords=topic_obj["keywords"],
        exclude_words=topic_obj.get("exclude_words", []),
        limit=limit,
        days_back=days,
    )
    articles.extend(rss_articles)
    click.echo(f">>> RSS: 找到 {len(rss_articles)} 篇")

    if not articles:
        click.echo("未找到任何文章")
        return

    click.echo(f">>> 正文提取: 共 {len(articles)} 篇")
    for a in articles:
        if not a.full_text or a.full_text == a.summary:
            a.full_text = extract_article(a.url) or a.summary

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = get_output_dir() / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{name}_{ts}.json"
    raw_data = {
        "topic": name,
        "fetched_at": datetime.now().isoformat(),
        "count": len(articles),
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "published_at": a.published_at,
                "summary": a.summary,
                "full_text": a.full_text,
                "language": a.language,
            }
            for a in articles
        ],
    }
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    click.echo(f">>> 已保存至 {raw_file}")


def _interactive_generate(config: dict):
    """交互式：生成报道"""
    topics = config.get("topics", [])
    if not topics:
        click.echo("\n暂无主题，请先添加。")
        return
    _interactive_list_topics(config)
    name = click.prompt("\n要生成报道的主题名称")
    topic_obj = find_topic(config, name)
    if not topic_obj:
        click.echo(f'错误：主题 "{name}" 不存在')
        return
    model = click.prompt("LLM 模型", default=config["llm"]["model"])
    limit = click.prompt("采集数量", default=config["search"]["default_limit"], type=int)

    click.echo()
    from .generator import run_generate
    try:
        output_path = run_generate(config, topic_obj, model=model, limit=limit)
        click.echo(f">>> 报道已保存至 {output_path}")
    except Exception as e:
        click.echo(f"错误：生成失败 - {e}")


def _interactive_memory_show():
    """交互式：查看记忆"""
    name = click.prompt("主题名称")
    click.echo()
    from .memory.store import MemoryStore
    store = MemoryStore(name)
    data = store.load()
    recent = data.get("recent", [])
    long_term = data.get("long_term", [])
    click.echo(f"  [L2 近期记忆] {len(recent)} 条记录")
    for r in recent:
        entities = ", ".join(r.get("top_entities", []))
        click.echo(f"    {r['date']} | 情感: {r.get('sentiment', 'N/A')} | 实体: {entities}")
    click.echo(f"  [L3 长期趋势] {len(long_term)} 周")
    for lt in long_term:
        entities = ", ".join(lt.get("top_entities", []))
        click.echo(f"    {lt['week_start']} | {lt.get('article_count', 0)} 篇 | 均情感: {lt.get('avg_sentiment', 'N/A')} | 实体: {entities}")


def _interactive_memory_compact():
    """交互式：压缩记忆"""
    name = click.prompt("主题名称")
    click.echo()
    from .memory.compact import compact_memory
    count = compact_memory(name)
    click.echo(f"✓ 已将 {count} 条 L2 记录压缩至 L3")


def _interactive_publish():
    """交互式：发布报道"""
    name = click.prompt("主题名称")
    platform = click.prompt("目标平台", type=click.Choice(["twitter", "linkedin", "mastodon"]))
    click.echo()
    from .publisher import publish_to_social
    out_dir = get_output_dir()
    md_files = sorted(out_dir.glob(f"{name}_*.md"), reverse=True)
    if not md_files:
        click.echo(f'错误：未找到主题 "{name}" 的已生成新闻文件')
        return
    content = md_files[0].read_text(encoding="utf-8")
    result = publish_to_social(platform=platform, content=content)
    click.echo(f"[Mock] 发布到 {platform}，内容长度 {len(content)} 字符")
    click.echo(f"✓ 发布模拟成功，返回 ID: {result['post_id']}")
