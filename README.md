# NewsWeaver - 可定制 AI 资讯 Agent

> 自动采集、分析、生成新闻报道的 CLI 工具。基于 RSS 订阅源采集新闻，使用 LLM 生成自媒体风格的深度报道，支持三层记忆机制追踪行业趋势。

---

## 快速开始

```bash
# 1. 安装
pip install -e .

# 2. 配置 LLM（创建 .env 文件，填入你的 API Key）
#    Windows:
echo NEWSWEAVER_LLM_API_KEY=sk-xxx > .env
echo NEWSWEAVER_LLM_BASE_URL=https://api.deepseek.com/v1 >> .env
echo NEWSWEAVER_LLM_MODEL=deepseek-chat >> .env
#    macOS/Linux:
#    cat > .env << 'EOF'
#    NEWSWEAVER_LLM_API_KEY=sk-xxx
#    NEWSWEAVER_LLM_BASE_URL=https://api.deepseek.com/v1
#    NEWSWEAVER_LLM_MODEL=deepseek-chat
#    EOF

# 3. 启动交互式模式
newsweaver interactive
```

或者直接用命令：

```bash
newsweaver topic add --name "AI" --keywords "大模型,GPT,LLM"
newsweaver generate --topic "AI"
```

生成的报道在 `output/AI_<日期>.md`。

---

## 目录

- [特性](#特性)
- [架构概览](#架构概览)
- [安装](#安装)
- [配置](#配置)
- [使用](#使用)
- [核心模块](#核心模块)
- [三层记忆机制](#三层记忆机制)
- [数据源](#数据源)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [文件存储](#文件存储)
- [开发](#开发)

---

## 特性

| 特性 | 说明 |
|------|------|
| **RSS 优先** | 预置 36氪、虎嗅、IT之家、少数派、InfoQ、爱范儿等中文科技媒体 RSS 源，中国大陆直接可用 |
| **LLM 兼容** | 支持 OpenAI / DeepSeek / Qwen 等 OpenAI 兼容 API，`base_url` 可配置 |
| **三层记忆** | L1 瞬时(内存) / L2 近期(7天) / L3 长期(90天) 记忆机制，自动对比历史趋势 |
| **自媒体风格** | 内置 `skill.md` 写作指南，生成有深度、有观点的完整报道，不是简单摘要 |
| **零基础设施** | 纯 JSON 文件存储，无需数据库，开箱即用 |
| **交互式 CLI** | 支持菜单式交互操作，无需记忆命令参数 |
| **跨平台** | Windows / macOS / Linux 完整支持 |

---

## 架构概览

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI (click)                            │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐   │
│  │  topic   │  config  │  fetch   │ generate │ publish  │   │
│  │  add/list│  set/show│  search  │  LLM gen │  social  │   │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┘   │
│       │          │          │          │          │          │
└───────┼──────────┼──────────┼──────────┼──────────┼──────────┘
        │          │          │          │          │
        ▼          ▼          ▼          ▼          ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │  Topic  │ │ Config  │ │Fetcher  │ │   LLM   │ │Publisher│
   │ Manager │ │ Manager │ │  Layer  │ │ Client  │ │ (Mock)  │
   └─────────┘ └─────────┘ └────┬────┘ └────┬────┘ └─────────┘
                                │            │
                    ┌───────────┼────────────┼───────────┐
                    │           │            │           │
                    ▼           ▼            ▼           ▼
              ┌──────────┐ ┌────────┐ ┌──────────┐ ┌─────────┐
              │ RSS Feed │ │ Bing   │ │ Memory   │ │ Output  │
              │ Parser   │ │ News   │ │ Store    │ │ (.md)   │
              └──────────┘ └────────┘ └──────────┘ └─────────┘
```

### 核心流程

```
用户配置主题
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   采集新闻   │────▶│   读取记忆   │────▶│  构造 Prompt │
│  (RSS/Bing) │     │  (L2 + L3)  │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                                                ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  输出报道   │◀────│  LLM 生成   │◀────│  加载 skill  │
│  (.md文件)  │     │             │     │  写作指南    │
└──────┬──────┘     └─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐
│  更新记忆   │
│  (L2 → L3)  │
└─────────────┘
```

---

## 安装

### 环境要求

- Python >= 3.10
- pip

### 安装步骤

```bash
# 克隆项目
git clone <repo-url>
cd newsweaver

# 安装（开发模式）
pip install -e .

# 验证安装
newsweaver --version
# 输出: newsweaver, version 1.0.0
```

### 依赖说明

| 依赖 | 版本 | 用途 |
|------|------|------|
| `click` | >= 8.0 | CLI 框架，支持命令组、参数验证 |
| `requests` | >= 2.28 | HTTP 请求，RSS/Bing API 调用 |
| `feedparser` | >= 6.0 | RSS/Atom 源解析 |
| `beautifulsoup4` | >= 4.12 | HTML 解析与正文提取 |
| `lxml` | >= 4.9 | HTML/XML 解析引擎 |
| `readability-lxml` | >= 0.8 | 基于 Mozilla Readability 的正文提取 |
| `openai` | >= 1.0 | OpenAI 兼容 API 调用 |

---

## 配置

### 方式一：.env 文件（推荐）

复制 `.env.example` 为 `.env`，填入你的配置：

```bash
cp .env.example .env
```

```env
# LLM 配置（必填）
NEWSWEAVER_LLM_API_KEY=sk-your-api-key-here
NEWSWEAVER_LLM_BASE_URL=https://api.openai.com/v1
NEWSWEAVER_LLM_MODEL=gpt-4o-mini

# 可选：Bing News Search API
# NEWSWEAVER_BING_API_KEY=your-bing-api-key
```

### 方式二：CLI 命令

```bash
newsweaver config set --key llm.api_key --value sk-xxx
newsweaver config set --key llm.base_url --value https://api.deepseek.com/v1
newsweaver config set --key llm.model --value deepseek-chat
```

### 配置优先级

```
环境变量 (.env) > 配置文件 (~/.newsweaver/config.json) > 默认值
```

### 支持的 LLM 服务

| 服务 | base_url | 推荐 model | 说明 |
|------|----------|------------|------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | 官方 API |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | 国内推荐，性价比高 |
| Qwen (通义千问) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` | 阿里云服务 |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | 月之暗面 |
| GLM (智谱) | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | 智谱 AI |

### 环境变量列表

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `NEWSWEAVER_LLM_API_KEY` | LLM API 密钥 | 是 |
| `NEWSWEAVER_LLM_BASE_URL` | API 端点地址 | 否 |
| `NEWSWEAVER_LLM_MODEL` | 默认模型 | 否 |
| `NEWSWEAVER_BING_API_KEY` | Bing News API 密钥 | 否 |

---

## 使用

### 交互式模式（推荐新手）

```bash
newsweaver interactive
```

```
==================================================
  NewsWeaver 交互式模式
==================================================

--------------------------------------------------
请选择操作：
  1. 查看已有主题
  2. 添加新主题
  3. 删除主题
  4. 采集新闻（fetch）
  5. 生成报道（generate）
  6. 查看记忆
  7. 压缩记忆
  8. 发布报道
  0. 退出
```

### 命令行模式

#### 主题管理

```bash
# 添加主题
newsweaver topic add --name "AI" --keywords "大模型,GPT,LLM" --lang zh

# 添加主题（带排除词）
newsweaver topic add --name "芯片" --keywords "NVIDIA,AMD,芯片" --exclude "游戏,显卡"

# 查看主题
newsweaver topic list

# 删除主题（含关联记忆）
newsweaver topic remove --name "AI"
```

#### 新闻采集

```bash
# 采集新闻（调试用，保存原始数据）
newsweaver fetch --topic "AI" --limit 5 --days 3

# 输出示例：
# >>> 正在搜索 "AI" 相关新闻...
# >>> RSS: 找到 5 篇
# >>> 正文提取: 共 5 篇
# >>> 已保存至 output/raw/AI_20260608_103000.json
```

#### 生成报道

```bash
# 使用默认模型生成
newsweaver generate --topic "AI"

# 指定模型生成
newsweaver generate --topic "AI" --model deepseek-chat --limit 10

# 输出示例：
# >>> 正在搜索 "AI" 相关新闻...
# >>> 找到 8 篇文章
# >>> 正文提取: 共 8 篇
# >>> 读取记忆...
# >>> L2 (2 条记录)，L3 (3 周数据)
# >>> 调用 LLM (deepseek-chat) 生成报道...
# >>> 报道生成完成
# >>> 报道已保存至 output/AI_2026-06-08.md
```

#### 记忆管理

```bash
# 查看记忆
newsweaver memory show --topic "AI"
#   [L2 近期记忆] 2 条记录
#     2026-06-07 | 情感: 0.85 | 实体: NVIDIA, AMD
#     2026-06-06 | 情感: 0.72 | 实体: Intel, TSMC
#   [L3 长期趋势] 3 周
#     2026-06-01 | 12 篇 | 均情感: 0.72 | 实体: NVIDIA, AMD, Intel

# 手动压缩记忆（L2 → L3）
newsweaver memory compact --topic "AI"
```

#### 发布

```bash
# 模拟发布到社交平台
newsweaver publish --topic "AI" --platform twitter
newsweaver publish --topic "AI" --platform linkedin
newsweaver publish --topic "AI" --platform mastodon
```

#### 全局参数

| 参数 | 缩写 | 说明 |
|------|------|------|
| `--verbose` | `-v` | 开启 DEBUG 日志输出 |
| `--config` | `-c` | 指定配置文件路径 |
| `--help` | `-h` | 显示帮助信息 |
| `--version` | - | 显示版本号 |

---

## 核心模块

### 模块依赖关系

```
cli.py ─────────────────────────────────────────────────┐
  │                                                     │
  ├── topic.py (主题管理)                               │
  │     └── config.py                                   │
  │                                                     │
  ├── commands.py (命令定义) ────────────────────────────┤
  │     ├── config.py (配置读写)                        │
  │     ├── fetcher/rss.py (RSS 采集)                   │
  │     ├── fetcher/bing.py (Bing 采集)                 │
  │     ├── extractor.py (正文提取)                     │
  │     ├── generator.py (生成编排) ─────────────────────┤
  │     │     ├── llm/client.py (LLM 调用)              │
  │     │     ├── llm/prompts.py (Prompt 模板)          │
  │     │     └── memory/store.py (记忆读写)            │
  │     ├── memory/compact.py (记忆压缩)                │
  │     └── publisher.py (发布接口)                     │
  │                                                     │
  └── utils.py (工具函数)                               │
```

### 关键模块说明

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI 入口 | `cli.py` | click 命令组注册，Windows UTF-8 支持 |
| 配置管理 | `config.py` | 读写 `~/.newsweaver/config.json`，支持 `.env` 环境变量覆盖 |
| 主题管理 | `topic.py` | `topic add/list/remove` 命令实现 |
| 命令定义 | `commands.py` | `config/fetch/generate/memory/publish/interactive` 命令实现 |
| RSS 适配器 | `fetcher/rss.py` | 使用 feedparser 解析 RSS 源，支持预置源和自定义源 |
| Bing 适配器 | `fetcher/bing.py` | Bing News Search API 调用（可选） |
| 正文提取 | `extractor.py` | readability-lxml + BeautifulSoup 双引擎提取 |
| LLM 客户端 | `llm/client.py` | OpenAI SDK 封装，含自动重试（最多 2 次，间隔 3s） |
| Prompt 模板 | `llm/prompts.py` | 加载 `skill.md` 写作指南，构造 System/User Prompt |
| 生成编排 | `generator.py` | 完整流程：fetch → 记忆 → LLM → 输出 → 更新记忆 |
| 记忆存储 | `memory/store.py` | L2/L3 JSON 读写，原子写入，自动清理过期数据 |
| 记忆压缩 | `memory/compact.py` | L2 → L3 按周聚合，统计高频实体和平均情感 |
| 发布接口 | `publisher.py` | 预留接口，当前为模拟实现 |
| 工具函数 | `utils.py` | 文件锁、日志配置、原子写入、文本截断 |

---

## 三层记忆机制

### 记忆层级

```
┌─────────────────────────────────────────────────────────┐
│                    L1 瞬时工作记忆                        │
│              (内存变量，单次运行即销毁)                    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                 L2 近期情景记忆                           │
│         ~/.newsweaver/memory/<topic>.json                │
│              recent[] - 7 天滚动窗口                      │
│                    最多 30 条记录                          │
└─────────────────────────────────────────────────────────┘
                            │
                     memory compact
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                 L3 长期趋势记忆                           │
│         ~/.newsweaver/memory/<topic>.json                │
│             long_term[] - 90 天按周聚合                    │
│                    最多 52 周记录                          │
└─────────────────────────────────────────────────────────┘
```

### L2 数据结构

```json
{
  "date": "2026-06-07",
  "summary": "OpenAI 发布 GPT-5，多模态能力大幅提升，行业反响热烈。",
  "sentiment": 0.85,
  "top_entities": ["OpenAI", "GPT-5", "Sam Altman"]
}
```

### L3 数据结构

```json
{
  "week_start": "2026-06-01",
  "article_count": 12,
  "avg_sentiment": 0.72,
  "top_entities": ["OpenAI", "Google", "Anthropic"]
}
```

### 更新逻辑

| 触发时机 | 操作 |
|----------|------|
| 每次 `generate` 完成后 | LLM 提取摘要 + 情感分数 → 追加至 L2；清理 >7 天记录 |
| 手动 `memory compact` | L2 按周聚合 → 写入 L3；清除已压缩的 L2 条目 |
| L3 超出 52 周 | 自动淘汰最早一周 |

---

## 数据源

### 预置 RSS 源

| 源名称 | RSS 地址 | 类型 |
|--------|----------|------|
| 36氪 | `https://36kr.com/feed` | 科技商业 |
| 虎嗅 | `https://www.huxiu.com/rss/0.xml` | 科技商业 |
| IT之家 | `https://www.ithome.com/rss/` | 科技资讯 |
| 少数派 | `https://sspai.com/feed` | 效率工具 |
| InfoQ | `https://www.infoq.cn/feed` | 技术社区 |
| 爱范儿 | `https://www.ifanr.com/feed` | 消费科技 |

### 自定义 RSS 源

```bash
# 添加自定义 RSS 源
newsweaver topic add --name "自定义" --keywords "关键词" --sources "rss:https://example.com/rss"
```

### 信源优先级

```
1. 预置 RSS 源（默认启用）
2. 用户自定义 RSS 源
3. Bing News Search API（需配置 API Key）
```

---

## 项目结构

```
NewsWeaver/
├── pyproject.toml              # 项目元数据与依赖声明
├── .env.example                # 环境变量模板
├── .gitignore                  # Git 忽略规则
├── README.md                   # 项目文档
├── skill.md                    # LLM 新闻写作指南
│
├── src/
│   └── newsweaver/
│       ├── __init__.py         # 版本号
│       ├── cli.py              # CLI 入口（click 命令组）
│       ├── config.py           # 配置管理（读写 config.json + .env）
│       ├── topic.py            # 主题管理命令
│       ├── commands.py         # CLI 命令定义
│       ├── generator.py        # 新闻生成主流程编排
│       ├── extractor.py        # 正文提取（readability + BS4）
│       ├── publisher.py        # 社交媒体发布接口（预留）
│       ├── utils.py            # 工具函数（文件锁、日志、原子写入）
│       │
│       ├── fetcher/
│       │   ├── __init__.py
│       │   ├── base.py         # 信源抽象基类 + Article dataclass
│       │   ├── rss.py          # RSS 适配器（feedparser）
│       │   └── bing.py         # Bing News Search 适配器
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py       # OpenAI API 封装（含重试）
│       │   └── prompts.py      # Prompt 模板（加载 skill.md）
│       │
│       └── memory/
│           ├── __init__.py
│           ├── store.py        # 记忆存储引擎（L2/L3 JSON）
│           └── compact.py      # 记忆压缩（L2 → L3 聚合）
│
├── output/                     # 生成的新闻报道
│   ├── <topic>_<date>.md       # 最终报道
│   └── raw/                    # 原始采集数据（调试用）
│       └── <topic>_<timestamp>.json
│
└── tests/                      # 测试文件
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 运行环境 | Python >= 3.10 | 使用 `match/case` 等新语法 |
| CLI 框架 | click >= 8.0 | 命令组、参数验证、自动补全 |
| HTTP 请求 | requests >= 2.28 | RSS/API 调用，15s 超时 |
| RSS 解析 | feedparser >= 6.0 | RSS/Atom 源解析 |
| 正文提取 | readability-lxml + BeautifulSoup4 | 双引擎，readability 优先，BS4 兜底 |
| LLM 调用 | openai SDK >= 1.0 | OpenAI 兼容范式，base_url 可配置 |
| 存储 | JSON 文件 | 原子写入（write → rename），无外部依赖 |
| 配置 | JSON + .env | 环境变量优先级高于配置文件 |

---

## 文件存储

### 配置文件

**路径**: `~/.newsweaver/config.json`

```json
{
  "config_version": 1,
  "llm": {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini"
  },
  "search": {
    "bing_api_key": "",
    "default_limit": 10,
    "days_back": 1
  },
  "topics": [
    {
      "name": "AI",
      "keywords": ["大模型", "GPT", "LLM"],
      "exclude_words": [],
      "sources": [],
      "language": "zh"
    }
  ]
}
```

### 记忆文件

**路径**: `~/.newsweaver/memory/<topic>.json`

```json
{
  "topic": "AI",
  "created_at": "2026-06-01T00:00:00Z",
  "updated_at": "2026-06-08T12:00:00Z",
  "recent": [...],
  "long_term": [...]
}
```

### 输出文件

- **报道**: `output/<topic>_<YYYY-MM-DD>.md`
- **原始数据**: `output/raw/<topic>_<timestamp>.json`

---

## 开发

### 本地开发

```bash
# 安装开发依赖
pip install -e .

# 运行
newsweaver --help

# 查看日志
newsweaver -v fetch --topic "AI"
```

### 新增信源

1. 在 `src/newsweaver/fetcher/` 下创建新适配器
2. 继承 `BaseFetcher`，实现 `fetch()` 方法
3. 在 `commands.py` 的 `fetch_cmd` 中注册

### 自定义 Prompt

编辑 `skill.md` 文件即可自定义 LLM 的写作风格和输出格式，无需修改代码。
