"""正文提取：readability-lxml + BeautifulSoup 降级"""

import re

import requests
from bs4 import BeautifulSoup

from .utils import logger


def extract_article(url: str, timeout: int = 10) -> str:
    """提取文章正文，失败返回空字符串"""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except requests.RequestException as e:
        logger.debug(f"正文提取请求失败 {url}: {e}")
        return ""

    html = resp.text

    # 优先使用 readability-lxml
    try:
        from readability import Document
        doc = Document(html)
        content_html = doc.summary()
        text = _html_to_text(content_html)
        if len(text) > 100:
            return text[:2000]
    except Exception as e:
        logger.debug(f"readability 提取失败: {e}")

    # 降级使用 BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
        # 移除无关标签
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe"]):
            tag.decompose()
        # 尝试常见的正文容器
        for selector in ["article", ".article-content", ".post-content", ".content", "main", "#content"]:
            container = soup.select_one(selector)
            if container:
                text = container.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text[:2000]
        # 最后兜底：body 全文
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            return text[:2000]
    except Exception as e:
        logger.debug(f"BeautifulSoup 提取失败: {e}")

    return ""


def _html_to_text(html: str) -> str:
    """将 HTML 转为纯文本"""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    # 合并多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
