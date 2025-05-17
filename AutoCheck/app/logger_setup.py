# app/logger_setup.py
import os
import sys
import traceback
from enum import Enum, auto
from abc import ABC, abstractmethod
from datetime import datetime
import colorama # 确保导入了 colorama
from colorama import Fore, Style

# 从我们新创建的 app.constants 模块导入 AppConstants
# FileLogger 类会使用 AppConstants.LOG_DIR
from app.constants import AppConstants

# 直接初始化 colorama，它能处理重复调用
# 如果在其他地方也初始化了，autoreset=True 通常能保证行为一致
colorama.init(autoreset=True)

class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()

class LoggerInterface(ABC):
    @abstractmethod
    def log(self, message: str, level: LogLevel = LogLevel.INFO, exc_info: bool = False) -> None:
        pass

class FileLogger(LoggerInterface):
    def __init__(
        self, log_file: str = "auto_check.log", console_level: LogLevel = LogLevel.INFO
    ):
        # AppConstants.LOG_DIR 是 "logs"
        # self.log_file 将是 "logs/auto_check.log" (相对于项目根目录)
        # FileLogger 内部的 _setup_log_directory 会创建 AppConstants.LOG_DIR 这个目录。
        # os.path.join 会正确处理路径拼接。
        self.log_file = os.path.join(AppConstants.LOG_DIR, log_file)
        self._setup_log_directory()
        self.console_level = console_level
        self.color_map = {
            LogLevel.DEBUG: Fore.CYAN,
            LogLevel.INFO: Fore.GREEN,
            LogLevel.WARNING: Fore.YELLOW,
            LogLevel.ERROR: Fore.RED,
            LogLevel.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
        }
        self.icon_map = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌",
            LogLevel.CRITICAL: "🚨",
        }

    def _setup_log_directory(self) -> None:
        # AppConstants.LOG_DIR 定义为 "logs"
        # 这个方法会在项目根目录下创建 "logs" 文件夹 (如果不存在)
        # os.makedirs 会基于当前工作目录创建（除非AppConstants.LOG_DIR是绝对路径）
        # 当从 main.py 运行时，当前工作目录通常是项目根目录，所以这是期望的行为。
        if not os.path.exists(AppConstants.LOG_DIR):
            try:
                os.makedirs(AppConstants.LOG_DIR)
            except OSError as e:
                print(f"创建日志目录失败 ({AppConstants.LOG_DIR}): {e}")


    def log(self, message: str, level: LogLevel = LogLevel.INFO, exc_info: bool = False) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry_message = message # 保存原始消息用于控制台

        if exc_info and sys.exc_info()[0] is not None:
            # 使用 traceback.format_exc() 可以获取完整的堆栈信息字符串
            tb_info = traceback.format_exc()
            message += "\n" + tb_info

        log_entry_file = f"[{timestamp}] [{level.name}] {message}\n"

        # 控制台输出逻辑
        if level.value >= self.console_level.value:
            color = self.color_map.get(level, Fore.WHITE)
            icon = self.icon_map.get(level, "")

            # 检查 stdout 是否是 TTY (终端) 以及是否需要静默输出
            # "--silent" 的检查应该在更上层控制 console_level，这里简化
            if sys.stdout.isatty() and "--silent" not in sys.argv:
                # 之前的 \r\033[K 在多行日志或多线程日志下可能会导致显示混乱
                # 直接打印通常更安全，让终端处理换行
                print(f"{color}{icon} [{timestamp}] {log_entry_message}{Style.RESET_ALL}")

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry_file)
        except IOError as e:
            # 这是一个严重问题，如果日志都无法写入
            print(
                f"{Fore.RED}[{timestamp}] [CRITICAL_ERROR] 无法写入日志文件 {self.log_file}: {e}{Style.RESET_ALL}"
            )