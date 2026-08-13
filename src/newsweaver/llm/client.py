"""OpenAI API 封装：含重试逻辑"""

import time
from urllib.parse import urlparse

from openai import OpenAI

from ..utils import logger


class LLMClient:
    """OpenAI 兼容 API 客户端"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.base_url = base_url
        self.model = model
        self.max_retries = 2
        self.retry_delay = 3

    def generate(self, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
        """调用 LLM 生成内容，失败自动重试"""
        model = model or self.model
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(f"LLM 调用 (尝试 {attempt + 1}/{self.max_retries + 1})")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.7,
                    max_tokens=4096,
                    **self._provider_options(model),
                )
                return self._response_text(response)
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        raise RuntimeError(f"LLM 调用失败，已重试 {self.max_retries} 次: {last_error}")

    def _provider_options(self, model: str) -> dict:
        """返回已知上游所需的最小兼容参数。"""
        hostname = urlparse(self.base_url).hostname or ""
        if hostname.lower() == "api.deepseek.com" and model.lower().startswith("deepseek-v4"):
            # DeepSeek V4 默认开启思考模式，推理 token 与最终答案共享
            # max_tokens。长提示可能在 content 开始前耗尽预算，得到空报告。
            # NewsWeaver 需要的是最终稿而非 reasoning_content，因此显式关闭。
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        return {}

    @staticmethod
    def _response_text(response) -> str:
        """提取最终文本，并拒绝看似成功的空 completion。"""
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise RuntimeError("LLM 返回空响应：没有 completion choice")

        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for item in content:
                value = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
                if isinstance(value, str):
                    parts.append(value)
            text = "".join(parts)
        else:
            text = ""

        if text.strip():
            return text.strip()

        finish_reason = getattr(choice, "finish_reason", None) or "unknown"
        reasoning_content = getattr(message, "reasoning_content", None) if message is not None else None
        reasoning_hint = "；模型仅返回了推理内容，未返回最终答案" if reasoning_content else ""
        raise RuntimeError(f"LLM 返回空白最终答案 (finish_reason={finish_reason}){reasoning_hint}")
