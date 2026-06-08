"""社交媒体发布接口（预留 + 模拟实现）"""

import uuid
from datetime import datetime, timezone

from .utils import logger


def publish_to_social(
    platform: str,
    content: str,
    media_paths: list[str] | None = None,
    credentials: dict | None = None,
) -> dict:
    """
    预留发布接口。当前仅打印日志并返回模拟结果。

    Args:
        platform: "twitter" | "linkedin" | "mastodon"
        content: 新闻正文（纯文本或 Markdown）
        media_paths: 可选图片附件路径
        credentials: 平台认证信息

    Returns:
        dict: {"success": bool, "post_id": str, "platform": str}

    Raises:
        ValueError: platform 不在支持列表中
        FileNotFoundError: media_paths 中的文件不存在
    """
    supported = {"twitter", "linkedin", "mastodon"}
    if platform not in supported:
        raise ValueError(f"不支持的平台: {platform}，可选: {', '.join(supported)}")

    if media_paths:
        import os
        for p in media_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"附件不存在: {p}")

    # 模拟发布
    post_id = f"mock_{uuid.uuid4().hex[:12]}"
    logger.info(f"[Mock] 发布到 {platform}，内容长度 {len(content)} 字符，ID: {post_id}")

    return {
        "success": True,
        "post_id": post_id,
        "platform": platform,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
