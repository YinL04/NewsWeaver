import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from newsweaver.llm.client import LLMClient


def completion(content, finish_reason="stop", reasoning_content=None):
    message = SimpleNamespace(content=content, reasoning_content=reasoning_content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class LLMClientTest(unittest.TestCase):
    @patch("newsweaver.llm.client.OpenAI")
    def test_deepseek_v4_disables_default_thinking_mode(self, openai):
        create = Mock(return_value=completion(" final report "))
        openai.return_value.chat.completions.create = create
        client = LLMClient("secret", "https://api.deepseek.com", "deepseek-v4-flash")

        result = client.generate("system", "user")

        self.assertEqual(result, "final report")
        self.assertEqual(
            create.call_args.kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    @patch("newsweaver.llm.client.OpenAI")
    def test_empty_completion_is_retried_instead_of_saved(self, openai):
        create = Mock(side_effect=[completion("", "length", "reasoning"), completion("Recovered report")])
        openai.return_value.chat.completions.create = create
        client = LLMClient("secret")
        client.retry_delay = 0

        result = client.generate("system", "user")

        self.assertEqual(result, "Recovered report")
        self.assertEqual(create.call_count, 2)

    @patch("newsweaver.llm.client.OpenAI")
    def test_repeated_empty_completions_raise_clear_error(self, openai):
        create = Mock(return_value=completion(None))
        openai.return_value.chat.completions.create = create
        client = LLMClient("secret")
        client.retry_delay = 0

        with self.assertRaisesRegex(RuntimeError, "空白最终答案"):
            client.generate("system", "user")

        self.assertEqual(create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
