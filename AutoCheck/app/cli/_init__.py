# app/cli/__init__.py

"""
命令行界面 (CLI) 相关模块，包括配置向导和运行时命令处理。
"""

from .setup_wizard import SetupWizard # 原 ConfigUpdater
from .command_handler import CommandHandler

__all__ = [
    "SetupWizard",
    "CommandHandler",
]