"""Small local web app for user-facing NewsWeaver workflows."""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import find_topic, load_config, save_config
from .pipeline import article_to_dict, build_fact_pack, build_quality_report, collect_articles
from .utils import get_memory_dir, get_output_dir


WEB_ROOT = Path(__file__).parent / "web"


class NewsWeaverHandler(BaseHTTPRequestHandler):
    server_version = "NewsWeaverWeb/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html")
        elif parsed.path.startswith("/static/"):
            self._serve_static(parsed.path.removeprefix("/static/"))
        elif parsed.path == "/api/state":
            self._json(self._state())
        elif parsed.path == "/api/report":
            self._get_report(parse_qs(parsed.query))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_json()
        try:
            if parsed.path == "/api/config":
                self._save_config(body)
            elif parsed.path == "/api/topics":
                self._add_topic(body)
            elif parsed.path == "/api/topics/delete":
                self._delete_topic(body)
            elif parsed.path == "/api/preview":
                self._preview(body)
            elif parsed.path == "/api/generate":
                self._generate(body)
            else:
                self.send_error(404)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relative: str) -> None:
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
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
        for path in sorted(get_output_dir().glob("*.md"), reverse=True):
            reports.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "modified": path.stat().st_mtime,
                }
            )
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
            "reports": reports[:20],
        }

    def _save_config(self, body: dict) -> None:
        config = load_config()
        llm = config.setdefault("llm", {})
        search = config.setdefault("search", {})
        for key in ("api_key", "base_url", "model"):
            value = body.get(key)
            if value is not None and value != "":
                llm[key] = value
        for key in ("default_limit", "days_back"):
            value = body.get(key)
            if value not in (None, ""):
                search[key] = int(value)
        save_config(config)
        self._json({"ok": True, "state": self._state()})

    def _add_topic(self, body: dict) -> None:
        config = load_config()
        name = (body.get("name") or "").strip()
        if not name:
            raise ValueError("Topic name is required.")
        if find_topic(config, name):
            raise ValueError("Topic already exists.")
        topic = {
            "name": name,
            "keywords": split_csv(body.get("keywords", "")),
            "exclude_words": split_csv(body.get("exclude_words", "")),
            "sources": split_csv(body.get("sources", "")),
            "language": body.get("language") or "zh",
        }
        if not topic["keywords"]:
            raise ValueError("At least one keyword is required.")
        config.setdefault("topics", []).append(topic)
        save_config(config)
        self._json({"ok": True, "topic": topic, "state": self._state()})

    def _delete_topic(self, body: dict) -> None:
        config = load_config()
        name = (body.get("name") or "").strip()
        topics = config.get("topics", [])
        new_topics = [topic for topic in topics if topic.get("name") != name]
        if len(new_topics) == len(topics):
            raise ValueError("Topic does not exist.")
        config["topics"] = new_topics
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
            raise ValueError("Topic does not exist.")
        limit = int(body.get("limit") or config.get("search", {}).get("default_limit", 10))
        articles = collect_articles(config, topic, limit)
        facts = build_fact_pack(topic_name, articles)
        quality = build_quality_report(topic_name, articles, facts)
        self._json(
            {
                "quality": quality,
                "facts": facts,
                "articles": [article_to_dict(a, topic.get("keywords", [])) for a in articles],
            }
        )

    def _generate(self, body: dict) -> None:
        from .generator import run_generate

        config = load_config()
        topic_name = body.get("topic")
        topic = find_topic(config, topic_name)
        if not topic:
            raise ValueError("Topic does not exist.")
        model = body.get("model") or config.get("llm", {}).get("model")
        limit = int(body.get("limit") or config.get("search", {}).get("default_limit", 10))
        output_path = run_generate(config, topic, model=model, limit=limit)
        self._json({"ok": True, "path": str(output_path), "state": self._state()})

    def _get_report(self, query: dict) -> None:
        name = (query.get("name") or [""])[0]
        target = (get_output_dir() / name).resolve()
        output_root = get_output_dir().resolve()
        if output_root not in target.parents and target != output_root:
            self.send_error(403)
            return
        if not target.exists() or target.suffix != ".md":
            self.send_error(404)
            return
        self._json({"name": target.name, "content": target.read_text(encoding="utf-8")})


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), NewsWeaverHandler)
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"NewsWeaver web is running at {url}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
