# app/config/storage.py
import json
import os # JsonConfigStorage 使用了 AppConstants.CONFIG_FILE，但最好路径由外部传入
from abc import ABC, abstractmethod
from typing import Dict, Any

# AppConstants.CONFIG_FILE 的使用需要调整。
# JsonConfigStorage 的构造函数应接收 config_path 参数，而不是硬编码依赖 AppConstants
# from app.constants import AppConstants # 暂时保留，以便原代码能粘贴过来

class ConfigStorageInterface(ABC):
    @abstractmethod
    def load(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save(self, config: Dict[str, Any]) -> None:
        pass
class JsonConfigStorage(ConfigStorageInterface):
    def __init__(self, config_path: str): # 移除默认值对 AppConstants 的依赖
        self.config_path = config_path

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件 {self.config_path} 格式错误: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except IOError as e:
            raise ValueError(f"保存配置文件 {self.config_path} 时出错: {e}")

