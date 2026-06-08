"""OpenAI API 封装：含重试逻辑"""

import time

from openai import OpenAI

from ..utils import logger


class LLMClient:
    """OpenAI 兼容 API 客户端"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
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
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        raise RuntimeError(f"LLM 调用失败，已重试 {self.max_retries} 次: {last_error}")
