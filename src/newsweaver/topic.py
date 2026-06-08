"""主题管理命令：add / list / remove"""

import click

from .config import load_config, save_config, find_topic
from .utils import get_memory_dir, logger


@click.group("topic")
def topic_group():
    """管理资讯主题"""
    pass


@topic_group.command("add")
@click.option("--name", "-n", required=True, help="主题名称（唯一标识）")
@click.option("--keywords", "-k", required=True, help="逗号分隔的搜索关键词")
@click.option("--exclude", "-e", default="", help="逗号分隔的排除词")
@click.option("--sources", "-s", default="", help="逗号分隔的信源列表")
@click.option("--lang", "-l", default="zh", help="语言偏好（zh/en，默认 zh）")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def topic_add(name, keywords, exclude, sources, lang, config_path):
    """新增主题"""
    config = load_config(config_path)
    if find_topic(config, name):
        click.echo(f"错误：主题 \"{name}\" 已存在", err=True)
        raise SystemExit(1)

    topic = {
        "name": name,
        "keywords": [k.strip() for k in keywords.split(",") if k.strip()],
        "exclude_words": [w.strip() for w in exclude.split(",") if w.strip()] if exclude else [],
        "sources": [s.strip() for s in sources.split(",") if s.strip()] if sources else [],
        "language": lang,
    }
    config.setdefault("topics", []).append(topic)
    save_config(config, config_path)
    click.echo(f'✓ 主题 "{name}" 已添加')


@topic_group.command("list")
@click.option("--config", "config_path", default=None, help="配置文件路径")
def topic_list(config_path):
    """列出所有主题"""
    config = load_config(config_path)
    topics = config.get("topics", [])
    if not topics:
        click.echo("暂无主题，请使用 `newsweaver topic add` 添加")
        return
    for i, t in enumerate(topics, 1):
        kw = ", ".join(t.get("keywords", []))
        lang = t.get("language", "zh")
        src = ", ".join(t.get("sources", [])) or "默认"
        click.echo(f"  {i}. {t['name']} (keywords: {kw} | lang: {lang} | sources: {src})")


@topic_group.command("remove")
@click.option("--name", "-n", required=True, help="主题名称")
@click.option("--config", "config_path", default=None, help="配置文件路径")
@click.confirmation_option(prompt="确定删除该主题及其关联记忆？")
def topic_remove(name, config_path):
    """删除主题（含关联记忆文件）"""
    config = load_config(config_path)
    topics = config.get("topics", [])
    new_topics = [t for t in topics if t["name"] != name]
    if len(new_topics) == len(topics):
        click.echo(f"错误：主题 \"{name}\" 不存在", err=True)
        raise SystemExit(1)

    config["topics"] = new_topics
    save_config(config, config_path)

    # 删除关联记忆文件
    mem_file = get_memory_dir() / f"{name}.json"
    if mem_file.exists():
        mem_file.unlink()
        logger.info(f"已删除记忆文件: {mem_file}")

    click.echo(f'✓ 主题 "{name}" 已删除')
