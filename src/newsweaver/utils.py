"""工具函数：文件锁、日志配置、原子写入"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("newsweaver")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)


def get_data_dir() -> Path:
    """返回 ~/.newsweaver/ 目录，不存在则创建"""
    data_dir = Path.home() / ".newsweaver"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_memory_dir() -> Path:
    """返回 ~/.newsweaver/memory/ 目录"""
    mem_dir = get_data_dir() / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def get_output_dir() -> Path:
    """返回项目下的 output/ 目录"""
    out_dir = Path.cwd() / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def atomic_write_json(path: Path, data: dict) -> None:
    """原子写入 JSON 文件：先写临时文件，再重命名"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.stem
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def read_json(path: Path) -> dict:
    """读取 JSON 文件，不存在或损坏时返回空字典"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        backup = path.with_suffix(".json.bak")
        logger.warning(f"配置文件损坏，已备份至 {backup}")
        path.rename(backup)
        return {}


def truncate(text: str, max_len: int = 500) -> str:
    """截断文本到指定长度"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
