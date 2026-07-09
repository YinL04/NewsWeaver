"""Local web workbench with evidence preview, async generation, and editing."""

from __future__ import annotations

import json
import importlib.util
import mimetypes
import re
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import find_topic, load_config, save_config
from .memory.trends import build_trend_cards
from .pipeline import article_to_dict, audit_report, build_fact_pack, build_quality_report, prepare_articles
from .utils import atomic_write_json, get_log_file, get_memory_dir, get_output_dir, log_exception, read_json


WEB_ROOT = Path(__file__).parent / "web"
PREVIEWS: dict[str, dict] = {}
JOBS: dict[str, dict] = {}
STATE_LOCK = threading.Lock()


class NewsWeaverHandler(BaseHTTPRequestHandler):
    server_version = "NewsWeaverWeb/1.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/api/state": lambda: self._json(self._state()),
            "/api/health": lambda: self._json(build_health_report()),
            "/api/report": lambda: self._get_report(parse_qs(parsed.query)),
            "/api/job": lambda: self._get_job(parse_qs(parsed.query)),
            "/api/trend": lambda: self._get_trend(parse_qs(parsed.query)),
        }
        if parsed.path == "/":
            return self._serve_static("index.html")
        if parsed.path.startswith("/static/"):
            return self._serve_static(parsed.path.removeprefix("/static/"))
        if parsed.path in routes:
            return routes[parsed.path]()
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_json()
            routes = {
                "/api/config": self._save_config,
                "/api/topics": self._add_topic,
                "/api/topics/update": self._update_topic,
                "/api/topics/delete": self._delete_topic,
                "/api/preview": self._preview,
                "/api/generate": self._generate,
                "/api/report/save": self._save_report,
                "/api/report/rewrite": self._rewrite_report,
                "/api/report/restore": self._restore_report,
            }
            handler = routes.get(parsed.path)
            if not handler:
                return self.send_error(404)
            handler(body)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
        except Exception as exc:
            log_exception(f"{self.command} {self.path}", exc)
            self._json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relative: str) -> None:
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents or not target.is_file():
            return self.send_error(404)
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _state(self) -> dict:
        config = load_config()
        reports = []
        for path in sorted(get_output_dir().glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.endswith((".wechat.md", ".email.md")):
                continue
            reports.append({"name": path.name, "modified": path.stat().st_mtime})
        return {
            "config": {
                "llm": {
                    "base_url": config.get("llm", {}).get("base_url", ""),
                    "model": config.get("llm", {}).get("model", ""),
                    "has_api_key": bool(config.get("llm", {}).get("api_key", "")),
                },
                "search": config.get("search", {}),
            },
            "topics": config.get("topics", []),
            "reports": reports[:30],
        }

    def _save_config(self, body: dict) -> None:
        config = load_config()
        llm, search = config.setdefault("llm", {}), config.setdefault("search", {})
        for key in ("api_key", "base_url", "model"):
            if body.get(key) not in (None, ""):
                llm[key] = body[key]
        for key in ("default_limit", "days_back"):
            if body.get(key) not in (None, ""):
                search[key] = int(body[key])
        save_config(config)
        self._json({"ok": True, "state": self._state()})

    def _topic_from_body(self, body: dict) -> dict:
        return {
            "name": (body.get("name") or "").strip(),
            "keywords": split_csv(body.get("keywords", "")),
            "exclude_words": split_csv(body.get("exclude_words", "")),
            "required_words": split_csv(body.get("required_words", "")),
            "sources": split_sources(body.get("sources", "")),
            "language": body.get("language") or "zh",
            "preferences": {
                "audience": (body.get("audience") or "行业关注者").strip(),
                "style": (body.get("style") or "深度分析").strip(),
                "length": (body.get("length") or "中等").strip(),
            },
        }

    def _add_topic(self, body: dict) -> None:
        config, topic = load_config(), self._topic_from_body(body)
        if not topic["name"] or not topic["keywords"]:
            raise ValueError("主题名称和关键词不能为空")
        if find_topic(config, topic["name"]):
            raise ValueError("主题已存在")
        config.setdefault("topics", []).append(topic)
        save_config(config)
        self._json({"ok": True, "topic": topic, "state": self._state()})

    def _update_topic(self, body: dict) -> None:
        config = load_config()
        original = (body.get("original_name") or body.get("name") or "").strip()
        existing = find_topic(config, original)
        if not existing:
            raise ValueError("主题不存在")
        updated = self._topic_from_body(body)
        if not updated["name"] or not updated["keywords"]:
            raise ValueError("主题名称和关键词不能为空")
        duplicate = find_topic(config, updated["name"])
        if duplicate is not None and duplicate is not existing:
            raise ValueError("新主题名称已存在")
        existing.clear()
        existing.update(updated)
        save_config(config)
        old_memory = get_memory_dir() / f"{original}.json"
        new_memory = get_memory_dir() / f"{updated['name']}.json"
        if original != updated["name"] and old_memory.exists() and not new_memory.exists():
            old_memory.rename(new_memory)
        self._json({"ok": True, "topic": updated, "state": self._state()})

    def _delete_topic(self, body: dict) -> None:
        config = load_config()
        name = (body.get("name") or "").strip()
        before = len(config.get("topics", []))
        config["topics"] = [topic for topic in config.get("topics", []) if topic.get("name") != name]
        if len(config["topics"]) == before:
            raise ValueError("主题不存在")
        save_config(config)
        memory_file = get_memory_dir() / f"{name}.json"
        if memory_file.exists():
            memory_file.unlink()
        self._json({"ok": True, "state": self._state()})

    def _preview(self, body: dict) -> None:
        config = load_config()
        topic_name = body.get("topic")
        topic = find_topic(config, topic_name)
        if not topic:
            raise ValueError("主题不存在")
        limit = int(body.get("limit") or config.get("search", {}).get("default_limit", 10))
        articles = prepare_articles(config, topic, limit)
        facts = build_fact_pack(topic_name, articles)
        quality = enrich_quality_report(build_quality_report(topic_name, articles, facts))
        preview_id = uuid.uuid4().hex
        with STATE_LOCK:
            PREVIEWS[preview_id] = {"topic": topic_name, "created": time.time(), "articles": articles}
            _prune_state()
        self._json({
            "preview_id": preview_id,
            "quality": quality,
            "facts": facts,
            "articles": [article_to_dict(a, topic.get("keywords", [])) for a in articles],
        })

    def _generate(self, body: dict) -> None:
        config = load_config()
        topic_name, preview_id = body.get("topic"), body.get("preview_id")
        topic = find_topic(config, topic_name)
        preview = PREVIEWS.get(preview_id or "")
        if not topic or not preview or preview.get("topic") != topic_name:
            raise ValueError("素材预览已失效，请重新体检")
        facts = build_fact_pack(topic_name, preview["articles"])
        quality = enrich_quality_report(build_quality_report(topic_name, preview["articles"], facts))
        force = bool(body.get("force"))
        if not quality.get("ready") and not force:
            return self._json({"error": "素材未达到生成门槛", "quality": quality, "requires_confirmation": True}, 409)
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"id": job_id, "status": "queued", "stage": "queued", "percent": 0, "message": "等待开始"}
        thread = threading.Thread(
            target=_run_generation_job,
            args=(job_id, config, dict(topic), body.get("model") or config.get("llm", {}).get("model"), preview["articles"], force),
            daemon=True,
        )
        thread.start()
        self._json({"ok": True, "job_id": job_id}, 202)

    def _get_job(self, query: dict) -> None:
        job = JOBS.get((query.get("id") or [""])[0])
        if not job:
            return self._json({"error": "任务不存在或已过期"}, 404)
        self._json(job)

    def _get_trend(self, query: dict) -> None:
        topic = (query.get("topic") or [""])[0]
        if not topic:
            raise ValueError("缺少主题")
        self._json(build_trend_cards(topic))

    def _report_target(self, name: str) -> Path:
        target = (get_output_dir() / name).resolve()
        root = get_output_dir().resolve()
        if root not in target.parents or target.suffix != ".md" or not target.exists():
            raise ValueError("报告不存在")
        return target

    def _get_report(self, query: dict) -> None:
        target = self._report_target((query.get("name") or [""])[0])
        facts = read_json(target.with_suffix(".facts.json"))
        self._json({
            "name": target.name,
            "content": target.read_text(encoding="utf-8"),
            "facts": facts,
            "quality": read_json(target.with_suffix(".quality.json")),
            "audit": read_json(target.with_suffix(".audit.json")),
            "versions": _report_versions(target),
        })

    def _save_report(self, body: dict) -> None:
        target = self._report_target(body.get("name", ""))
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("报告内容不能为空")
        _snapshot_report(target)
        target.write_text(content, encoding="utf-8")
        audit = audit_report(content, read_json(target.with_suffix(".facts.json")))
        atomic_write_json(target.with_suffix(".audit.json"), audit)
        self._json({"ok": True, "audit": audit, "versions": _report_versions(target)})

    def _rewrite_report(self, body: dict) -> None:
        from .llm.client import LLMClient
        target = self._report_target(body.get("name", ""))
        heading, instruction = (body.get("heading") or "").strip(), (body.get("instruction") or "").strip()
        if not heading or not instruction:
            raise ValueError("请选择章节并填写改写要求")
        content = target.read_text(encoding="utf-8")
        section = _extract_section(content, heading)
        if not section:
            raise ValueError("未找到该章节")
        config = load_config()
        facts = read_json(target.with_suffix(".facts.json"))
        prompt = (
            f"仅改写 Markdown 报告的“{heading}”章节。要求：{instruction}\n"
            "保留章节标题；所有数字和关键事实必须使用原有 [F001] 形式证据编号；不要创造新事实。\n\n"
            f"事实包：{json.dumps(facts.get('facts', []), ensure_ascii=False)}\n\n原章节：\n{section}"
        )
        rewritten = LLMClient(
            config.get("llm", {}).get("api_key", ""),
            config.get("llm", {}).get("base_url", "https://api.openai.com/v1"),
            config.get("llm", {}).get("model", "gpt-4o-mini"),
        ).generate("你是严谨的中文新闻编辑，只输出改写后的完整章节。", prompt)
        _snapshot_report(target)
        updated = content.replace(section, rewritten.strip(), 1)
        target.write_text(updated, encoding="utf-8")
        audit = audit_report(updated, facts)
        atomic_write_json(target.with_suffix(".audit.json"), audit)
        self._json({"ok": True, "content": updated, "audit": audit, "versions": _report_versions(target)})

    def _restore_report(self, body: dict) -> None:
        target = self._report_target(body.get("name", ""))
        version_name = Path(body.get("version", "")).name
        version_dir = (get_output_dir() / ".versions" / target.stem).resolve()
        version = (version_dir / version_name).resolve()
        if version_dir not in version.parents or not version.is_file() or version.suffix != ".md":
            raise ValueError("历史版本不存在")
        _snapshot_report(target)
        content = version.read_text(encoding="utf-8")
        target.write_text(content, encoding="utf-8")
        facts = read_json(target.with_suffix(".facts.json"))
        audit = audit_report(content, facts)
        atomic_write_json(target.with_suffix(".audit.json"), audit)
        self._json({"ok": True, "content": content, "audit": audit, "versions": _report_versions(target)})


def _run_generation_job(job_id: str, config: dict, topic: dict, model: str, articles: list, force: bool) -> None:
    from .generator import run_generate

    def progress(stage: str, percent: int, message: str) -> None:
        JOBS[job_id].update({"status": "running", "stage": stage, "percent": percent, "message": message})

    try:
        JOBS[job_id].update({"status": "running", "percent": 5, "message": "任务已启动"})
        path = run_generate(config, topic, model, len(articles), prepared_articles=articles, force=force, progress=progress)
        JOBS[job_id].update({"status": "complete", "stage": "complete", "percent": 100, "message": "报告已完成", "report": path.name})
    except Exception as exc:
        log_exception(f"generation job {job_id}", exc)
        JOBS[job_id].update({"status": "failed", "message": str(exc), "error": str(exc)})


def _prune_state() -> None:
    cutoff = time.time() - 3600
    for key in [key for key, value in PREVIEWS.items() if value.get("created", 0) < cutoff]:
        PREVIEWS.pop(key, None)


def _snapshot_report(target: Path) -> None:
    version_dir = get_output_dir() / ".versions" / target.stem
    version_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    (version_dir / f"{stamp}.md").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")


def _report_versions(target: Path) -> list[dict]:
    version_dir = get_output_dir() / ".versions" / target.stem
    if not version_dir.exists():
        return []
    return [{"name": p.name, "modified": p.stat().st_mtime} for p in sorted(version_dir.glob("*.md"), reverse=True)[:20]]


def build_health_report() -> dict:
    """Return Web-friendly diagnostics for first-run and real-chain validation."""
    config = load_config()
    checks = [
        _health_check("python", sys.version_info >= (3, 10), f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", "请使用 Python 3.10 或更高版本。"),
    ]
    missing = [package for package in ("click", "requests", "feedparser", "bs4", "lxml", "readability", "openai") if importlib.util.find_spec(package) is None]
    checks.append(_health_check("dependencies", not missing, "依赖完整" if not missing else "缺少 " + ", ".join(missing), "运行 pip install -e . 安装依赖。"))
    llm = config.get("llm", {})
    has_key = bool(llm.get("api_key")) and llm.get("api_key") != "sk-your-api-key-here"
    checks.append(_health_check("llm", has_key, llm.get("model", "未设置"), "填写 API Key 后才能真实生成报告。"))
    topics = config.get("topics", [])
    checks.append(_health_check("topics", bool(topics), f"{len(topics)} 个主题", "从模板创建一个主题。"))
    checks.append(_health_check("output", _output_dir_is_writable(), str(get_output_dir()), "检查 output 目录写入权限。"))
    custom_sources = sum(1 for topic in topics for source in topic.get("sources", []) if source.startswith("rss:"))
    checks.append(_health_check("sources", bool(topics), f"{custom_sources} 个自定义 RSS", "默认 RSS 可直接使用；也可为主题添加自定义 RSS。", optional=True))
    blocking = [check for check in checks if not check["ok"] and not check.get("optional")]
    return {
        "version": __version__,
        "ready": not blocking,
        "checks": checks,
        "log_file": str(get_log_file()),
        "next_action": _next_health_action(blocking, topics),
    }


def _health_check(name: str, ok: bool, detail: str, fix: str, optional: bool = False) -> dict:
    return {
        "name": name,
        "ok": ok,
        "level": "ok" if ok else ("warn" if optional else "error"),
        "detail": detail,
        "fix": "" if ok else fix,
        "optional": optional,
    }


def _output_dir_is_writable() -> bool:
    try:
        probe = get_output_dir() / ".health_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _next_health_action(blocking: list[dict], topics: list[dict]) -> str:
    if not blocking:
        return "环境已准备好，可以体检素材并生成报告。"
    first = blocking[0]
    if first["name"] == "llm":
        return "先保存 API Key，然后再生成第一篇报告。"
    if first["name"] == "topics" or not topics:
        return "从主题模板开始，创建一个关注方向。"
    return first.get("fix") or "按诊断提示修复后重试。"


def enrich_quality_report(quality: dict) -> dict:
    """Attach product-facing traffic-light status and actionable advice."""
    score = int(quality.get("score") or 0)
    blockers = quality.get("blockers") or []
    warnings = quality.get("warnings") or []
    if blockers:
        status = {
            "level": "red",
            "label": "红灯",
            "title": "素材不足，需要确认",
            "summary": "继续生成可能导致报告偏薄或来源单一。",
        }
    elif score < 80 or warnings:
        status = {
            "level": "yellow",
            "label": "黄灯",
            "title": "可生成，但建议复核",
            "summary": "素材基本够用，但仍有改进空间。",
        }
    else:
        status = {
            "level": "green",
            "label": "绿灯",
            "title": "素材健康，可直接生成",
            "summary": "文章数、来源和正文覆盖率已达到门槛。",
        }
    quality["status"] = status
    quality["advice"] = _quality_advice(quality)
    return quality


def _quality_advice(quality: dict) -> list[str]:
    advice = []
    if quality.get("article_count", 0) < 3:
        advice.append("放宽关键词或增加采集数量，至少拿到 3 篇相关文章。")
    if quality.get("source_count", 0) < 2:
        advice.append("增加自定义 RSS 或启用 Bing，让来源不要集中在一家媒体。")
    if quality.get("full_text_count", 0) < max(1, quality.get("article_count", 0) // 2):
        advice.append("优先选择可提取正文的信源，否则报告只能基于摘要。")
    if not advice:
        advice.append("可以生成；生成后请查看引用审计和证据侧栏。")
    return advice


def _extract_section(content: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$.*?(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    return match.group(0).strip() if match else ""


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace("，", ",").split(",") if item.strip()]


def split_sources(value: str) -> list[str]:
    sources = []
    for item in split_csv(value):
        if item in {"rss", "bing"} or item.startswith("rss:"):
            sources.append(item)
        elif item.startswith(("http://", "https://")):
            sources.append(f"rss:{item}")
    return sources


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), NewsWeaverHandler)
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"NewsWeaver web is running at {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
