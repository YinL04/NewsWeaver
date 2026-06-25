"""Multi-format export and semi-automatic publishing assets."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from .utils import atomic_write_json


def export_report_bundle(report_path: Path, report_text: str, topic_name: str, fact_pack: dict, quality_report: dict) -> dict:
    """Export Markdown report into HTML, WeChat draft, email summary, and publish kit."""
    html_path = report_path.with_suffix(".html")
    wechat_path = report_path.with_suffix(".wechat.md")
    email_path = report_path.with_suffix(".email.md")
    publish_path = report_path.with_suffix(".publish.json")

    html_path.write_text(markdown_to_html(report_text, title=f"{topic_name} 资讯报告"), encoding="utf-8")
    wechat_path.write_text(build_wechat_draft(report_text, fact_pack), encoding="utf-8")
    email_path.write_text(build_email_summary(report_text, topic_name, quality_report), encoding="utf-8")
    atomic_write_json(publish_path, build_publish_kit(report_text, topic_name, fact_pack, quality_report))

    return {
        "html": str(html_path),
        "wechat": str(wechat_path),
        "email": str(email_path),
        "publish": str(publish_path),
    }


def markdown_to_html(markdown: str, title: str) -> str:
    body = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line:
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append("")
            continue
        if line.startswith("# "):
            close_list(body, in_list)
            in_list = False
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list(body, in_list)
            in_list = False
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            close_list(body, in_list)
            in_list = False
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("> "):
            close_list(body, in_list)
            in_list = False
            body.append(f"<blockquote>{inline_markdown(line[2:])}</blockquote>")
        elif line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline_markdown(line[2:])}</li>")
        else:
            close_list(body, in_list)
            in_list = False
            body.append(f"<p>{inline_markdown(line)}</p>")
    close_list(body, in_list)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ margin: 0; background: #f4f6f3; color: #17231d; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 40px 22px; background: #fff; }}
    h1 {{ font-size: 30px; line-height: 1.2; }}
    h2 {{ margin-top: 32px; padding-top: 20px; border-top: 1px solid #dce4da; }}
    p, li {{ line-height: 1.78; }}
    blockquote {{ margin: 18px 0; padding: 14px 16px; border-left: 4px solid #0f6b52; background: #e1f3ec; }}
    a {{ color: #0f6b52; }}
  </style>
</head>
<body><main>
{chr(10).join(body)}
</main></body></html>
"""


def close_list(body: list[str], in_list: bool) -> None:
    if in_list:
        body.append("</ul>")


def inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def build_wechat_draft(report_text: str, fact_pack: dict) -> str:
    lead = extract_lead(report_text)
    sources = fact_pack.get("facts", [])[:8]
    lines = [
        "# 公众号草稿",
        "",
        "## 标题",
        extract_title(report_text),
        "",
        "## 摘要",
        lead,
        "",
        "## 正文",
        report_text,
        "",
        "## 来源清单",
    ]
    lines.extend([f"- [{item.get('source_title')}]({item.get('url')}) - {item.get('source')}" for item in sources])
    return "\n".join(lines).strip() + "\n"


def build_email_summary(report_text: str, topic_name: str, quality_report: dict) -> str:
    bullets = extract_bullets(report_text, limit=5)
    lines = [
        f"# {topic_name} 邮件摘要",
        "",
        f"质量评分：{quality_report.get('score', 0)}/100",
        "",
        "## 30 秒看完",
    ]
    lines.extend([f"- {item}" for item in bullets])
    lines.extend(["", "## 阅读完整报告", "请查看同名 Markdown 或 HTML 文件。"])
    return "\n".join(lines).strip() + "\n"


def build_publish_kit(report_text: str, topic_name: str, fact_pack: dict, quality_report: dict) -> dict:
    title = extract_title(report_text)
    lead = extract_lead(report_text)
    bullets = extract_bullets(report_text, limit=4)
    return {
        "topic": topic_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quality_score": quality_report.get("score", 0),
        "title_candidates": [
            title,
            f"{topic_name} 本期关键变化：{lead[:42]}",
            f"看懂 {topic_name}：{lead[:36]}",
        ],
        "social_summaries": {
            "short": lead[:120],
            "thread": bullets,
            "linkedin": f"{lead}\n\n" + "\n".join(f"- {item}" for item in bullets),
        },
        "cover_prompt": f"一张用于资讯报告封面的专业商业插画，主题是 {topic_name}，画面包含新闻流、趋势曲线、关键企业节点，清爽科技感，适合公众号封面，不要文字。",
        "source_count": fact_pack.get("source_count", 0),
        "article_count": fact_pack.get("article_count", 0),
    }


def extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "资讯报告"


def extract_lead(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("> "):
            return line[2:].strip()
    paragraphs = [line.strip() for line in markdown.splitlines() if line.strip() and not line.startswith("#")]
    return paragraphs[0] if paragraphs else ""


def extract_bullets(markdown: str, limit: int = 5) -> list[str]:
    bullets = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:])
        elif stripped and not stripped.startswith("#") and not stripped.startswith(">") and len(stripped) > 32:
            bullets.append(stripped[:120])
        if len(bullets) >= limit:
            break
    return bullets
