"""配置管理：读写 ~/.newsweaver/config.json，支持 .env 文件"""

import os
from pathlib import Path

from .utils import get_data_dir, atomic_write_json, read_json


def _load_dotenv() -> None:
    """从项目目录或 ~/.newsweaver/.env 加载环境变量"""
    for env_path in [
        Path.cwd() / ".env",
        get_data_dir() / ".env",
    ]:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            break

CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "llm": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "search": {
        "bing_api_key": "",
        "default_limit": 10,
        "days_back": 1,
    },
    "topics": [],
}


def get_config_path(custom_path: str | None = None) -> Path:
    if custom_path:
        return Path(custom_path)
    return get_data_dir() / "config.json"


def load_config(config_path: str | None = None) -> dict:
    _load_dotenv()
    path = get_config_path(config_path)
    config = read_json(path)
    if not config:
        config = DEFAULT_CONFIG.copy()
        atomic_write_json(path, config)
    # 环境变量覆盖配置文件（优先级：env > config.json）
    env_mapping = {
        "NEWSWEAVER_LLM_API_KEY": ("llm", "api_key"),
        "NEWSWEAVER_LLM_BASE_URL": ("llm", "base_url"),
        "NEWSWEAVER_LLM_MODEL": ("llm", "model"),
        "NEWSWEAVER_BING_API_KEY": ("search", "bing_api_key"),
    }
    for env_key, (section, key) in env_mapping.items():
        val = os.environ.get(env_key)
        if val:
            config.setdefault(section, {})[key] = val
    return config


def save_config(config: dict, config_path: str | None = None) -> None:
    path = get_config_path(config_path)
    atomic_write_json(path, config)


def get_nested(config: dict, key_path: str):
    """获取嵌套配置值，如 'llm.model'"""
    keys = key_path.split(".")
    val = config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return None
    return val


def set_nested(config: dict, key_path: str, value) -> None:
    """设置嵌套配置值，如 'llm.model' -> 'gpt-4o'"""
    keys = key_path.split(".")
    d = config
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    # 尝试自动转换类型
    if value.lower() in ("true", "false"):
        value = value.lower() == "true"
    elif value.isdigit():
        value = int(value)
    else:
        try:
            value = float(value)
        except ValueError:
            pass
    d[keys[-1]] = value


def find_topic(config: dict, name: str) -> dict | None:
    for t in config.get("topics", []):
        if t["name"] == name:
            return t
    return None
