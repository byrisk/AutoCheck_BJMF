# app/config/remote_manager.py
import requests
import json
import threading
import time # <--- 确保这一行存在且未被注释
from datetime import datetime
from typing import Dict, Any, Optional, List 
from copy import deepcopy

from app.constants import AppConstants
from app.logger_setup import LoggerInterface, LogLevel

class RemoteConfigManager:
    def __init__(
        self,
        logger: LoggerInterface,
        primary_url: Optional[str],
        secondary_url: Optional[str],
        application_run_event: threading.Event
    ):
        self.logger = logger
        self.application_run_event = application_run_event
        self.primary_url = primary_url
        self.secondary_url = secondary_url
        self._config: Dict[str, Any] = deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG)
        self._last_successful_fetch_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self.fetch_config()

    def _fetch_from_url(self, url: str, attempt: int) -> Optional[Dict[str, Any]]:
        try:
            self.logger.log(
                f"尝试从 {url} 获取远程配置 (尝试 {attempt})", LogLevel.DEBUG
            )
            if not self.application_run_event.is_set():
                self.logger.log(f"应用停止，取消从 {url} 获取远程配置。", LogLevel.DEBUG)
                return None
                
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            config_data = response.json()
            self.logger.log(
                f"成功从 {url} 获取远程配置", LogLevel.DEBUG
            )
            return config_data
        except requests.RequestException as e:
            self.logger.log(
                f"从 {url} 获取配置失败 (尝试 {attempt}): {e}", LogLevel.DEBUG
            )
        except json.JSONDecodeError as e:
            self.logger.log(
                f"解析来自 {url} 的JSON配置失败 (尝试 {attempt}): {e}", LogLevel.DEBUG
            )
        return None

    def fetch_config(self) -> bool:
        urls_to_try = []
        if self.primary_url:
            urls_to_try.append(self.primary_url)
        if self.secondary_url:
            urls_to_try.append(self.secondary_url)

        if not urls_to_try:
            self.logger.log("未配置远程配置URL，使用默认或缓存的远程配置。", LogLevel.DEBUG)
            with self._lock:
                pass 
            return False

        max_retries_per_url = 3
        fetched_successfully = False

        for url_index, url in enumerate(urls_to_try):
            for attempt in range(1, max_retries_per_url + 1):
                if not self.application_run_event.is_set():
                    self.logger.log("应用停止，终止远程配置获取尝试。", LogLevel.INFO)
                    return False

                config_data = self._fetch_from_url(url, attempt)
                if config_data:
                    with self._lock:
                        merged_config = deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG)
                        for key, value in config_data.items():
                            if key in merged_config and isinstance(merged_config[key], dict) and isinstance(value, dict):
                                merged_config[key].update(value)
                            else:
                                merged_config[key] = value
                        self._config = merged_config
                        self._last_successful_fetch_time = datetime.now()
                    self.logger.log(
                        f"远程配置已从 {url} 更新。", LogLevel.INFO
                    )
                    fetched_successfully = True
                    break 

                if attempt < max_retries_per_url:
                    wait_time = 2**attempt
                    for _ in range(wait_time): # 使用 time.sleep()
                        if not self.application_run_event.is_set():
                            self.logger.log("应用停止，中断远程配置获取的等待。", LogLevel.INFO)
                            return False
                        time.sleep(1) # <--- 这里使用了 time.sleep()
            
            if fetched_successfully:
                break
        
        if not fetched_successfully:
            self.logger.log(
                "所有远程配置源均获取失败。将继续使用当前缓存的或默认的远程配置。", LogLevel.WARNING
            )
            return False
        return True

    def get_config_value(self, keys: List[str], default: Any = None) -> Any:
        with self._lock:
            config_dict = self._config
        try:
            for key in keys:
                config_dict = config_dict[key]
            return config_dict
        except (KeyError, TypeError):
            return default

    def is_cache_valid(self) -> bool:
        if not self._last_successful_fetch_time:
            return False
        return (
            datetime.now() - self._last_successful_fetch_time
        ).total_seconds() < AppConstants.REMOTE_CONFIG_CACHE_TTL_SECONDS

    def refresh_config_if_needed(self) -> None:
        if not self.is_cache_valid():
            self.logger.log("远程配置缓存已过期或无效，尝试刷新...", LogLevel.DEBUG)
            self.fetch_config()
        else:
            self.logger.log("远程配置缓存仍然有效。", LogLevel.DEBUG)
    
    def get_forced_update_below_version(self) -> str:
        return str(
            self.get_config_value(
                ["script_version_control", "forced_update_below_version"], "0.0.0"
            )
        )

    def is_globally_disabled(self) -> bool:
        return bool(self.get_config_value(["access_control", "global_disable"], False))

    def is_device_allowed(self, device_id: str) -> bool:
        whitelist = self.get_config_value(["access_control", "device_whitelist"], [])
        blacklist = self.get_config_value(["access_control", "device_blacklist"], [])
        if isinstance(whitelist, list) and whitelist:
            return device_id in whitelist
        if isinstance(blacklist, list) and device_id in blacklist:
            return False
        return True

    def get_announcement(self) -> Optional[Dict[str, Any]]:
        announcement_config = self.get_config_value(["announcement"], {})
        if (
            isinstance(announcement_config, dict)
            and announcement_config.get("enabled")
            and announcement_config.get("message")
        ):
            return {
                "id": str(announcement_config.get("id", "")),
                "title": str(announcement_config.get("title", "")).strip(),
                "message": str(announcement_config.get("message", "")),
                "enabled": True
            }
        return None

    def get_setting(self, setting_name: str, default: Any) -> Any:
        return self.get_config_value(["settings", setting_name], default)

    def is_forced_updates_enabled(self) -> bool:
        return bool(self.get_config_value(["script_version_control", "enable_forced_updates"], False))

    def get_optional_update_message_template(self) -> Optional[str]:
        msg = self.get_config_value(["script_version_control", "optional_update_message"], None)
        if msg and isinstance(msg, str) and msg.strip():
            return msg.strip()
        return None

    def get_global_disable_message(self) -> str:
        default_msg = "Access to the service is currently disabled globally."
        return str(self.get_config_value(["access_control", "global_disable_message"], default_msg))

    def get_device_block_message_template(self) -> str:
        default_msg = "Your device ({device_id}) is not permitted to use this service."
        return str(self.get_config_value(["access_control", "device_block_message_template"], default_msg))

    def get_forced_update_reason(self) -> Optional[str]:
        reason = self.get_config_value(["script_version_control", "forced_update_reason"])
        if reason and isinstance(reason, str) and reason.strip():
            return reason.strip()
        return None