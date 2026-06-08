"""Prompt 模板管理"""

from pathlib import Path

from ..utils import truncate


def _load_skill() -> str:
    """加载 skill.md 写作指南"""
    skill_path = Path(__file__).parent.parent.parent.parent / "skill.md"
    if skill_path.exists():
        return skill_path.read_text(encoding="utf-8")
    return ""


SKILL_CONTENT = _load_skill()

SYSTEM_PROMPT = f"""你是一位资深的自媒体新闻编辑，擅长将碎片化的新闻素材串联成有深度、有观点的完整报道。

你的写作风格：
- 说人话，不要官方腔和公关稿味道
- 敢下判断，基于事实给出你的分析
- 用数据说话，有数字就用数字
- 长短句交替，节奏感强
- 串联线索，发现趋势，预判未来

你的任务是根据提供的新闻素材，生成一篇**完整的、有深度的自媒体风格新闻报道**，不是简单的新闻摘要。

{SKILL_CONTENT}"""

USER_PROMPT_TEMPLATE = """请根据以下素材，写一篇完整的自媒体风格新闻报道。

## 主题：{topic_name}

## 本次采集的新闻素材（{article_count} 篇）

{articles_text}

{memory_section}

## 写作要求

1. **不是摘要，是报道**：不要逐条罗列新闻，要串联、分析、下判断
2. **有深度分析**：解释"为什么"和"意味着什么"，不只是"发生了什么"
3. **有观点**：基于事实给出你的洞察和预判
4. **有导语**：用一句话抓住读者注意力
5. **有节奏**：段落不要太长，重要观点加粗强调
6. **有来源**：关键事实引用原文链接

请严格按照以下结构输出：

# {topic_name} 资讯报道 – {date}

> 一句话导语（用最有冲击力的事实或观点抓住读者）

## 核心事件

（不要逐条罗列，每个事件要讲清楚：发生了什么 → 为什么重要 → 对行业意味着什么）

## 深度分析

（串联线索、发现趋势、预判未来。这是文章的核心价值）

## 关键玩家动态

（用表格简洁展示各主要实体的最新动态和你的解读）

## 风险与机会

（基于当前趋势，哪些方向值得关注，哪些信号值得警惕）

## 本期观点

（2-3 句话总结你对这个领域当前状态的判断）

## 参考来源
- [文章标题](url) - 来源, 日期"""


def build_user_prompt(
    topic_name: str,
    articles: list,
    recent_memory: list | None = None,
    long_term_memory: list | None = None,
) -> str:
    """构造 User Prompt"""
    from datetime import datetime

    # 文章列表 - 提供更多正文内容
    articles_text = ""
    for i, a in enumerate(articles[:10], 1):
        text = truncate(a.get("full_text", "") or a.get("summary", ""), 800)
        articles_text += f"### {i}. {a['title']}\n"
        articles_text += f"- 来源: {a.get('source', '未知')}\n"
        articles_text += f"- 时间: {a.get('published_at', '未知')}\n"
        articles_text += f"- 链接: {a['url']}\n"
        articles_text += f"- 正文: {text}\n\n"

    # 记忆部分
    memory_section = ""
    if recent_memory:
        memory_section += "## 近期记忆（L2，最近 7 天）\n\n"
        for r in recent_memory:
            memory_section += f"- {r['date']}: {r.get('summary', '')}\n"
            memory_section += f"  情感: {r.get('sentiment', 'N/A')} | 实体: {', '.join(r.get('top_entities', []))}\n"
        memory_section += "\n请分析本次新闻与近期热点的延续和变化。\n\n"

    if long_term_memory:
        memory_section += "## 长期趋势（L3）\n\n"
        for lt in long_term_memory:
            memory_section += f"- {lt['week_start']} 周: {lt.get('article_count', 0)} 篇, 平均情感: {lt.get('avg_sentiment', 'N/A')}\n"
            memory_section += f"  实体: {', '.join(lt.get('top_entities', []))}\n"
        memory_section += "\n请分析情感走向和实体变化趋势。\n\n"

    if not memory_section:
        memory_section = "## 历史记忆\n\n首次分析，暂无历史记忆数据。这是第一篇报道，后续会自动对比历史趋势。\n\n"

    return USER_PROMPT_TEMPLATE.format(
        topic_name=topic_name,
        article_count=len(articles),
        articles_text=articles_text,
        memory_section=memory_section,
        date=datetime.now().strftime("%Y-%m-%d"),
    )


def build_memory_prompt(topic_name: str, articles: list) -> str:
    """构造用于提取记忆的 Prompt"""
    articles_text = ""
    for a in articles[:10]:
        articles_text += f"- {a['title']}: {truncate(a.get('summary', ''), 200)}\n"

    return f"""分析以下 "{topic_name}" 主题的新闻，返回 JSON 格式：

{articles_text}

返回格式（仅返回 JSON，不要其他内容）：
{{
  "summary": "一段 200 字以内的总结",
  "sentiment": 0.0到1.0之间的情感分数（0=极度负面，1=极度正面）,
  "top_entities": ["实体1", "实体2", "实体3"]
}}"""
