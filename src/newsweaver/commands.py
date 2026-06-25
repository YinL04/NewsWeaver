"""CLI 命令定义：config / fetch / generate / memory / publish / interactive"""

import json
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import click

from .config import load_config, save_config, set_nested, get_nested, find_topic
from .pipeline import article_to_dict, build_fact_pack, build_quality_report, collect_articles
from .templates import get_topic_template, list_topic_templates
from .utils import get_output_dir, logger


REQUIRED_PACKAGES = [
    "click",
    "requests",
    "feedparser",
    "bs4",
    "lxml",
    "readability",
    "openai",
]


def _ok(label: str, detail: str = "") -> None:
    click.echo(f"[OK] {label}{': ' + detail if detail else ''}")


def _warn(label: str, detail: str = "") -> None:
    click.echo(f"[WARN] {label}{': ' + detail if detail else ''}")


def _fail(label: str, detail: str = "") -> None:
    click.echo(f"[FAIL] {label}{': ' + detail if detail else ''}")


@click.command("doctor")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def doctor_cmd(config_path):
    """检查本地环境、依赖和 NewsWeaver 配置"""
    click.echo("NewsWeaver doctor")
    click.echo("-" * 40)

    if sys.version_info >= (3, 10):
        _ok("Python", sys.version.split()[0])
    else:
        _fail("Python", "需要 Python >= 3.10")

    missing = []
    for package in REQUIRED_PACKAGES:
        if importlib.util.find_spec(package) is None:
            missing.append(package)
    if missing:
        _fail("依赖", "缺少 " + ", ".join(missing))
        click.echo("      运行: pip install -e .")
    else:
        _ok("依赖", "全部可导入")

    config = load_config(config_path)
    api_key = config.get("llm", {}).get("api_key", "")
    if api_key and api_key != "sk-your-api-key-here":
        _ok("LLM API Key", "已配置")
    else:
        _warn("LLM API Key", "尚未配置，generate 会失败")

    model = config.get("llm", {}).get("model", "")
    base_url = config.get("llm", {}).get("base_url", "")
    _ok("模型配置", f"{model} @ {base_url}")

    topics = config.get("topics", [])
    if topics:
        _ok("主题", f"{len(topics)} 个")
    else:
        _warn("主题", "还没有主题，运行 newsweaver topic add")

    out_dir = get_output_dir()
    try:
        probe = out_dir / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _ok("输出目录", str(out_dir))
    except OSError as exc:
        _fail("输出目录", str(exc))


@click.command("preview")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--limit", "-l", default=None, type=int, help="采集数量")
@click.option("--save", is_flag=True, help="保存预览 JSON 到 output/preview")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def preview_cmd(topic, limit, save, config_path):
    """预览采集结果、相关性和基础质量，不调用 LLM"""
    config = load_config(config_path)
    topic_obj = find_topic(config, topic)
    if not topic_obj:
        click.echo(f'错误：主题 "{topic}" 不存在', err=True)
        raise SystemExit(1)

    click.echo(f'>>> 正在预览 "{topic}" 的采集结果...')
    articles = collect_articles(config, topic_obj, limit or config["search"]["default_limit"])
    facts = build_fact_pack(topic, articles)
    quality = build_quality_report(topic, articles, facts)

    click.echo(
        f">>> 质量评分: {quality['score']}/100 | "
        f"{quality['article_count']} 篇 | {quality['source_count']} 个来源"
    )
    for warning in quality.get("warnings", []):
        click.echo(f"[WARN] {warning}")

    for i, article in enumerate(articles, 1):
        data = article_to_dict(article, topic_obj.get("keywords", []))
        click.echo(
            f"{i}. [{data['source']}] {data['title']} "
            f"(score={data['relevance_score']})"
        )
        click.echo(f"   {data['url']}")

    if save:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        preview_dir = get_output_dir() / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        path = preview_dir / f"{topic}_{ts}.json"
        payload = {
            "topic": topic,
            "generated_at": datetime.now().isoformat(),
            "quality": quality,
            "facts": facts,
            "articles": [article_to_dict(a, topic_obj.get("keywords", [])) for a in articles],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        click.echo(f">>> 预览已保存至 {path}")


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
@click.option("--force", is_flag=True, help="强制压缩所有 L2 记录")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def memory_compact(topic, force, config_path):
    """手动将 L2 旧数据压缩到 L3"""
    from .memory.compact import compact_memory

    count = compact_memory(topic, force=force)
    click.echo(f"✓ 已将 {count} 条 L2 记录压缩至 L3")


# ───────────────── trend 命令 ─────────────────

@click.command("trend")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--output", "-o", default=None, help="保存趋势卡片 Markdown 路径")
def trend_cmd(topic, output):
    """输出趋势卡片：热点、玩家、拐点和周期变化"""
    from .memory.trends import build_trend_cards, format_trend_cards

    cards = build_trend_cards(topic)
    text = format_trend_cards(cards)
    click.echo(text)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        click.echo(f">>> 趋势卡片已保存至 {path}")


# ───────────────── template 命令组 ─────────────────

@click.group("template")
def template_group():
    """管理内置订阅主题模板"""
    pass


@template_group.command("list")
def template_list():
    """列出内置主题模板"""
    for item in list_topic_templates():
        click.echo(f"{item['id']}: {item['name']} - {item.get('description', '')}")


@template_group.command("add")
@click.argument("template_id")
@click.option("--name", default=None, help="覆盖模板主题名称")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def template_add(template_id, name, config_path):
    """从内置模板创建主题"""
    config = load_config(config_path)
    try:
        topic = get_topic_template(template_id)
    except KeyError:
        click.echo(f"错误：模板 {template_id} 不存在，可运行 `newsweaver template list` 查看", err=True)
        raise SystemExit(1)
    if name:
        topic["name"] = name
    if find_topic(config, topic["name"]):
        click.echo(f"错误：主题 \"{topic['name']}\" 已存在", err=True)
        raise SystemExit(1)
    topic.pop("description", None)
    config.setdefault("topics", []).append(topic)
    save_config(config, config_path)
    click.echo(f"✓ 已添加模板主题：{topic['name']}")


# ───────────────── schedule 命令组 ─────────────────

@click.group("schedule")
def schedule_group():
    """管理每日/每周自动生成任务"""
    pass


@schedule_group.command("add")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--cadence", type=click.Choice(["daily", "weekly"]), default="daily", show_default=True)
@click.option("--time", "run_time", default="09:00", show_default=True, help="运行时间 HH:MM")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def schedule_add(topic, cadence, run_time, config_path):
    """新增或覆盖一个定时生成任务"""
    from .scheduler import add_job

    config = load_config(config_path)
    if not find_topic(config, topic):
        click.echo(f"错误：主题 \"{topic}\" 不存在，请先用 topic add 或 template add 创建", err=True)
        raise SystemExit(1)
    hour, minute = parse_hhmm(run_time)
    job = add_job(topic, cadence=cadence, hour=hour, minute=minute)
    click.echo(f"✓ 已添加任务 {job['id']}，下次运行：{job['next_run_at']}")


@schedule_group.command("list")
def schedule_list():
    """列出本地定时任务"""
    from .scheduler import load_schedule

    jobs = load_schedule().get("jobs", [])
    if not jobs:
        click.echo("暂无定时任务。")
        return
    for job in jobs:
        status = "enabled" if job.get("enabled", True) else "disabled"
        click.echo(
            f"{job['id']} | {job['topic']} | {job['cadence']} "
            f"{job.get('hour', 9):02d}:{job.get('minute', 0):02d} | {status} | next={job.get('next_run_at', '')}"
        )


@schedule_group.command("remove")
@click.argument("job_id")
def schedule_remove(job_id):
    """删除一个定时任务"""
    from .scheduler import remove_job

    if remove_job(job_id):
        click.echo(f"✓ 已删除任务 {job_id}")
    else:
        click.echo(f"错误：任务 {job_id} 不存在", err=True)
        raise SystemExit(1)


@schedule_group.command("run")
@click.option("--once", is_flag=True, help="只检查并运行一次到期任务")
@click.option("--interval", default=300, show_default=True, type=int, help="循环检查间隔秒数")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def schedule_run(once, interval, config_path):
    """运行本地调度器"""
    from .scheduler import run_due_jobs, run_scheduler_loop

    if once:
        results = run_due_jobs(config_path=config_path)
        if not results:
            click.echo("当前没有到期任务。")
        for result in results:
            if result.get("ok"):
                click.echo(f"✓ {result['topic']} -> {result['path']}")
            else:
                click.echo(f"✗ {result['topic']} - {result.get('error')}", err=True)
        return
    click.echo(f">>> 调度器已启动，每 {interval} 秒检查一次。按 Ctrl+C 停止。")
    run_scheduler_loop(config_path=config_path, interval_seconds=interval)


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = value.split(":", 1)
        hour = int(hour_s)
        minute = int(minute_s)
    except Exception:
        raise click.BadParameter("时间格式应为 HH:MM")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise click.BadParameter("时间范围应为 00:00 到 23:59")
    return hour, minute


# ───────────────── publish 命令 ─────────────────

@click.command("publish")
@click.option("--topic", "-t", required=True, help="主题名称")
@click.option("--platform", "-p", required=True, type=click.Choice(["twitter", "linkedin", "mastodon"]), help="目标平台")
@click.option("--kit", is_flag=True, help="只输出半自动发布素材包，不执行模拟发布")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def publish_cmd(topic, platform, kit, config_path):
    """模拟发布到社交平台"""
    from .publisher import publish_to_social

    # 查找最新生成的 .md 文件
    out_dir = get_output_dir()
    md_files = sorted(out_dir.glob(f"{topic}_*.md"), reverse=True)
    if not md_files:
        click.echo(f"错误：未找到主题 \"{topic}\" 的已生成新闻文件", err=True)
        raise SystemExit(1)

    publish_files = sorted(out_dir.glob(f"{topic}_*.publish.json"), reverse=True)
    if kit:
        if not publish_files:
            click.echo("错误：未找到发布素材包，请先运行 generate 生成 .publish.json", err=True)
            raise SystemExit(1)
        data = json.loads(publish_files[0].read_text(encoding="utf-8"))
        click.echo("# 发布素材包")
        click.echo("\n## 标题候选")
        for title in data.get("title_candidates", []):
            click.echo(f"- {title}")
        click.echo("\n## 社媒摘要")
        summaries = data.get("social_summaries", {})
        click.echo(summaries.get(platform, summaries.get("short", "")))
        click.echo("\n## 封面图 Prompt")
        click.echo(data.get("cover_prompt", ""))
        return

    content = md_files[0].read_text(encoding="utf-8")
    result = publish_to_social(platform=platform, content=content)

    click.echo(f"[Mock] 发布到 {platform}，内容长度 {len(content)} 字符")
    click.echo(f"✓ 发布模拟成功，返回 ID: {result['post_id']}")


# ───────────────── web 命令 ─────────────────

@click.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="监听地址")
@click.option("--port", default=8765, show_default=True, type=int, help="监听端口")
@click.option("--open/--no-open", "open_browser", default=True, show_default=True, help="自动打开浏览器")
def web_cmd(host, port, open_browser):
    """启动面向用户的本地 Web 前端"""
    from .webapp import serve

    serve(host=host, port=port, open_browser=open_browser)


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
