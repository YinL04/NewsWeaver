"""CLI 入口：click 命令组注册"""

import os
import sys

# Windows 终端 UTF-8 支持
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

import click

from . import __version__
from .utils import setup_logging


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="开启 DEBUG 日志输出")
@click.option("--config", "config_path", default=None, help="指定配置文件路径")
@click.version_option(__version__, prog_name="newsweaver")
@click.pass_context
def main(ctx, verbose, config_path):
    """NewsWeaver - 可定制 AI 资讯 Agent"""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["verbose"] = verbose


# 延迟导入子命令模块，避免循环依赖
from .topic import topic_group  # noqa: E402
from .commands import (  # noqa: E402
    config_group,
    doctor_cmd,
    fetch_cmd,
    generate_cmd,
    interactive_cmd,
    memory_group,
    preview_cmd,
    publish_cmd,
    web_cmd,
)

main.add_command(topic_group)
main.add_command(config_group)
main.add_command(doctor_cmd)
main.add_command(preview_cmd)
main.add_command(fetch_cmd)
main.add_command(generate_cmd)
main.add_command(memory_group)
main.add_command(publish_cmd)
main.add_command(web_cmd)
main.add_command(interactive_cmd)
