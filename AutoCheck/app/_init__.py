# app/__init__.py

"""
应用主包。
"""

# 从子模块中提升常用的类/常量到 app 命名空间，方便外部导入
from .app_orchestrator import AppOrchestrator
from .constants import AppConstants, SCRIPT_VERSION
from .logger_setup import FileLogger, LogLevel, LoggerInterface
from .exceptions import ConfigError, LocationError, ServiceAccessError, UpdateRequiredError

# __all__ 定义了当执行 `from app import *` 时会导入哪些名字。
# 虽然通常不推荐使用 `import *`，但定义 `__all__` 是一个好习惯。
__all__ = [
    "AppOrchestrator",
    "AppConstants",
    "SCRIPT_VERSION",
    "FileLogger",
    "LogLevel",
    "LoggerInterface",
    "ConfigError",
    "LocationError",
    "ServiceAccessError",
    "UpdateRequiredError",
]