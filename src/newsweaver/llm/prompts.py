"""Prompt templates for evidence-constrained generation and repair."""

import json
import re
from collections import defaultdict
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

证据纪律是最高优先级：
- 报告中的可验证事实只能来自“事实证据包”，文章列表只用于来源目录
- 每个关键事实必须紧跟一个或多个准确的 `[Fxxx]`
- 数字、日期、金额、比例、人物表态、直接归因必须逐项引用
- 一个 `[Fxxx]` 只能支持该 fact 的 claim/source_span 实际包含的内容
- 分析和预测必须明确写成分析，不得伪装成已发生事实
- 如果证据不足，明确说明“现有证据不足”，不要补全常识或外部知识

{SKILL_CONTENT}"""

USER_PROMPT_TEMPLATE = """请根据以下素材，写一篇完整的自媒体风格新闻报道。

## 主题：{topic_name}

## 本次采集的新闻素材（{article_count} 篇）

{articles_text}

{evidence_section}

{memory_section}

## 写作要求

1. **不是摘要，是报道**：不要逐条罗列新闻，要串联、分析、下判断
2. **有深度分析**：解释"为什么"和"意味着什么"，不只是"发生了什么"
3. **有观点**：基于事实给出你的洞察和预判
4. **有导语**：用一句话抓住读者注意力
5. **有节奏**：段落不要太长，重要观点加粗强调
6. **有来源**：每个关键事实后必须使用 `[F001]` 这样的证据编号，编号必须来自事实证据包
7. **受证据约束**：只能使用事实证据包中的事实；所有数字、日期、金额、比例、人物引语和直接归因必须紧跟证据编号
8. **精确引用**：引用必须支持它紧邻的具体 claim；不得用一条只包含 A 的 fact 同时支撑 A+B

请严格按照以下结构输出：

# {topic_name} 资讯报道 – {date}

> 一句话导语（用最有冲击力的事实或观点抓住读者）

## 核心事件

（不要逐条罗列，每个事件要讲清楚：发生了什么 → 为什么重要 → 对行业意味着什么）

## 深度分析

（串联线索、发现趋势、预判未来。这是文章的核心价值）

## 本期和过去相比变化了什么

（必须结合历史趋势记忆：哪些玩家延续热度，哪些信号新出现，哪些判断需要修正）

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
    fact_pack: dict | None = None,
    quality_report: dict | None = None,
    trend_memory: str | None = None,
    preferences: dict | None = None,
) -> str:
    """构造 User Prompt"""
    from datetime import datetime

    # Article metadata is a bibliography. Factual content comes from the Fact Pack.
    articles_text = ""
    for i, a in enumerate(articles[:10], 1):
        articles_text += f"### {i}. {a['title']}\n"
        articles_text += f"- 来源: {a.get('source', '未知')}\n"
        articles_text += f"- 时间: {a.get('published_at', '未知')}\n"
        articles_text += f"- 链接: {a['url']}\n"
        articles_text += "- 说明: 仅用于来源目录；正文事实必须从下方事实证据包引用。\n\n"

    evidence_section = ""
    if fact_pack:
        evidence_section += "## 事实证据包\n\n"
        evidence_section += (
            f"- 文章数: {fact_pack.get('article_count', 0)}\n"
            f"- 来源数: {fact_pack.get('source_count', 0)}\n"
        )
        if quality_report:
            evidence_section += f"- 质量评分: {quality_report.get('score', 0)}/100\n"
            warnings = quality_report.get("warnings", [])
            if warnings:
                evidence_section += "- 风险提示: " + "；".join(warnings) + "\n"
        selected_facts = select_facts_for_prompt(fact_pack.get("facts", []))
        evidence_section += (
            f"\n以下是报告唯一允许使用的可验证事实（按 token 预算选入 {len(selected_facts)}/"
            f"{len(fact_pack.get('facts', []))} 条，优先保留高风险信息和事件多样性）：\n"
        )
        for fact in selected_facts:
            fact_id = fact.get("fact_id") or fact.get("id")
            evidence_section += (
                f"- [{fact_id}] {fact.get('claim')} "
                f"| 原文证据: {fact.get('source_span', fact.get('claim', ''))} "
                f"| 事件: {fact.get('event_id', '')} "
                f"| 来源: {fact.get('source_title')} ({fact.get('url')})\n"
            )
        evidence_section += "\n"

    # 记忆部分
    memory_section = ""
    if trend_memory:
        memory_section += trend_memory.strip() + "\n\n"

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

    preferences = preferences or {}
    preference_text = (
        f"\n## 用户偏好\n\n- 目标受众：{preferences.get('audience', '行业关注者')}"
        f"\n- 写作风格：{preferences.get('style', '深度分析')}"
        f"\n- 篇幅：{preferences.get('length', '中等')}\n"
    )
    return USER_PROMPT_TEMPLATE.format(
        topic_name=topic_name,
        article_count=len(articles),
        articles_text=articles_text,
        evidence_section=evidence_section,
        memory_section=memory_section + preference_text,
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


def select_facts_for_prompt(facts: list[dict], max_chars: int = 24000) -> list[dict]:
    """Select complete evidence spans under a prompt budget without head truncation."""
    by_event = defaultdict(list)
    for index, fact in enumerate(facts):
        event_id = fact.get("event_id") or f"ungrouped-{index}"
        evidence = f"{fact.get('claim', '')} {fact.get('source_span', '')}"
        risk = 3 if re.search(r"[%％$¥€£]|美元|欧元|英镑|亿元|million|billion|trillion", evidence, re.I) else (
            2 if re.search(r"\d{4}[-/年]|表示|宣布|称|said|announced", evidence, re.I) else (
                1 if re.search(r"\d", evidence) else 0
            )
        )
        by_event[event_id].append((risk, float(fact.get("confidence", 0.0) or 0.0), -index, fact))
    queues = [
        [item[3] for item in sorted(items, key=lambda item: (item[0], item[1], item[2]), reverse=True)]
        for _event, items in sorted(by_event.items())
    ]
    selected = []
    used = 0
    while any(queues):
        made_progress = False
        for queue in queues:
            if not queue:
                continue
            fact = queue.pop(0)
            size = len(fact.get("claim", "")) + len(fact.get("source_span", "")) + 180
            if used + size <= max_chars or not selected:
                selected.append(fact)
                used += size
                made_progress = True
        if not made_progress:
            break
    return selected


REPAIR_SYSTEM_PROMPT = """你是 NewsWeaver 的引用修复编辑。只修复给定 Markdown 报告，不添加新事实。
你的唯一事实来源是 Fact Pack。删除无法支持的陈述，为可支持的关键事实添加准确 `[Fxxx]`，并确保数字、日期、金额、比例和直接归因逐项有证据。保留原有文章结构，只输出修复后的完整 Markdown。"""


def build_repair_prompt(report: str, fact_pack: dict, audit: dict) -> str:
    """Build a focused repair request from structured audit failures."""
    compact_facts = [
        {
            "fact_id": fact.get("fact_id") or fact.get("id"),
            "claim": fact.get("claim", ""),
            "source_span": fact.get("source_span", fact.get("claim", "")),
            "source": fact.get("source", ""),
            "url": fact.get("url", ""),
        }
        for fact in fact_pack.get("facts", [])
    ]
    return (
        "请根据审计失败原因修复报告。不得保留 Fact Pack 外事实，也不得让引用支撑其未包含的 claim。\n\n"
        f"## 审计失败原因\n{json.dumps(audit.get('failure_reasons', []), ensure_ascii=False, indent=2)}\n\n"
        f"## Fact Pack\n{json.dumps(compact_facts, ensure_ascii=False, indent=2)}\n\n"
        f"## 待修复报告\n{report}"
    )
