"""Resilient full-text extraction with cache, metadata, and adapter hooks."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .utils import atomic_write_json, get_data_dir, logger, read_json


DEFAULT_USER_AGENT = "NewsWeaver/1.3 (+https://github.com/YinL04/NewsWeaver)"


@dataclass
class ExtractionResult:
    text: str
    metadata: dict


class ExtractorAdapter(Protocol):
    """Domain adapter interface for publishers that need custom parsing."""

    def extract(self, html: str, url: str) -> str: ...


DOMAIN_ADAPTERS: dict[str, ExtractorAdapter] = {}


def register_extractor_adapter(domain: str, adapter: ExtractorAdapter) -> None:
    DOMAIN_ADAPTERS[domain.lower().removeprefix("www.")] = adapter


def extract_article(url: str, timeout: int = 10) -> str:
    """Backward-compatible text-only extraction; failures return an empty string."""
    return extract_article_detailed(url, timeout=timeout).text


def extract_article_detailed(
    url: str,
    timeout: int = 10,
    max_retries: int = 2,
    cache_dir: Path | None = None,
    cache_max_age: timedelta = timedelta(days=7),
    user_agent: str = DEFAULT_USER_AGENT,
) -> ExtractionResult:
    """Fetch and extract complete article text without fixed character truncation."""
    cache_root = cache_dir or (get_data_dir() / "cache" / "articles")
    cache_path = cache_root / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
    cached = _load_cache(cache_path, cache_max_age)
    if cached:
        metadata = dict(cached.get("metadata", {}))
        metadata.update({"cached": True, "status": "success", "content_length": len(cached.get("text", ""))})
        return ExtractionResult(cached.get("text", ""), metadata)

    response = None
    error = ""
    attempts = 0
    session = requests.Session()
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        try:
            response = session.get(
                url,
                timeout=timeout,
                headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding or "utf-8"
            break
        except requests.RequestException as exc:
            error = str(exc)
            response = None
            logger.debug(f"正文提取请求失败 {url} (attempt {attempts}): {exc}")
            if attempt < max_retries:
                time.sleep(0.25 * (2 ** attempt))
    if response is None:
        return ExtractionResult(
            "",
            {
                "status": "failed",
                "method": "none",
                "content_length": 0,
                "cached": False,
                "canonical_url": url,
                "requested_url": url,
                "attempts": attempts,
                "error": error,
            },
        )

    html = response.text
    canonical_url = _canonical_url(html, response.url or url)
    text, method, extraction_error = _extract_html(html, canonical_url)
    metadata = {
        "status": "success" if text else "failed",
        "method": method,
        "content_length": len(text),
        "cached": False,
        "canonical_url": canonical_url,
        "requested_url": url,
        "attempts": attempts,
        "http_status": response.status_code,
        "error": extraction_error,
    }
    if text:
        cache_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            cache_path,
            {
                "url": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "text": text,
                "metadata": metadata,
            },
        )
    return ExtractionResult(text, metadata)


def _extract_html(html: str, url: str) -> tuple[str, str, str]:
    domain = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for adapter_domain, adapter in DOMAIN_ADAPTERS.items():
        if domain == adapter_domain or domain.endswith("." + adapter_domain):
            try:
                text = _clean_text(adapter.extract(html, url))
                if len(text) > 100:
                    return text, f"adapter:{adapter_domain}", ""
            except Exception as exc:
                logger.debug(f"adapter 提取失败 {adapter_domain}: {exc}")

    errors = []
    try:
        from readability import Document

        text = _html_to_text(Document(html).summary())
        if len(text) > 100:
            return text, "readability", ""
    except Exception as exc:
        errors.append(f"readability: {exc}")
        logger.debug(f"readability 提取失败: {exc}")

    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "form", "noscript"]):
            tag.decompose()
        selectors = [
            "article",
            "[itemprop='articleBody']",
            ".article-content",
            ".article-body",
            ".post-content",
            ".entry-content",
            "main",
            "#content",
        ]
        for selector in selectors:
            container = soup.select_one(selector)
            if container:
                text = _clean_text(container.get_text(separator="\n", strip=True))
                if len(text) > 100:
                    return text, f"selector:{selector}", "; ".join(errors)
        body = soup.find("body")
        if body:
            text = _clean_text(body.get_text(separator="\n", strip=True))
            if text:
                return text, "body", "; ".join(errors)
    except Exception as exc:
        errors.append(f"beautifulsoup: {exc}")
        logger.debug(f"BeautifulSoup 提取失败: {exc}")
    return "", "none", "; ".join(errors)


def _canonical_url(html: str, response_url: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        link = soup.find("link", rel=lambda value: value and "canonical" in value)
        href = link.get("href", "").strip() if link else ""
        return urljoin(response_url, href) if href else response_url
    except Exception:
        return response_url


def _load_cache(path: Path, max_age: timedelta) -> dict:
    data = read_json(path)
    if not data or not data.get("text") or not data.get("fetched_at"):
        return {}
    try:
        fetched_at = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - fetched_at > max_age:
            return {}
    except (TypeError, ValueError):
        return {}
    return data


def _html_to_text(html: str) -> str:
    return _clean_text(BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True))


def _clean_text(text: str) -> str:
    text = re.sub(r"[\t\r ]+", " ", text or "")
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
