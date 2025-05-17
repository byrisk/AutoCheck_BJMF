# app/config/__init__.py

"""
配置管理模块，包含配置模型、存储、本地及远程配置管理器。
"""

from .models import ConfigModel, HotSpotData, SelectedSchoolData
from .storage import ConfigStorageInterface, JsonConfigStorage
from .manager import ConfigManager
from .remote_manager import RemoteConfigManager

__all__ = [
    "ConfigModel",
    "HotSpotData",
    "SelectedSchoolData",
    "ConfigStorageInterface",
    "JsonConfigStorage",
    "ConfigManager",
    "RemoteConfigManager",
]