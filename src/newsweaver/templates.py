"""Built-in subscription topic templates."""

from __future__ import annotations


TOPIC_TEMPLATES = {
    "ai": {
        "name": "AI 大模型",
        "keywords": ["大模型", "GPT", "OpenAI", "DeepSeek", "Qwen", "LLM"],
        "exclude_words": ["教程", "招聘"],
        "sources": [],
        "language": "zh",
        "description": "模型发布、价格、产品和行业变化",
    },
    "chip": {
        "name": "芯片半导体",
        "keywords": ["NVIDIA", "AMD", "芯片", "半导体", "AI 加速器"],
        "exclude_words": ["游戏", "显卡评测"],
        "sources": [],
        "language": "zh",
        "description": "算力、供应链、厂商动向",
    },
    "ev": {
        "name": "新能源车",
        "keywords": ["新能源车", "比亚迪", "特斯拉", "小鹏", "理想", "蔚来"],
        "exclude_words": ["二手车", "车主论坛"],
        "sources": [],
        "language": "zh",
        "description": "车企新品、销量和产业链",
    },
    "global": {
        "name": "出海公司",
        "keywords": ["出海", "跨境", "TikTok", "SHEIN", "Temu", "全球化"],
        "exclude_words": ["代运营", "培训"],
        "sources": [],
        "language": "zh",
        "description": "中国公司全球化和商业机会",
    },
    "fintech": {
        "name": "金融科技",
        "keywords": ["金融科技", "支付", "稳定币", "跨境支付", "数字银行", "风控"],
        "exclude_words": ["贷款广告", "培训"],
        "sources": [],
        "language": "zh",
        "description": "支付、跨境结算、数字金融和监管变化",
    },
}


def get_topic_template(template_id: str) -> dict:
    if template_id not in TOPIC_TEMPLATES:
        raise KeyError(template_id)
    return dict(TOPIC_TEMPLATES[template_id])


def list_topic_templates() -> list[dict]:
    return [{"id": key, **value} for key, value in TOPIC_TEMPLATES.items()]
