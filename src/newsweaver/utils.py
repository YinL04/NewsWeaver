"""工具函数：文件锁、日志配置、原子写入"""

import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from traceback import format_exception

logger = logging.getLogger("newsweaver")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    log_file = get_log_file()
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_file for handler in logger.handlers):
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)


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


def get_log_dir() -> Path:
    """返回本地日志目录"""
    candidates = [Path.home() / ".newsweaver" / "logs", Path.cwd() / "output" / "logs"]
    for log_dir in candidates:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir
        except OSError:
            continue
    return Path.cwd()


def get_log_file() -> Path:
    """返回默认错误日志文件"""
    return get_log_dir() / "newsweaver.log"


def log_exception(context: str, exc: BaseException) -> None:
    """将异常追加写入本地日志，便于 Web 用户排查失败原因"""
    get_log_dir().mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        f"[{datetime.now().isoformat(timespec='seconds')}] {context}",
        "".join(format_exception(type(exc), exc, exc.__traceback__)).rstrip(),
    ]
    with open(get_log_file(), "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


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
