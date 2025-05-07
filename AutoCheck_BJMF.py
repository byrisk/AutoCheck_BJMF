import requests
import re
import time
import os
import json
import sys
from bs4 import BeautifulSoup
import colorama
from colorama import Fore, Style
import random
import tkinter as tk
from io import BytesIO
from PIL import Image, ImageTk
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from pydantic import BaseModel, field_validator, ValidationError
from typing import Dict, List, Set, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
import threading
from copy import deepcopy
import uuid
import platform
from datetime import timezone

# Initialize colorama
colorama.init(autoreset=True)

# === Application Version ===
SCRIPT_VERSION = "1.0.0" # Used for forced update checks

# === Constants Definition ===
class AppConstants:
    REQUIRED_FIELDS: Tuple[str, ...] = ("cookie", "class_id", "lat", "lng", "acc")
    COOKIE_PATTERN: str = r'remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=[^;]+'
    LOG_DIR: str = "logs"
    CONFIG_FILE: str = "data.json"
    DEVICE_ID_FILE: str = "device_id.txt" # Stores unique device ID
    DEFAULT_SEARCH_INTERVAL: int = 60
    USER_AGENT_TEMPLATE: str = (
        "Mozilla/5.0 (Linux; Android {android_version}; {device} Build/{build_number}; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_version} Mobile Safari/537.36 "
        "MicroMessenger/{wechat_version} NetType/{net_type} Language/zh_CN"
    )
    DEFAULT_RUN_TIME = {
        'enable_time_range': False,
        'start_time': '08:00',
        'end_time': '22:00'
    }

    # --- Remote Configuration Gist URLs (User needs to set these up) ---
    # Example: "https://gist.githubusercontent.com/YourUser/YourGistId/raw/remote_config.json"
    PRIMARY_REMOTE_CONFIG_URL: Optional[str] = "https://raw.githubusercontent.com/byrisk/AutoCheck_BJMF/refs/heads/main/master/remote_config.json" # Primary source for remote config
    SECONDARY_REMOTE_CONFIG_URL: Optional[str] = "https://gist.githubusercontent.com/byrisk/1b931a51a5f976097bc796f13602c7bd/raw/config.json" # Fallback source

    # --- Data Upload Gist Configuration ---
    DATA_UPLOAD_GIST_ID: str = "41a6aa985a553b9fe94b9ee14182d2f7" # Gist ID for uploading data
    DATA_UPLOAD_FILENAME: str = "device_activity_log.jsonl"      # Filename within the Gist for data
    # IMPORTANT: The GitHub PAT is sensitive. Prefer environment variables or secure storage.
    GITHUB_PAT: str = "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" # GitHub Personal Access Token with 'gist' scope

    # --- Intervals for Background Tasks ---
    REMOTE_CONFIG_CACHE_TTL_SECONDS: int = 300  # 5 minutes for remote config cache
    DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS: int = 900 # 15 minutes
    DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS: int = 3600 # 1 hour

    # --- Default Remote Configuration (used if fetching fails on startup) ---
    DEFAULT_REMOTE_CONFIG: Dict[str, Any] = {
        "script_version_control": {"forced_update_below_version": "0.0.0"},
        "access_control": {
            "global_disable": False,
            "device_blacklist": [],
            "device_whitelist": [] 
        },
        "announcement": {"id": "", "message": "", "enabled": False},
        "settings": {
            "config_refresh_interval_seconds": DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS,
            "data_upload_interval_seconds": DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS
        }
    }

# Global event to signal application-wide shutdown
application_run_event = threading.Event()
application_run_event.set() # Application is allowed to run by default

# === 日志系统 (Logging System) ===
class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto() # 用于严重错误或强制关闭信息

class LoggerInterface(ABC):
    @abstractmethod
    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        pass

class FileLogger(LoggerInterface):
    # 注意这里的 __init__ 方法定义，它必须包含 console_level 参数
    def __init__(self, log_file: str = "auto_check.log", console_level: LogLevel = LogLevel.INFO): # <--- 确认这一行是这样的
        self.log_file = os.path.join(AppConstants.LOG_DIR, log_file)
        self._setup_log_directory()
        self.console_level = console_level # 并且这里正确设置了 self.console_level
        self.color_map = {
            LogLevel.DEBUG: Fore.CYAN,
            LogLevel.INFO: Fore.GREEN,
            LogLevel.WARNING: Fore.YELLOW,
            LogLevel.ERROR: Fore.RED,
            LogLevel.CRITICAL: Fore.MAGENTA + Style.BRIGHT
        }
        self.icon_map = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌",
            LogLevel.CRITICAL: "🚨"
        }

    def _setup_log_directory(self) -> None:
        if not os.path.exists(AppConstants.LOG_DIR):
            try:
                os.makedirs(AppConstants.LOG_DIR)
            except OSError as e:
                # 如果在程序非常早期就发生错误，colorama可能还未初始化，直接print
                print(f"创建日志目录失败: {e}")

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level.name}] {message}\n"

        # 基于 console_level 控制控制台日志输出
        if level.value >= self.console_level.value:
            if "--silent" not in sys.argv or level in [LogLevel.ERROR, LogLevel.CRITICAL]:
                color = self.color_map.get(level, Fore.WHITE) # 提供一个默认颜色
                icon = self.icon_map.get(level, "")
                # 这是一个启发式方法，尝试避免 INFO 级别的日志覆盖命令提示符
                # prefix = "\n" if level == LogLevel.INFO and "(输入命令:" in message else "" # 这个启发式方法可能过于复杂，暂时移除
                print(f"{color}{icon} [{timestamp}] {message}{Style.RESET_ALL}") # 移除了 prefix

        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except IOError as e:
            print(f"{Fore.RED}[{timestamp}] [ERROR] 写入日志文件时出错: {e}{Style.RESET_ALL}")

# === Device ID Manager ===
class DeviceManager:
    def __init__(self, logger: LoggerInterface, device_id_file: str = AppConstants.DEVICE_ID_FILE):
        self.logger = logger
        self.device_id_file = device_id_file
        self.device_id: str = self._load_or_create_device_id()

    def _load_or_create_device_id(self) -> str:
        try:
            if os.path.exists(self.device_id_file):
                with open(self.device_id_file, 'r') as f:
                    device_id = f.read().strip()
                if device_id:
                    self.logger.log(f"设备ID加载成功: {device_id}", LogLevel.DEBUG)
                    return device_id
        except IOError as e:
            self.logger.log(f"读取设备ID文件失败: {e}", LogLevel.WARNING)

        # Create new device ID
        device_id = str(uuid.uuid4())
        try:
            with open(self.device_id_file, 'w') as f:
                f.write(device_id)
            self.logger.log(f"新设备ID已创建并保存: {device_id}", LogLevel.INFO)
        except IOError as e:
            self.logger.log(f"保存新设备ID失败: {e}. 将在内存中使用: {device_id}", LogLevel.ERROR)
        return device_id

    def get_id(self) -> str:
        return self.device_id

# === Remote Configuration Manager ===
class RemoteConfigManager:
    def __init__(self, logger: LoggerInterface, primary_url: Optional[str], secondary_url: Optional[str]):
        self.logger = logger
        self.primary_url = primary_url
        self.secondary_url = secondary_url
        self._config: Dict[str, Any] = deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG)
        self._last_successful_fetch_time: Optional[datetime] = None
        self._lock = threading.Lock()
        self.fetch_config() # Initial fetch

    def _fetch_from_url(self, url: str, attempt: int) -> Optional[Dict[str, Any]]:
        try:
            self.logger.log(f"尝试从 {url} 获取远程配置 (尝试 {attempt})", LogLevel.DEBUG)
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            config_data = response.json()
            self.logger.log(f"成功从 {url} 获取远程配置", LogLevel.DEBUG) # 修改为 DEBUG
            return config_data
        except requests.RequestException as e:
            self.logger.log(f"从 {url} 获取配置失败 (尝试 {attempt}): {e}", LogLevel.WARNING)
        except json.JSONDecodeError as e:
            self.logger.log(f"解析来自 {url} 的JSON配置失败 (尝试 {attempt}): {e}", LogLevel.WARNING)
        return None

    def fetch_config(self) -> bool:
        """Fetches config from primary, then secondary, with retries and backoff."""
        urls_to_try = []
        if self.primary_url:
            urls_to_try.append(self.primary_url)
        if self.secondary_url:
            urls_to_try.append(self.secondary_url)

        if not urls_to_try:
            self.logger.log("未配置远程配置URL，使用默认配置。", LogLevel.WARNING)
            with self._lock:
                self._config = deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG)
            return False

        max_retries_per_url = 2 
        fetched_successfully = False

        for url_index, url in enumerate(urls_to_try):
            for attempt in range(1, max_retries_per_url + 1):
                if not application_run_event.is_set(): return False # Stop if app is shutting down
                
                config_data = self._fetch_from_url(url, attempt)
                if config_data:
                    with self._lock:
                        self._config = {**deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG), **config_data} # Merge with defaults
                        self._last_successful_fetch_time = datetime.now()
                    # self.logger.log(f"远程配置已更新自 {url}.", LogLevel.INFO)
                    
                        self._config = {**deepcopy(AppConstants.DEFAULT_REMOTE_CONFIG), **config_data}
                        self._last_successful_fetch_time = datetime.now()
                    self.logger.log(f"远程配置已更新自 {url}.", LogLevel.DEBUG) # 修改为 DEBUG
                    
                    fetched_successfully = True
                    break # Success, move to next URL or finish
                
                if attempt < max_retries_per_url:
                    # Exponential backoff, but simple delay here for brevity
                    time.sleep(2 ** attempt) 
            if fetched_successfully:
                break # Fetched from this URL, no need to try next one in the list

        if not fetched_successfully:
            self.logger.log("所有远程配置源均获取失败。可能使用旧的或默认配置。", LogLevel.ERROR)
            # Keep existing or default config if all fetches fail
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
        return (datetime.now() - self._last_successful_fetch_time).total_seconds() < AppConstants.REMOTE_CONFIG_CACHE_TTL_SECONDS

    def refresh_config_if_needed(self) -> None:
        if not self.is_cache_valid():
            self.logger.log("远程配置缓存已过期，尝试刷新...", LogLevel.DEBUG)
            self.fetch_config()
        else:
            self.logger.log("远程配置缓存仍然有效。", LogLevel.DEBUG)
            
    def get_forced_update_below_version(self) -> str:
        return str(self.get_config_value(["script_version_control", "forced_update_below_version"], "0.0.0"))

    def is_globally_disabled(self) -> bool:
        return bool(self.get_config_value(["access_control", "global_disable"], False))

    def is_device_allowed(self, device_id: str) -> bool:
        whitelist = self.get_config_value(["access_control", "device_whitelist"], [])
        blacklist = self.get_config_value(["access_control", "device_blacklist"], [])

        if isinstance(whitelist, list) and whitelist: # If whitelist is present and not empty, it takes precedence
            return device_id in whitelist
        
        if isinstance(blacklist, list) and device_id in blacklist: # Otherwise, check blacklist
            return False
        
        return True # Allowed by default if not in blacklist or if whitelist is empty

    def get_announcement(self) -> Optional[Dict[str, str]]:
        announcement_config = self.get_config_value(["announcement"], {})
        if isinstance(announcement_config, dict) and \
           announcement_config.get("enabled") and \
           announcement_config.get("message"):
            return {
                "id": str(announcement_config.get("id", "")),
                "message": str(announcement_config.get("message",""))
            }
        return None

    def get_setting(self, setting_name: str, default: Any) -> Any:
        return self.get_config_value(["settings", setting_name], default)

# === Data Uploader ===
class DataUploader:
    def __init__(self, logger: LoggerInterface, device_id: str, gist_id: str, filename: str, pat: str):
        self.logger = logger
        self.device_id = device_id
        self.gist_id = gist_id
        self.filename_in_gist = filename
        self.github_pat = pat
        self.api_base_url = "https://api.github.com"

    def _get_os_info(self) -> str:
        return f"{platform.system()} {platform.release()}"

    def upload_data(self) -> None:
        if not self.github_pat or self.github_pat == "YOUR_GITHUB_PAT_HERE_OR_REMOVE_IF_NOT_USED":
            self.logger.log("GitHub PAT未配置，跳过数据上传。", LogLevel.WARNING)
            return

        if not application_run_event.is_set():
            self.logger.log("应用程序正在关闭，跳过数据上传。", LogLevel.DEBUG)
            return

        log_entry = {
            # "timestamp": datetime.utcnow().isoformat() + "Z",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), 
            "device_id": self.device_id,
            "os_info": self._get_os_info(),
            "script_version": SCRIPT_VERSION,
            "event_type": "heartbeat" # Or other types like "sign_in_attempt", "config_update"
        }
        new_data_line = json.dumps(log_entry)

        gist_url = f"{self.api_base_url}/gists/{self.gist_id}"
        headers = {
            "Authorization": f"token {self.github_pat}",
            "Accept": "application/vnd.github.v3+json"
        }

        try:
            # 1. Fetch current Gist content
            self.logger.log(f"正在获取Gist {self.gist_id} 的当前内容...", LogLevel.DEBUG)
            response = requests.get(gist_url, headers=headers, timeout=15)
            response.raise_for_status()
            gist_data = response.json()
            
            old_content = ""
            if self.filename_in_gist in gist_data.get("files", {}):
                file_info = gist_data["files"][self.filename_in_gist]
                if file_info and 'content' in file_info: # Check if content exists
                     old_content = file_info.get("content", "")
                else: # File exists but content might be missing (e.g. truncated)
                    self.logger.log(f"文件 {self.filename_in_gist} 在Gist中存在但无内容，将创建新内容。", LogLevel.DEBUG)
            else:
                self.logger.log(f"文件 {self.filename_in_gist} 在Gist中不存在，将创建。", LogLevel.DEBUG)

            # 2. Append new data
            # Ensure old_content ends with a newline if it's not empty
            if old_content and not old_content.endswith("\n"):
                updated_content = old_content + "\n" + new_data_line + "\n"
            else:
                updated_content = old_content + new_data_line + "\n"

            # 3. Update Gist
            payload = {
                "files": {
                    self.filename_in_gist: {
                        "content": updated_content
                    }
                }
            }
            self.logger.log(f"正在上传数据到Gist {self.gist_id}...", LogLevel.DEBUG)
            patch_response = requests.patch(gist_url, headers=headers, json=payload, timeout=20)
            patch_response.raise_for_status()
            # self.logger.log(f"数据成功上传到Gist {self.gist_id}/{self.filename_in_gist}", LogLevel.INFO)
            self.logger.log(f"数据成功上传到Gist {self.gist_id}/{self.filename_in_gist}", LogLevel.DEBUG) # 修改为 DEBUG
        except requests.RequestException as e:
            self.logger.log(f"上传数据到Gist失败: {e}", LogLevel.ERROR)
            if e.response is not None:
                self.logger.log(f"Gist API响应: {e.response.text}", LogLevel.DEBUG)
        except Exception as e:
            self.logger.log(f"处理数据上传时发生未知错误: {e}", LogLevel.ERROR)


# === Background Job Manager ===
class BackgroundJobManager:
    def __init__(self, logger: LoggerInterface):
        self.logger = logger
        self.jobs: List[Tuple[Callable, int, str]] = []
        self.threads: List[threading.Thread] = []

    def add_job(self, task: Callable, interval_seconds: int, job_name: str):
        self.jobs.append((task, interval_seconds, job_name))

    def _run_job(self, task: Callable, interval_seconds: int, job_name: str):
        # self.logger.log(f"后台任务 '{job_name}' 已启动，执行间隔: {interval_seconds} 秒。", LogLevel.INFO)
        self.logger.log(f"后台任务 '{job_name}' (间隔: {interval_seconds}s) 监控已启动。", LogLevel.DEBUG) 
        while application_run_event.is_set():
            try:
                task_name_for_log = job_name
                # 对于控制台，将实际执行日志记录为 DEBUG 级别；对于文件，记录为 INFO 级别
                self.logger.log(f"执行后台任务: {task_name_for_log}", LogLevel.DEBUG) # 修改为 DEBUG
                task()
            except Exception as e:
                self.logger.log(f"后台任务 '{job_name}' 执行出错: {e}", LogLevel.ERROR)
            
            # Wait for the interval, but check application_run_event frequently
            for _ in range(interval_seconds):
                if not application_run_event.is_set():
                    break
                time.sleep(1)
        self.logger.log(f"后台任务 '{job_name}' 已停止。", LogLevel.DEBUG) # 控制台记录为 DEBUG (DEBUG for console)


    def start_jobs(self):
        if not self.jobs:
            self.logger.log("没有要启动的后台任务。", LogLevel.INFO)
            return

        for task, interval, name in self.jobs:
            thread = threading.Thread(target=self._run_job, args=(task, interval, name), daemon=True)
            self.threads.append(thread)
            thread.start()
        self.logger.log(f"{len(self.threads)} 个后台任务已启动。", LogLevel.INFO)

    def stop_jobs(self): # Should be called if application_run_event is cleared elsewhere too
        self.logger.log("正在停止所有后台任务...", LogLevel.INFO)
        # application_run_event.clear() # Signal threads to stop
        # Threads are daemons, but explicit join is good practice if needed, though not strictly required for daemons on app exit
        # For this design, clearing application_run_event is the primary stop mechanism.


# === Configuration Model (Pydantic) ===
class ConfigModel(BaseModel):
    cookie: str
    class_id: str
    lat: str
    lng: str
    acc: str
    time: int = AppConstants.DEFAULT_SEARCH_INTERVAL
    pushplus: str = ""
    remark: str = "自动签到配置"
    enable_time_range: bool = False
    start_time: str = "08:00"
    end_time: str = "22:00"

    @field_validator('class_id')
    @classmethod
    def validate_class_id(cls, v: str) -> str:
        if not v:
            raise ValueError("班级ID不能为空")
        if not v.isdigit():
            raise ValueError("班级ID必须为数字")
        return v

    @field_validator('lat')
    @classmethod
    def validate_latitude(cls, v: str) -> str:
        if not v:
            raise ValueError("纬度不能为空")
        try:
            lat_float = float(v)
            if not -90 <= lat_float <= 90:
                raise ValueError("纬度需在 -90 到 90 之间")
            return v
        except ValueError:
            raise ValueError("纬度必须是有效数字")

    @field_validator('lng')
    @classmethod
    def validate_longitude(cls, v: str) -> str:
        if not v:
            raise ValueError("经度不能为空")
        try:
            lng_float = float(v)
            if not -180 <= lng_float <= 180:
                raise ValueError("经度需在 -180 到 180 之间")
            return v
        except ValueError:
            raise ValueError("经度必须是有效数字")

    @field_validator('acc') # Accuracy, not altitude, based on typical GPS data. Renamed validator for clarity.
    @classmethod
    def validate_accuracy(cls, v: str) -> str: # Changed from validate_altitude
        if not v:
            raise ValueError("精度不能为空") # Changed from 海拔 (altitude)
        try:
            float(v) # Accuracy is usually a float
            return v
        except ValueError:
            raise ValueError("精度必须是有效数字") # Changed from 海拔

    @field_validator('cookie')
    @classmethod
    def validate_cookie(cls, v: str) -> str:
        if not v:
            raise ValueError("Cookie 不能为空")
        if not re.search(AppConstants.COOKIE_PATTERN, v):
            raise ValueError("Cookie 缺少关键字段，需包含 remember_student_...")
        return v

    @field_validator('time')
    @classmethod
    def validate_search_time(cls, v: Any) -> int:
        if isinstance(v, str):
            try:
                v_int = int(v)
            except ValueError:
                raise ValueError("检索间隔必须为有效的整数")
        elif isinstance(v, int):
            v_int = v
        else:
            raise ValueError("检索间隔类型无效")
            
        if v_int <= 0:
            raise ValueError("检索间隔必须为正整数")
        return v_int

    @field_validator('start_time', 'end_time')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError("时间格式必须为 HH:MM")

# === Configuration Storage ===
class ConfigStorageInterface(ABC):
    @abstractmethod
    def load(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save(self, config: Dict[str, Any]) -> None:
        pass

class JsonConfigStorage(ConfigStorageInterface):
    def __init__(self, config_path: str = AppConstants.CONFIG_FILE):
        self.config_path = config_path

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件 {self.config_path} 格式错误: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except IOError as e:
            raise ValueError(f"保存配置文件 {self.config_path} 时出错: {e}")

# === Configuration Manager ===
class ConfigManager:
    def __init__(self, storage: ConfigStorageInterface, logger: LoggerInterface):
        self.storage = storage
        self.logger = logger
        self._config = self._load_config()

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        self._config = value

    def _load_config(self) -> Dict[str, Any]:
        try:
            raw_config = self.storage.load()
            defaults = {
                "time": AppConstants.DEFAULT_SEARCH_INTERVAL,
                "remark": "自动签到配置",
                "enable_time_range": AppConstants.DEFAULT_RUN_TIME['enable_time_range'],
                "start_time": AppConstants.DEFAULT_RUN_TIME['start_time'],
                "end_time": AppConstants.DEFAULT_RUN_TIME['end_time'],
                "pushplus": ""
            }
            # Ensure all required fields exist before validation, even if empty
            for req_field in AppConstants.REQUIRED_FIELDS:
                if req_field not in raw_config:
                    raw_config[req_field] = "" # Provide empty string for missing required fields to allow Pydantic to catch it

            config_with_defaults = {**defaults, **raw_config}


            # Validate required fields are not empty after defaults
            missing_fields = [field for field in AppConstants.REQUIRED_FIELDS if not config_with_defaults.get(field)]
            if missing_fields:
                 # This case is for when file exists but fields are empty.
                 # If file doesn't exist, FileNotFoundError is caught below.
                self.logger.log(f"配置文件缺少必填字段: {', '.join(missing_fields)}. 请运行配置向导。", LogLevel.ERROR)
                return {} # Signal to run config wizard

            return ConfigModel(**config_with_defaults).model_dump()

        except FileNotFoundError:
            self.logger.log(f"配置文件 {self.storage.config_path if hasattr(self.storage, 'config_path') else 'data.json'} 未找到。将创建默认配置并提示用户。", LogLevel.WARNING)
            # Don't save defaults here, let ConfigUpdater handle first run
            return {} # Return empty to trigger wizard
        except (ValueError, ValidationError) as e: # Catch Pydantic validation errors too
            self._handle_validation_error(e if isinstance(e, ValidationError) else None, str(e))
            return {} # Return empty to trigger wizard

    def _handle_validation_error(self, error: Optional[ValidationError], message: Optional[str] = None) -> None:
        if error:
            error_messages = [f"{err['loc'][0]}: {err['msg']}" for err in error.errors()]
            self.logger.log("本地配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)
        elif message:
            self.logger.log(f"本地配置加载错误: {message}", LogLevel.ERROR)


    def save(self) -> None:
        try:
            # Re-validate before saving
            ConfigModel(**self._config)
            self.storage.save(self._config)
            self.logger.log("本地配置保存成功。", LogLevel.INFO)
        except (ValueError, ValidationError) as e:
            self._handle_validation_error(e if isinstance(e, ValidationError) else None, str(e))
            self.logger.log(f"保存配置时验证失败，未保存。", LogLevel.ERROR)


# === QR Login System ===
class QRLoginSystem:
    def __init__(self, logger: LoggerInterface): # Added logger
        self.logger = logger
        self.base_url = 'http://k8n.cn/weixin/qrlogin/student'
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cache-Control': 'max-age=0',
            'Host': 'k8n.cn',
            'Proxy-Connection': 'keep-alive', # Note: Proxy-Connection is not standard
            'Referer': 'http://k8n.cn/student/login?ref=%2Fstudent',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36' # Updated UA
        }
        self.session = requests.Session()
        self.max_attempts = 20  # Max attempts to check login status
        self.check_interval = 2 # Seconds between checks
        self.classid = None # Stores selected class ID

    def fetch_qr_code_url(self):
        self.logger.log("正在获取二维码链接...", LogLevel.INFO)
        try:
            response = self.session.get(self.base_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=[^"]+'
            match = re.search(pattern, response.text)
            if match:
                qr_code_url = match.group(0)
                self.logger.log("成功获取二维码链接。", LogLevel.INFO)
                return qr_code_url
            else:
                self.logger.log("响应中未找到二维码链接。", LogLevel.ERROR)
                self.logger.log(f"响应内容片段: {response.text[:500]}", LogLevel.DEBUG) # Log part of response for debugging
        except requests.RequestException as e:
            self.logger.log(f"获取二维码链接出错: {e}", LogLevel.ERROR)
        return None

    def display_qr_code(self, qr_code_url):
        self.logger.log("准备显示二维码...", LogLevel.INFO)
        try:
            response = self.session.get(qr_code_url, timeout=10) # Fetch QR image
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            img = img.resize((260, 260), Image.LANCZOS)

            root = tk.Tk()
            root.title("微信登录二维码")
            # Center window on screen
            window_width = 320
            window_height = 400
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            center_x = int(screen_width/2 - window_width / 2)
            center_y = int(screen_height/2 - window_height / 2)
            root.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
            
            root.resizable(False, False)
            root.attributes('-topmost', True) # Keep window on top
            # Ensure it stays on top after a short delay
            root.after(100, lambda: root.attributes('-topmost', True))


            main_frame = tk.Frame(root, padx=20, pady=20)
            main_frame.pack(expand=True, fill=tk.BOTH)

            photo = ImageTk.PhotoImage(img)
            img_frame = tk.Frame(main_frame, bd=2, relief=tk.GROOVE)
            img_frame.pack(pady=(0, 15))
            img_label = tk.Label(img_frame, image=photo)
            img_label.pack(padx=5, pady=5)
            img_label.image = photo # Keep a reference!

            tk.Label(main_frame, text="请使用微信扫描二维码登录", font=("Microsoft YaHei", 12), fg="#333").pack(pady=(0, 10))
            tk.Label(main_frame, text="拖动窗口空白处可移动", font=("Microsoft YaHei", 9), fg="#666").pack()
            
            # --- Make window draggable ---
            # Store initial mouse click position
            root.x_root = 0
            root.y_root = 0

            def start_move(event):
                root.x_root = event.x_root
                root.y_root = event.y_root

            def do_move(event):
                deltax = event.x_root - root.x_root
                deltay = event.y_root - root.y_root
                x = root.winfo_x() + deltax
                y = root.winfo_y() + deltay
                root.geometry(f"+{x}+{y}")
                root.x_root = event.x_root # Update position for next delta
                root.y_root = event.y_root

            # Bind to the main_frame, not the root window itself for better control
            main_frame.bind("<ButtonPress-1>", start_move)
            main_frame.bind("<B1-Motion>", do_move)
            # Also bind to labels if they cover significant area
            for child in main_frame.winfo_children():
                 if isinstance(child, (tk.Label, tk.Frame)): # Bind to frames too
                    child.bind("<ButtonPress-1>", start_move)
                    child.bind("<B1-Motion>", do_move)
                    if isinstance(child, tk.Frame): # Bind recursively for nested frames
                        for sub_child in child.winfo_children():
                             if isinstance(sub_child, tk.Label):
                                sub_child.bind("<ButtonPress-1>", start_move)
                                sub_child.bind("<B1-Motion>", do_move)


            root.after(100, root.focus_force) # Bring window to front
            # Start checking login status, passing the root window to destroy it later
            root.after(0, self.check_login_status, root, 0) 
            root.mainloop()
            return True # Indicates Tkinter window was shown
        except tk.TclError as e: # Handle cases where Tkinter might not be available (e.g. headless server)
            self.logger.log(f"Tkinter显示二维码时出错 (可能无GUI环境): {e}", LogLevel.ERROR)
            self.logger.log(f"请手动复制以下URL到浏览器扫描: {qr_code_url}", LogLevel.INFO)
        except Exception as e:
            self.logger.log(f"显示二维码时发生未知错误: {e}", LogLevel.ERROR)
            self.logger.log(f"请手动复制以下URL到浏览器扫描: {qr_code_url}", LogLevel.INFO)
        return False # QR display failed or Tkinter not used

    def check_login_status(self, root_window, attempt_count):
        if attempt_count >= self.max_attempts:
            self.logger.log("超过最大尝试次数，登录检查失败。", LogLevel.ERROR)
            if root_window: root_window.destroy()
            return False # Indicate failure

        check_url = f"{self.base_url}?op=checklogin"
        try:
            response = self.session.get(check_url, headers=self.headers, timeout=5)
            response.raise_for_status()
            self.logger.log(f"第 {attempt_count + 1} 次检查登录状态，状态码: {response.status_code}", LogLevel.DEBUG)
            
            data = response.json()
            if data.get('status'): # Login successful
                self.logger.log("微信扫码登录成功！", LogLevel.INFO)
                self.handle_successful_login(response, data) # Process cookies and redirect
                if root_window: root_window.destroy()
                return True # Indicate success
            else: # Not logged in yet, or other status
                self.logger.log(f"登录状态检查: {data.get('msg', '未登录或未知状态')}", LogLevel.DEBUG)
        except requests.RequestException as e:
            self.logger.log(f"第 {attempt_count + 1} 次登录检查请求出错: {e}", LogLevel.WARNING)
        except json.JSONDecodeError as e:
            self.logger.log(f"第 {attempt_count + 1} 次登录检查解析JSON出错: {e}", LogLevel.WARNING)
        except Exception as e: # Catch any other unexpected error during check
            self.logger.log(f"第 {attempt_count + 1} 次登录检查发生未知错误: {e}", LogLevel.WARNING)


        # Schedule next check if root_window still exists (i.e., not destroyed by success/failure)
        if root_window and root_window.winfo_exists():
             root_window.after(self.check_interval * 1000, self.check_login_status, root_window, attempt_count + 1)
        elif not root_window: # If called without root_window (e.g. CLI fallback)
            time.sleep(self.check_interval)
            return self.check_login_status(None, attempt_count + 1) # Recursive call for CLI
        return None # Still checking or error occurred, handled by recursion or caller

    def handle_successful_login(self, initial_response, data):
        self.logger.log("处理登录成功后的操作...", LogLevel.DEBUG)
        # Cookies are usually set on the session by requests library automatically
        # but we can explicitly log them if needed or extract specific ones.
        # The crucial cookie is `remember_student_...` which should now be in self.session.cookies

        new_url = data.get('url')
        if not new_url:
            self.logger.log("登录成功响应中未找到跳转URL。", LogLevel.ERROR)
            return
        
        if not new_url.startswith('http'):
            new_url = 'http://k8n.cn' + new_url # Prepend domain if it's a relative path

        self.logger.log(f"登录后跳转至: {new_url}", LogLevel.DEBUG)
        try:
            # Follow the redirect to ensure all necessary session cookies are set
            response = self.session.get(new_url, headers=self.headers, allow_redirects=True, timeout=10)
            response.raise_for_status()
            self.logger.log("登录后跳转请求成功。", LogLevel.DEBUG)
        except requests.RequestException as e:
            self.logger.log(f"登录后跳转请求出错: {e}", LogLevel.ERROR)
        # The session object (self.session) should now contain the necessary cookies.

    def get_scanned_cookie_and_class_id(self) -> Optional[Dict[str, Any]]:
        """
        To be called after successful QR scan and login.
        Fetches student page to get class ID and confirms cookie.
        """
        self.logger.log("获取登录后的学生数据 (班级ID等)...", LogLevel.INFO)
        data_url = 'http://k8n.cn/student' # Student dashboard page
        try:
            response = self.session.get(data_url, headers=self.headers, timeout=10)
            response.raise_for_status()

            # Extract class IDs
            class_ids = self._extract_class_ids_from_html(response.text)
            if not class_ids:
                self.logger.log("在学生页面未找到任何班级信息。", LogLevel.ERROR)
                return None

            self.logger.log(f"找到的班级ID: {class_ids}", LogLevel.DEBUG)

            selected_class_id = ""
            if len(class_ids) == 1:
                selected_class_id = class_ids[0]
                self.logger.log(f"自动选择单个班级ID: {selected_class_id}", LogLevel.INFO)
            else:
                self.logger.log("找到多个班级，请用户选择:", LogLevel.INFO)
                for idx, cid in enumerate(class_ids):
                    print(f"  {idx + 1}. {cid}")
                while True:
                    try:
                        choice = input(f"请输入要使用的班级序号 (1-{len(class_ids)}): ").strip()
                        choice_idx = int(choice) - 1
                        if 0 <= choice_idx < len(class_ids):
                            selected_class_id = class_ids[choice_idx]
                            self.logger.log(f"用户选择的班级ID: {selected_class_id}", LogLevel.INFO)
                            break
                        else:
                            print(f"{Fore.RED}无效的序号，请输入1到{len(class_ids)}之间的数字。{Style.RESET_ALL}")
                    except ValueError:
                        print(f"{Fore.RED}输入无效，请输入数字。{Style.RESET_ALL}")
            
            self.classid = selected_class_id # Store it

            # Extract the required cookie from the session
            scanned_cookie_value = self.session.cookies.get("remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d")
            if not scanned_cookie_value:
                self.logger.log("在session中未找到关键的 'remember_student' Cookie。", LogLevel.ERROR)
                return None
            
            full_cookie_string = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={scanned_cookie_value}"
            self.logger.log("成功获取Cookie和班级ID。", LogLevel.INFO)
            return {
                "cookie": full_cookie_string,
                "class_id": selected_class_id
            }

        except requests.RequestException as e:
            self.logger.log(f"获取学生数据出错: {e}", LogLevel.ERROR)
        except Exception as e:
            self.logger.log(f"处理学生数据时发生未知错误: {e}", LogLevel.ERROR)
        return None

    def _extract_class_ids_from_html(self, html_content: str) -> List[str]:
        """Extracts class IDs from the student dashboard HTML."""
        soup = BeautifulSoup(html_content, 'html.parser')
        # Look for elements that typically contain course/class IDs.
        # This might need adjustment if the website structure changes.
        # Example: <div class="course-item" data-course-id="12345">...</div>
        # Or: <a href="/student/course/12345/details">...</a>
        
        # Try finding by 'course_id' attribute as in original code
        ids_from_attr = [div.get('course_id') for div in soup.find_all('div', class_=re.compile(r'\bcourse\b', re.I)) if div.get('course_id')] # Case-insensitive class search
        if ids_from_attr:
            return list(set(ids_from_attr)) # Return unique IDs

        # Fallback: Try extracting from URLs like '/student/course/ID/...'
        ids_from_href = []
        for a_tag in soup.find_all('a', href=True):
            match = re.search(r'/student/course/(\d+)', a_tag['href'])
            if match:
                ids_from_href.append(match.group(1))
        
        if ids_from_href:
            return list(set(ids_from_href))

        self.logger.log("在HTML中未找到班级ID的已知模式。", LogLevel.WARNING)
        return []


# === Configuration Updater (Interactive Setup) ===
class ConfigUpdater:
    def __init__(self, config_manager: ConfigManager, logger: LoggerInterface):
        self.manager = config_manager
        self.logger = logger
        self.login_system = QRLoginSystem(logger) # Pass logger
        self.scanned_data: Optional[Dict[str, str]] = None # To store {'cookie': ..., 'class_id': ...}

    def init_config(self) -> Dict[str, Any]:
        """Handles initial configuration, prompting user if necessary."""
        if not self.manager.config or not self._validate_current_config_quietly():
            self.logger.log("本地配置无效或首次运行，进入配置向导。", LogLevel.INFO)
            return self._first_run_config_wizard()
        
        self._show_current_config()
        if self._should_update_config_interactively():
            return self._update_config_interactively()
        
        self.logger.log("使用现有本地配置。", LogLevel.INFO)
        return self.manager.config

    def _validate_current_config_quietly(self) -> bool:
        """Validates current config without logging errors to console during init check."""
        if not self.manager.config: return False
        try:
            ConfigModel(**self.manager.config)
            return True
        except ValidationError:
            return False

    def _first_run_config_wizard(self) -> Dict[str, Any]:
        self.logger.log(f"\n{Fore.GREEN}🌟 欢迎使用自动签到系统 {SCRIPT_VERSION} 🌟{Style.RESET_ALL}", LogLevel.INFO) # Use logger for consistent output
        self.logger.log(f"{Fore.YELLOW}首次运行或配置损坏，需要进行初始配置。{Style.RESET_ALL}", LogLevel.INFO)
        print("="*60) # Keep visual separator for wizard
        
        new_config_data: Dict[str, Any] = {}

        # Step 1: Login Method (Cookie & Class ID)
        self._setup_login_credentials(new_config_data)
        if not new_config_data.get("cookie") or not new_config_data.get("class_id"):
            self.logger.log("未能获取Cookie或班级ID，配置中止。", LogLevel.CRITICAL)
            application_run_event.clear() # Stop application
            sys.exit(1)

        # Step 2: Location Info
        self._setup_location_info(new_config_data)
        if not all(k in new_config_data for k in ("lat", "lng", "acc")):
             self.logger.log("未能获取完整位置信息，配置中止。", LogLevel.CRITICAL)
             application_run_event.clear()
             sys.exit(1)

        # Step 3: Other Settings (time, pushplus, remark, time_range)
        self._setup_other_settings(new_config_data)

        try:
            validated_config = ConfigModel(**new_config_data).model_dump()
            self.manager.config = validated_config # Update manager's internal config
            self.manager.save() # Save to file
            self.logger.log(f"\n{Fore.GREEN}✅ 初始配置完成并已保存！{Style.RESET_ALL}", LogLevel.INFO)
            return validated_config
        except ValidationError as e:
            self._handle_pydantic_validation_error(e)
            self.logger.log("配置数据无效，请重新尝试。", LogLevel.ERROR)
            return self._first_run_config_wizard() # Recursive call on validation failure

    def _setup_login_credentials(self, config_data_dict: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.CYAN}=== 第一步：登录凭证设置 ==={Style.RESET_ALL}", LogLevel.INFO)
        print("请选择获取Cookie和班级ID的方式：")
        print(f"1. {Fore.GREEN}微信扫码登录 (推荐){Style.RESET_ALL}")
        print("2. 手动输入Cookie和班级ID")
        
        while True:
            choice = input("请选择 (1/2, 默认1): ").strip() or "1"
            if choice == "1":
                if self._perform_qr_scan_for_credentials(): # Sets self.scanned_data
                    if self.scanned_data:
                        config_data_dict["cookie"] = self.scanned_data["cookie"]
                        config_data_dict["class_id"] = self.scanned_data["class_id"]
                        return # Success
                    else:
                        self.logger.log("扫码登录过程未成功获取凭证，请重试或选择手动输入。", LogLevel.WARNING)
                else: # QR scan process itself failed (e.g., couldn't show QR)
                    self.logger.log("扫码登录流程启动失败，请尝试手动输入。", LogLevel.WARNING)
            elif choice == "2":
                self._manual_input_credentials(config_data_dict)
                return # Assume manual input handles its own validation for now
            else:
                print(f"{Fore.RED}无效输入，请输入1或2。{Style.RESET_ALL}")

    def _perform_qr_scan_for_credentials(self) -> bool:
        """Attempts QR scan and updates self.scanned_data."""
        self.scanned_data = None
        for attempt in range(1, 4): # Max 3 attempts for QR process
            self.logger.log(f"\n🔄 尝试获取二维码 (第 {attempt} 次)...", LogLevel.INFO)
            qr_url = self.login_system.fetch_qr_code_url()
            if not qr_url:
                self.logger.log("无法获取二维码URL。", LogLevel.WARNING)
                if attempt < 3 and (input("获取二维码失败，是否重试? (y/n, 默认y): ").strip().lower() or 'y') != 'y': break
                continue

            if not self.login_system.display_qr_code(qr_url): # This blocks until QR window is closed or login status check finishes
                self.logger.log("二维码窗口未能成功显示或被用户关闭。", LogLevel.WARNING)
                # display_qr_code itself logs if it falls back to URL
                if attempt < 3 and (input("二维码显示/扫描过程未完成，是否重试? (y/n, 默认y): ").strip().lower() or 'y') != 'y': break
                continue
            
            # After display_qr_code returns, check_login_status should have run.
            # Now, try to get the cookie and class_id.
            scanned_info = self.login_system.get_scanned_cookie_and_class_id()
            if scanned_info and scanned_info.get("cookie") and scanned_info.get("class_id"):
                self.scanned_data = scanned_info
                self.logger.log(f"✅ 扫码登录成功！获取到班级ID: {self.scanned_data['class_id']}", LogLevel.INFO)
                cookie_preview = self.scanned_data['cookie']
                if len(cookie_preview) > 40: cookie_preview = f"{cookie_preview[:20]}...{cookie_preview[-20:]}"
                self.logger.log(f"获取到的Cookie (部分): {cookie_preview}", LogLevel.DEBUG)
                return True
            else: # Login might have succeeded but data extraction failed
                self.logger.log("扫码登录后未能提取Cookie或班级ID。", LogLevel.WARNING)
                if attempt < 3 and (input("扫码后数据提取失败，是否重试整个扫码流程? (y/n, 默认y): ").strip().lower() or 'y') != 'y': break
        
        self.logger.log("扫码登录获取凭证失败。", LogLevel.ERROR)
        return False

    def _manual_input_credentials(self, config_data_dict: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.YELLOW}⚠️ 请手动输入必要信息{Style.RESET_ALL}", LogLevel.INFO)
        config_data_dict["cookie"] = self._get_validated_input("请输入Cookie: ", ConfigModel.validate_cookie)
        config_data_dict["class_id"] = self._get_validated_input("请输入班级ID: ", ConfigModel.validate_class_id)

    def _get_validated_input(self, prompt: str, validator: Callable, default_value: Optional[str] = None, current_value_for_update: Optional[str] = None) -> str:
        prompt_suffix = ""
        if current_value_for_update is not None: # For updates
            display_current = current_value_for_update
            if "cookie" in prompt.lower() and len(display_current) > 30:
                 display_current = f"{display_current[:15]}...{display_current[-15:]}"
            prompt_suffix = f" (当前: {display_current}, 直接回车不修改): "
        elif default_value is not None: # For initial setup with defaults
            prompt_suffix = f" (默认: {default_value}, 直接回车使用默认值): "
        else: # Required input
            prompt_suffix = ": "
            
        while True:
            try:
                user_input = input(prompt + prompt_suffix).strip()
                if current_value_for_update is not None and not user_input: # Updating, user pressed Enter
                    return current_value_for_update # Return original value
                if default_value is not None and not user_input: # Initial setup, user pressed Enter for default
                    value_to_validate = default_value
                else:
                    value_to_validate = user_input
                
                if not value_to_validate and default_value is None and current_value_for_update is None: # Required field is empty
                     raise ValueError("该字段为必填项。")

                return validator(value_to_validate) # Validate the chosen value
            except ValueError as e: # Catches validation errors from Pydantic validators
                print(f"{Fore.RED}输入错误: {e}{Style.RESET_ALL}")
            except Exception as e: # Catch other unexpected errors during input
                print(f"{Fore.RED}发生未知输入错误: {e}{Style.RESET_ALL}")


    def _setup_location_info(self, config_data_dict: Dict[str, Any], is_update: bool = False) -> None:
        current_config = self.manager.config if is_update else {}
        self.logger.log(f"\n{Fore.CYAN}=== {'更新' if is_update else '设置'}位置信息 ==={Style.RESET_ALL}", LogLevel.INFO)
        if not is_update: print("请提供您常用的签到位置坐标：")
        
        config_data_dict["lat"] = self._get_validated_input(
            "请输入纬度 (例如 39.9042)", ConfigModel.validate_latitude, 
            current_value_for_update=current_config.get("lat") if is_update else None)
        config_data_dict["lng"] = self._get_validated_input(
            "请输入经度 (例如 116.4074)", ConfigModel.validate_longitude,
            current_value_for_update=current_config.get("lng") if is_update else None)
        config_data_dict["acc"] = self._get_validated_input( # Accuracy
            "请输入签到精度 (例如 20.0)", ConfigModel.validate_accuracy, # Changed prompt
            current_value_for_update=current_config.get("acc") if is_update else None)


    def _setup_other_settings(self, config_data_dict: Dict[str, Any], is_update: bool = False) -> None:
        current_config = self.manager.config if is_update else {}
        self.logger.log(f"\n{Fore.CYAN}=== {'更新' if is_update else '设置'}其他选项 ==={Style.RESET_ALL}", LogLevel.INFO)

        # Search interval
        default_time = str(AppConstants.DEFAULT_SEARCH_INTERVAL)
        config_data_dict["time"] = int(self._get_validated_input(
            "请输入检查间隔 (秒)", 
            lambda v: str(ConfigModel.validate_search_time(v)), # Validator needs to return str for _get_validated_input
            default_value=default_time if not is_update else None,
            current_value_for_update=str(current_config.get("time", default_time)) if is_update else None
        ))

        # PushPlus
        config_data_dict["pushplus"] = self._get_validated_input(
            "请输入PushPlus令牌 (可选)", lambda v: v, # No specific validation, just return as is
            default_value="" if not is_update else None,
            current_value_for_update=current_config.get("pushplus", "") if is_update else None
        )
        
        # Remark
        default_remark = "自动签到配置"
        config_data_dict["remark"] = self._get_validated_input(
            "请输入备注信息 (可选)", lambda v: v or default_remark,
            default_value=default_remark if not is_update else None,
            current_value_for_update=current_config.get("remark", default_remark) if is_update else None
        ) or default_remark # Ensure it's not empty if user just hits enter

        # Time range
        self._setup_time_range_config(config_data_dict, is_update)


    def _setup_time_range_config(self, config_data_dict: Dict[str, Any], is_update: bool = False) -> None:
        current_config = self.manager.config if is_update else AppConstants.DEFAULT_RUN_TIME
        
        current_enabled_str = 'y' if current_config.get('enable_time_range') else 'n'
        enable_choice_prompt = "是否启用时间段控制? (y/n"
        if is_update:
            enable_choice_prompt += f", 当前: {'是' if current_enabled_str == 'y' else '否'}, 直接回车不修改): "
        else:
            enable_choice_prompt += f", 默认: {'否' if AppConstants.DEFAULT_RUN_TIME['enable_time_range'] else '是'}): " # Default based on AppConstants

        enable_input = input(enable_choice_prompt).strip().lower()
        
        if is_update and not enable_input: # User pressed Enter during update
            config_data_dict["enable_time_range"] = current_config.get('enable_time_range', False)
        elif not enable_input and not is_update: # User pressed Enter during initial setup
             config_data_dict["enable_time_range"] = AppConstants.DEFAULT_RUN_TIME['enable_time_range']
        else:
            config_data_dict["enable_time_range"] = (enable_input == 'y')

        if config_data_dict["enable_time_range"]:
            self.logger.log("请设置运行时间段 (格式 HH:MM)。", LogLevel.INFO)
            while True:
                try:
                    start_time_val = self._get_validated_input(
                        "开始时间", ConfigModel.validate_time_format,
                        default_value=AppConstants.DEFAULT_RUN_TIME['start_time'] if not is_update else None,
                        current_value_for_update=current_config.get("start_time") if is_update else None)
                    
                    end_time_val = self._get_validated_input(
                        "结束时间", ConfigModel.validate_time_format,
                        default_value=AppConstants.DEFAULT_RUN_TIME['end_time'] if not is_update else None,
                        current_value_for_update=current_config.get("end_time") if is_update else None)

                    if datetime.strptime(start_time_val, '%H:%M') >= datetime.strptime(end_time_val, '%H:%M'):
                        raise ValueError("开始时间必须早于结束时间。")
                    
                    config_data_dict["start_time"] = start_time_val
                    config_data_dict["end_time"] = end_time_val
                    break
                except ValueError as e:
                    print(f"{Fore.RED}时间设置错误: {e}{Style.RESET_ALL}")
        else: # If disabled, ensure default/current times are set if not already
            config_data_dict["start_time"] = current_config.get("start_time", AppConstants.DEFAULT_RUN_TIME['start_time'])
            config_data_dict["end_time"] = current_config.get("end_time", AppConstants.DEFAULT_RUN_TIME['end_time'])


    def _show_current_config(self) -> None:
        config = self.manager.config
        if not config:
            self.logger.log("当前无有效本地配置可显示。", LogLevel.WARNING)
            return

        self.logger.log("\n📋 当前本地配置信息:", LogLevel.INFO)
        print("--------------------------------")
        
        cookie_display = config.get("cookie", "未设置")
        if len(cookie_display) > 30 and cookie_display != "未设置":
            cookie_display = f"{cookie_display[:15]}...{cookie_display[-15:]}"
        
        items_to_display = [
            ("Cookie", cookie_display),
            ("班级ID", config.get("class_id", "未设置")),
            ("纬度", config.get("lat", "未设置")),
            ("经度", config.get("lng", "未设置")),
            ("精度", config.get("acc", "未设置")),
            ("检查间隔", f"{config.get('time', 'N/A')} 秒"),
            ("PushPlus令牌", config.get("pushplus") or "未设置"),
            ("备注", config.get("remark", "未设置")),
            ("时间段控制", "已启用" if config.get("enable_time_range") else "已禁用")
        ]
        if config.get("enable_time_range"):
            items_to_display.append(("运行时间段", f"{config.get('start_time','N/A')} 至 {config.get('end_time','N/A')}"))

        for name, value in items_to_display:
            print(f"🔹 {name.ljust(12)}: {value}")
        print("--------------------------------")

    def _should_update_config_interactively(self) -> bool:
        print("\n是否要修改当前本地配置? (y/n, 默认n, 10秒后自动选n): ", end='', flush=True)
        
        user_input_container = ['n'] # Use a list to allow modification in thread
        input_event = threading.Event()

        def get_input_with_timeout():
            try:
                # This will block until input or timeout in input_thread.join
                val = sys.stdin.readline().strip().lower()
                if val: # Only update if user actually typed something
                    user_input_container[0] = val
            except Exception: # Handle potential errors with stdin in a thread
                pass # Keep default 'n'
            finally:
                input_event.set() # Signal that input attempt is done

        input_thread = threading.Thread(target=get_input_with_timeout)
        input_thread.daemon = True
        input_thread.start()
        
        input_event.wait(timeout=10) # Wait for event or timeout

        if not input_event.is_set(): # Timeout occurred
            print(f"\n{Fore.YELLOW}输入超时，自动选择 'n'。{Style.RESET_ALL}")
            # Attempt to interrupt stdin, though this is platform-dependent and tricky
            # For simplicity, we'll just proceed with 'n'
        else: # Input was received (or thread finished for other reasons)
             print() # Add a newline after user input or if they just hit enter.

        return user_input_container[0] == 'y'

    def _update_config_interactively(self) -> Dict[str, Any]:
        self.logger.log("进入交互式配置更新模式...", LogLevel.INFO)
        # Make a deep copy to modify, and revert if user cancels
        temp_config = deepcopy(self.manager.config)
        original_config_backup = deepcopy(self.manager.config) # For full revert

        while True:
            self._show_current_config() # Show config before asking what to change
            print("\n🔧 请选择要修改的配置项:")
            print("1. 登录凭证 (Cookie 和 班级ID) - 将通过扫码或手动重新设置")
            print("2. 位置信息 (纬度/经度/精度)")
            print("3. 其他设置 (检查间隔/PushPlus/备注/运行时间段)")
            print("0. 完成修改并保存")
            print("c. 取消修改并恢复原始配置")

            choice = input("请输入选项 (0-3, c): ").strip().lower()

            if choice == "1":
                self.logger.log("选择更新登录凭证...", LogLevel.INFO)
                self._setup_login_credentials(temp_config) # Updates temp_config directly
            elif choice == "2":
                self.logger.log("选择更新位置信息...", LogLevel.INFO)
                self._setup_location_info(temp_config, is_update=True)
            elif choice == "3":
                self.logger.log("选择更新其他设置...", LogLevel.INFO)
                self._setup_other_settings(temp_config, is_update=True)
            elif choice == "0":
                try:
                    ConfigModel(**temp_config) # Validate before proposing save
                    self.manager.config = temp_config # Commit changes to manager
                    self.manager.save() # Save to file
                    self.logger.log("✅ 配置已成功更新并保存。", LogLevel.INFO)
                    return self.manager.config
                except ValidationError as e:
                    self._handle_pydantic_validation_error(e)
                    self.logger.log("更新后的配置无效，请修正或取消。", LogLevel.ERROR)
                    # Do not revert temp_config here, let user fix or cancel
            elif choice == 'c':
                self.manager.config = original_config_backup # Restore original
                self.logger.log("修改已取消，配置已恢复到更新前状态。", LogLevel.INFO)
                return self.manager.config # Return original unchanged config
            else:
                print(f"{Fore.RED}无效选项，请重新输入。{Style.RESET_ALL}")
        
    def _handle_pydantic_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"  - {err['loc'][0] if err['loc'] else 'Unknown field'}: {err['msg']}" for err in error.errors()]
        self.logger.log("配置数据验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)


# === Sign Task ===
class SignTask:
    def __init__(self, 
                 config: Dict[str, Any], 
                 logger: LoggerInterface, 
                 run_event: threading.Event,
                 remote_config_mgr: RemoteConfigManager,
                 device_id_str: str
                 ):
        self.config = config # This is the local config from data.json
        self.logger = logger
        self.application_run_event = run_event
        self.remote_config_manager = remote_config_mgr
        self.device_id = device_id_str

        self.invalid_sign_ids: Set[str] = set() # IDs that require password, etc.
        self.signed_ids: Set[str] = set()       # IDs successfully signed or already signed
        
        self._user_requested_stop = False # For 'q' command from user
        self._control_thread: Optional[threading.Thread] = None

    def _should_application_run(self) -> bool:
        """Checks all conditions for the application to continue running."""
        if not self.application_run_event.is_set():
            self.logger.log("Application run event is not set, SignTask stopping.", LogLevel.INFO)
            return False
        if self._user_requested_stop:
            self.logger.log("User requested stop, SignTask stopping.", LogLevel.INFO)
            return False
        
        # Check dynamic remote config for disables
        if self.remote_config_manager.is_globally_disabled():
            self.logger.log("远程配置: 全局禁用已激活，签到任务停止。", LogLevel.CRITICAL)
            self.application_run_event.clear() # Signal all parts of app to stop
            return False
        if not self.remote_config_manager.is_device_allowed(self.device_id):
            self.logger.log(f"远程配置: 设备 {self.device_id} 被禁用，签到任务停止。", LogLevel.CRITICAL)
            self.application_run_event.clear()
            return False
        return True

    def run(self) -> None:
        self._setup_control_thread()
        
        try:
            while self._should_application_run():
                # Log announcement if any
                announcement = self.remote_config_manager.get_announcement()
                if announcement:
                    self.logger.log(f"[公告] {announcement['message']}", LogLevel.INFO)

                if self._is_within_time_range():
                    self._execute_sign_cycle()
                else:
                    self._log_waiting_for_time_range()
                
                self._wait_for_next_cycle()
        except KeyboardInterrupt:
            self.logger.log("用户中断程序 (Ctrl+C)。", LogLevel.INFO)
            self.application_run_event.clear() # Signal shutdown
        finally:
            self.logger.log("签到任务主循环结束。", LogLevel.INFO)
            if not self._user_requested_stop: # If not stopped by user 'q' command
                 self.application_run_event.clear() # Ensure it's cleared on other exits
            self._cleanup_control_thread()

    def _is_within_time_range(self) -> bool:
        if not self.config.get('enable_time_range', False):
            return True 
        try:
            now_time = datetime.now().time()
            start_time = datetime.strptime(self.config.get('start_time', '00:00'), '%H:%M').time()
            end_time = datetime.strptime(self.config.get('end_time', '23:59'), '%H:%M').time()
            
            if start_time <= end_time: # Normal range, e.g., 08:00-22:00
                return start_time <= now_time <= end_time
            else: # Overnight range, e.g., 22:00-06:00
                return now_time >= start_time or now_time <= end_time
        except ValueError:
            self.logger.log("时间范围配置格式错误，默认允许运行。", LogLevel.WARNING)
            return True # Fail open

    def _log_waiting_for_time_range(self) -> None:
        current_time_str = datetime.now().strftime('%H:%M:%S')
        start_str = self.config.get('start_time', 'N/A')
        end_str = self.config.get('end_time', 'N/A')
        self.logger.log(
            f"⏳ 当前时间 {current_time_str} 不在运行时间段 ({start_str}-{end_str}) 内，等待中...",
            LogLevel.DEBUG 
        )

    def _setup_control_thread(self):
        self._control_thread = threading.Thread(target=self._monitor_commands, daemon=True)
        self._control_thread.start()

    def _monitor_commands(self):
        time.sleep(1) 

        # 安全打印提示符的函数
        def print_prompt():
            if sys.stdin.isatty() and self.application_run_event.is_set() and not self._user_requested_stop:
                # 在提示符前添加换行符有助于将其与之前的日志输出分开
                # 使用蓝色以更好地区分提示符
                print(f"\n{Fore.BLUE}(输入命令: q=退出, s=立即签到, c=检查状态, conf=修改配置):{Style.RESET_ALL} ", end='', flush=True)

        print_prompt() # 打印初始提示符

        while self.application_run_event.is_set() and not self._user_requested_stop:
            try:
                cmd_container = [""] 
                cmd_thread_finished_event = threading.Event() # 修改处: 使用事件进行通知 (MODIFIED: Use event for signaling)

                def get_cmd_input():
                    try:
                        cmd_container[0] = sys.stdin.readline().strip().lower()
                    except EOFError: # 文件结束错误 (通常由 Ctrl+D 或输入重定向结束引起)
                        cmd_container[0] = "EOF" 
                    except Exception: # 其他可能的输入错误
                        cmd_container[0] = "ERROR" 
                    finally:
                        cmd_thread_finished_event.set() # 修改处: 通知完成 (MODIFIED: Signal completion)

                cmd_thread = threading.Thread(target=get_cmd_input)
                cmd_thread.daemon = True 
                cmd_thread.start()

                # 带超时的等待输入，或直到应用程序停止
                # 等待较短时间以使循环对 application_run_event 更敏感
                input_received_in_time = cmd_thread_finished_event.wait(timeout=1.0) # 修改处: 等待事件 (MODIFIED: Wait on event)

                # 等待后检查停止条件
                if not self.application_run_event.is_set() or self._user_requested_stop:
                    if cmd_thread.is_alive(): # 如果可能，尝试“轻推” readline 以使其退出
                        # 这很棘手且依赖于平台；通常 readline 会强阻塞。
                        # 目前，我们依赖守护线程的属性进行清理。
                        pass
                    break

                if input_received_in_time: # 已接收到输入 (或 EOF/Error)
                    cmd_thread.join() # 确保线程资源得到清理
                    cmd = cmd_container[0]

                    if cmd == "EOF":
                        self.logger.log("输入流结束，控制线程退出。", LogLevel.INFO)
                        self._user_requested_stop = True 
                        self.application_run_event.clear()
                        break 
                    elif cmd == "ERROR":
                        self.logger.log("读取命令输入时发生错误。", LogLevel.ERROR)
                        # 没有特定的命令需要处理，循环将继续
                        print_prompt() # 出错后重新打印提示符
                        continue # 继续下一次循环
                    elif cmd: # 命令非空
                        # 如果可能，清除用户输入命令的那一行和旧提示符
                        # 这是为了使输出更整洁。
                        # \r 将光标移到行首，ANSI 转义序列 \033[K 清除从光标到行尾的内容。
                        if sys.stdin.isatty(): print("\r\033[K", end='') 

                        if cmd == 'q':
                            self.logger.log("用户请求退出...", LogLevel.INFO)
                            self._user_requested_stop = True
                            self.application_run_event.clear()
                            break    
                        elif cmd == 's':    
                            self.logger.log("用户请求立即执行签到检查...", LogLevel.INFO)
                            if self._should_application_run(): 
                                if self._is_within_time_range():
                                    self._execute_sign_cycle()
                                else:
                                    self._log_waiting_for_time_range()
                                    self.logger.log("无法立即签到：不在设定时间范围内。", LogLevel.WARNING)
                            else:
                                self.logger.log("应用程序当前不允许运行，无法执行立即签到。", LogLevel.WARNING)
                        elif cmd == 'c':
                            self._show_status()
                        elif cmd == 'conf':
                            self.logger.log("用户请求修改配置...", LogLevel.INFO)
                            print("配置修改功能需重启程序以通过配置向导进行，或按 'q' 退出后重新运行脚本。")
                        else: 
                            # \r\033[K 清除当前行后打印未知命令消息
                            print(f"\r\033[K{Fore.YELLOW}⚠️ 未知命令 '{cmd}'. 可用: q, s, c, conf{Style.RESET_ALL}")
                        
                        print_prompt() # 处理完一个命令后重新打印提示符
                    else: # 空输入 (用户只按了回车)
                        if sys.stdin.isatty(): print("\r\033[K", end='') # 清除该行
                        print_prompt() # 重新打印提示符
                # else: # 超时发生，尚未收到输入。循环继续，并将再次调用 wait()。
                      # 此处无需重新打印提示符，因为没有用户交互发生。
                      # 循环将检查 application_run_event，然后再次等待。

            except KeyboardInterrupt: # 用户按下了 Ctrl+C
                self.logger.log("控制线程检测到中断 (Ctrl+C)。", LogLevel.INFO)
                self._user_requested_stop = True
                self.application_run_event.clear()
                break
            except Exception as e:
                self.logger.log(f"命令监控线程出错: {e}", LogLevel.ERROR)
                # 如果输入循环中发生意外错误，暂停后重新打印提示符
                time.sleep(1)
                if self.application_run_event.is_set() and not self._user_requested_stop:
                     print_prompt()


    def _show_status(self):
        print("\n") # 新增 (ADDED)
        # Make sure to use self.config for local settings and remote_config_manager for remote ones
        print(f"\n{Fore.CYAN}=== 当前状态 ==={Style.RESET_ALL}")
        print(f"Script Version: {SCRIPT_VERSION}")
        print(f"Device ID: {self.device_id}")
        print(f"签到任务运行中: {'是' if self._should_application_run() else '否'}")
        
        print(f"\n--- 本地配置 ({AppConstants.CONFIG_FILE}) ---")
        print(f"班级ID: {self.config.get('class_id', 'N/A')}")
        print(f"检查间隔: {self.config.get('time', 'N/A')} 秒")
        if self.config.get('enable_time_range'):
            print(f"运行时间段: {self.config.get('start_time','N/A')} - {self.config.get('end_time','N/A')}")
        else:
            print("运行时间段: 全天候")
        
        print(f"\n--- 远程配置状态 ---")
        print(f"全局禁用: {'是' if self.remote_config_manager.is_globally_disabled() else '否'}")
        print(f"此设备允许运行: {'是' if self.remote_config_manager.is_device_allowed(self.device_id) else '否'}")
        forced_version = self.remote_config_manager.get_forced_update_below_version()
        print(f"强制更新版本 (低于此版本需更新): {forced_version if forced_version != '0.0.0' else '未设置'}")
        ann = self.remote_config_manager.get_announcement()
        print(f"当前公告: {ann['message'] if ann else '无'}")
        
        print(f"\n--- 签到记录 ---")
        print(f"✅ 已签到/处理过的ID: {self.signed_ids if self.signed_ids else '无'}")
        print(f"❌ 本轮忽略的无效ID (如需密码): {self.invalid_sign_ids if self.invalid_sign_ids else '无'}")
        
        next_check_estimate = datetime.now() + timedelta(seconds=self.config.get('time', AppConstants.DEFAULT_SEARCH_INTERVAL))
        print(f"⏱️ 下次自动检查预估: {next_check_estimate.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*20)


    def _cleanup_control_thread(self):
        if self._control_thread and self._control_thread.is_alive():
            self.logger.log("等待控制线程结束...", LogLevel.DEBUG)
            self._control_thread.join(timeout=2) # Give it a moment to exit
            if self._control_thread.is_alive():
                 self.logger.log("控制线程未能干净退出。", LogLevel.WARNING)


    def _execute_sign_cycle(self) -> None:
        if not self._should_application_run(): # Re-check before execution
            return

        self.logger.log(f"\n🔍 开始检索签到任务 (班级ID: {self.config['class_id']})", LogLevel.INFO)
        
        try:
            sign_ids_to_process = self._fetch_sign_ids()
            if not sign_ids_to_process:
                self.logger.log("本次未找到有效或新的签到任务。", LogLevel.INFO)
                return

            active_tasks_found = False
            for sign_id in sign_ids_to_process:
                if not self._should_application_run(): break # Check before processing each ID

                if not sign_id.isdigit():
                    self.logger.log(f"跳过无效格式的签到ID: {sign_id}", LogLevel.WARNING)
                    continue
                
                if sign_id in self.invalid_sign_ids: # Persists across cycles for current run
                    self.logger.log(f"跳过先前标记为无效的签到ID: {sign_id}", LogLevel.DEBUG)
                    continue
                
                if sign_id in self.signed_ids: # Persists across cycles
                    self.logger.log(f"跳过已签到或处理过的ID: {sign_id}", LogLevel.DEBUG)
                    continue
                
                active_tasks_found = True
                self.logger.log(f"处理新签到ID: {sign_id}", LogLevel.INFO)
                self._attempt_sign(sign_id)
            
            if not active_tasks_found and sign_ids_to_process : # Found IDs but all were already processed/invalid
                 self.logger.log("找到的签到任务均已处理或标记为无效。", LogLevel.INFO)


        except requests.RequestException as e:
            self.logger.log(f"网络请求出错 (获取签到列表): {e}", LogLevel.ERROR)
        except Exception as e:
            self.logger.log(f"执行签到周期时发生未知错误: {e}", LogLevel.ERROR)


    def _fetch_sign_ids(self) -> List[str]:
        url = f'http://k8n.cn/student/course/{self.config["class_id"]}/punchs'
        headers = self._build_headers()
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # Will raise HTTPError for bad responses (4xx or 5xx)

        self.logger.log(f"获取签到列表响应状态码: {response.status_code}", LogLevel.DEBUG)
        
        # Regex to find punch_gps(ID) or punchcard_ID (common patterns for sign-in links/buttons)
        # This pattern looks for digits within parentheses after 'punch_gps' or digits after 'punchcard_'
        pattern = r'punch_gps\((\d+)\)|punchcard_(\d+)' 
        matches = re.findall(pattern, response.text)
        
        # matches will be a list of tuples, e.g., [('123', ''), ('', '456')]
        # We need to extract the non-empty group from each tuple
        extracted_ids = [group for match_tuple in matches for group in match_tuple if group]
        
        unique_ids = list(set(extracted_ids)) # Remove duplicates
        if unique_ids:
            self.logger.log(f"从页面提取到的签到ID: {unique_ids}", LogLevel.DEBUG)
        return unique_ids


    def _attempt_sign(self, sign_id: str) -> None:
        # Construct the URL for attempting the sign-in for a specific ID
        # This might vary based on whether it's GPS punch or another type,
        # but often the system handles it via the same endpoint.
        url = f'http://k8n.cn/student/punchs/course/{self.config["class_id"]}/{sign_id}'
        headers = self._build_headers()
        payload = {
            'id': sign_id, # The specific sign-in task ID
            'lat': self.config["lat"],
            'lng': self.config["lng"],
            'acc': self.config["acc"], # Accuracy
            'res': '',       # Typically empty, might be for address resolution if provided
            'gps_addr': ''   # GPS address string, if available
        }
        
        max_retries = 2 # Max retries for a single sign-in attempt
        for attempt in range(1, max_retries + 1):
            if not self._should_application_run(): return

            self.logger.log(f"尝试签到ID {sign_id} (尝试 {attempt}/{max_retries})...", LogLevel.DEBUG)
            try:
                response = requests.post(url, headers=headers, data=payload, timeout=15)
                response.raise_for_status()
                
                if not response.text.strip(): # Check for empty response
                    self.logger.log(f"签到ID {sign_id} 响应为空。", LogLevel.WARNING)
                    if attempt < max_retries: time.sleep(3); continue
                    else: break # Failed after retries

                self._handle_sign_response(response.text, sign_id)
                return # Successfully handled or decided to ignore this ID

            except requests.RequestException as e:
                self.logger.log(f"签到ID {sign_id} 请求出错 (尝试 {attempt}): {e}", LogLevel.ERROR)
                if attempt < max_retries:
                    time.sleep(5 * attempt) # Basic backoff
                else:
                    self.logger.log(f"达到最大重试次数，放弃签到ID {sign_id} 本轮尝试。", LogLevel.ERROR)
            except Exception as e: # Catch-all for unexpected errors during sign attempt
                self.logger.log(f"处理签到ID {sign_id} 时发生未知错误: {e}", LogLevel.ERROR)
                break # Stop trying for this ID if an unknown error occurs

    def _handle_sign_response(self, html_response: str, sign_id: str) -> None:
        soup = BeautifulSoup(html_response, 'html.parser')
        
        # Try to find a title or message element that indicates status
        # Common patterns: <div id="title">Message</div> or <div class="weui-msg__title">Message</div>
        title_tag = soup.find('div', id='title')
        if not title_tag: # Fallback to another common pattern
            title_tag = soup.find('div', class_='weui-msg__title') 
        
        result_message = "未能解析签到响应"
        if title_tag:
            result_message = title_tag.text.strip()
        else: # If no title tag, look for any prominent text, e.g., in a body paragraph
            body_text_tags = soup.find_all(['p', 'h1', 'h2', 'h3', 'div'], class_=lambda x: not x or 'button' not in x.lower()) # Avoid button text
            # Concatenate text from a few prominent tags if no specific title found
            candidate_messages = [tag.text.strip() for tag in body_text_tags if tag.text.strip()]
            if candidate_messages:
                result_message = ". ".join(list(set(candidate_messages[:3]))) # Join first few unique messages
            self.logger.log(f"无法找到标准标题标签，解析到的响应文本片段: '{result_message[:100]}...'", LogLevel.DEBUG)


        self.logger.log(f"签到ID {sign_id} 的响应消息: '{result_message}'", LogLevel.INFO)

        # Check for specific keywords in the message
        if "密码错误" in result_message or "请输入密码" in result_message:
            self.logger.log(f"签到ID {sign_id} 需要密码，标记为无效并不再尝试。", LogLevel.WARNING)
            self.invalid_sign_ids.add(sign_id)
            self._send_notification(f"签到失败 (ID: {sign_id}): 需要密码 - {result_message}", is_success=False)
        elif "已签到过啦" in result_message or "您已签到" in result_message or "签过啦" in result_message:
            self.logger.log(f"签到ID {sign_id} 已签到过。", LogLevel.INFO)
            self.signed_ids.add(sign_id)
            # Optionally send notification for already signed, or just log it.
            # self._send_notification(f"签到提醒 (ID: {sign_id}): 您已签到过 - {result_message}", is_success=True)
        elif "成功" in result_message: # General success keyword
            self.logger.log(f"✅ 签到ID {sign_id} 成功!", LogLevel.INFO)
            self.signed_ids.add(sign_id)
            self._send_notification(f"签到成功 (ID: {sign_id}): {result_message}", is_success=True)
        else: # Other messages, potentially failure or unknown status
            self.logger.log(f"签到ID {sign_id} 结果不明确: '{result_message}'. 可能失败或需关注。", LogLevel.WARNING)
            # Consider not adding to signed_ids or invalid_ids if unclear, so it might be retried next cycle.
            # However, to avoid repeated attempts on persistent non-actionable errors,
            # one might add it to a temporary ignore list for the current cycle or a short duration.
            # For now, we'll assume it might be a transient issue or a non-critical message.
            self._send_notification(f"签到结果 (ID: {sign_id}): {result_message}", is_success=False) # Assume not success if unclear

    def _send_notification(self, message_content: str, is_success: bool) -> None:
        pushplus_token = self.config.get("pushplus")
        if not pushplus_token:
            return

        title_prefix = "✅ 签到成功" if is_success else "⚠️ 签到通知"
        full_title = f"{title_prefix} - {self.config.get('remark', '自动签到')}"
        
        # Construct detailed content for PushPlus
        timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        content_body = f"""
时间: {timestamp_str}
班级ID: {self.config.get("class_id", "N/A")}
消息: {message_content}
设备备注: {self.config.get("remark", "N/A")}
"""
        if not is_success and "坐标" not in message_content and "cookie" not in message_content.lower(): # Add hint for common failures
            content_body += "\n提示: 若失败，请检查Cookie是否过期或签到位置是否准确。"

        try:
            # URL encode title and content for safety, though requests usually handles it.
            # For simplicity, direct inclusion is used here. Proper URL encoding is recommended.
            push_url = (
                f'http://www.pushplus.plus/send?token={pushplus_token}'
                f'&title={requests.utils.quote(full_title)}&content={requests.utils.quote(content_body)}'
                f'&template=markdown' # Using markdown template for better formatting
            )
            response = requests.get(push_url, timeout=10)
            response.raise_for_status()
            # PushPlus response is JSON, check it
            push_response_data = response.json()
            if push_response_data.get("code") == 200:
                 self.logger.log(f"PushPlus通知发送成功: {full_title}", LogLevel.INFO)
            else:
                 self.logger.log(f"PushPlus通知发送失败: {push_response_data.get('msg', '未知错误')}", LogLevel.ERROR)
        except requests.RequestException as e:
            self.logger.log(f"发送PushPlus通知出错: {e}", LogLevel.ERROR)
        except json.JSONDecodeError:
            self.logger.log(f"解析PushPlus响应失败. Raw: {response.text if 'response' in locals() else 'N/A'}", LogLevel.ERROR)


    def _build_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': self._generate_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'X-Requested-With': 'com.tencent.mm', # Simulates WeChat environment
            'Referer': f'http://k8n.cn/student/course/{self.config["class_id"]}/punchs', # Referer for sign-in page
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8', # Prioritize Chinese
            'Cookie': self.config["cookie"]
        }

    def _generate_random_user_agent(self) -> str:
        # Keep User-Agent generation simple as it's not the core focus of the new features
        android_versions = ["10", "11", "12", "13", "14"]
        devices = ["MI 9", "HUAWEI P40", "OPPO Reno5", "vivo X60", "Samsung Galaxy S22"]
        build_numbers = ["QKQ1.190828.002", "HMA-AL00 10.0.0.156(C00E155R2P11)", "PEGM00_11_A.15", "V2055A_A_2.7.3", "SM-S901U1UEU1AVA3"]
        chrome_versions = ["90.0.4430.210", "95.0.4638.50", "100.0.4896.127", "105.0.5195.77", "110.0.5481.65"]
        wechat_versions = ["8.0.20", "8.0.25", "8.0.30", "8.0.32", "8.0.35"]
        net_types = ["WIFI", "4G", "5G"]

        return AppConstants.USER_AGENT_TEMPLATE.format(
            android_version=random.choice(android_versions),
            device=random.choice(devices),
            build_number=random.choice(build_numbers),
            chrome_version=random.choice(chrome_versions),
            wechat_version=random.choice(wechat_versions),
            net_type=random.choice(net_types)
        )

    def _wait_for_next_cycle(self) -> None:
        # Uses local config 'time' for interval
        interval = self.config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL)
        self.logger.log(f"⏳ 等待下次检索，间隔: {interval} 秒。", LogLevel.DEBUG)
        
        # Check stop conditions frequently during sleep
        for _ in range(interval):
            if not self._should_application_run():
                break
            time.sleep(1)


# === Main Application Entry Point ===
if __name__ == "__main__":
    # 1. Initialize Logger (critical first step)
    logger = FileLogger(console_level=LogLevel.INFO) # 修改处 (MODIFIED)
    logger.log(f"--- 自动签到系统 v{SCRIPT_VERSION} 启动 ---", LogLevel.INFO)
    
    # logger = FileLogger()
    # logger.log(f"--- 自动签到系统 v{SCRIPT_VERSION} 启动 ---", LogLevel.INFO)

    # 2. Initialize Device ID
    device_manager = DeviceManager(logger)
    current_device_id = device_manager.get_id()
    logger.log(f"当前设备ID: {current_device_id}", LogLevel.INFO)

    # 3. Initialize Remote Configuration Manager
    remote_config_manager = RemoteConfigManager(
        logger,
        AppConstants.PRIMARY_REMOTE_CONFIG_URL,
        AppConstants.SECONDARY_REMOTE_CONFIG_URL
    )
    # Initial fetch is done in RemoteConfigManager constructor.
    # We can log its status or use it for immediate checks.
    if not remote_config_manager._last_successful_fetch_time: # Check if initial fetch failed
        logger.log("警告: 初始远程配置获取失败，将使用默认或上次缓存的配置（如果存在）。", LogLevel.WARNING)
    else:
        logger.log("初始远程配置已加载。", LogLevel.INFO)


    # 4. Perform Critical Startup Checks based on Remote Config
    if remote_config_manager.is_globally_disabled():
        logger.log("远程配置: 全局禁用已激活。程序将退出。", LogLevel.CRITICAL)
        application_run_event.clear() # Ensure all threads know to stop
        sys.exit(1)

    if not remote_config_manager.is_device_allowed(current_device_id):
        logger.log(f"远程配置: 设备 {current_device_id} 被禁止运行。程序将退出。", LogLevel.CRITICAL)
        application_run_event.clear()
        sys.exit(1)
    
    forced_update_version = remote_config_manager.get_forced_update_below_version()
    # Simple version comparison (assumes versions like X.Y.Z)
    # A more robust comparison would parse version parts.
    if SCRIPT_VERSION < forced_update_version:
        logger.log(f"远程配置: 检测到强制更新。当前版本 {SCRIPT_VERSION}，需要版本 {forced_update_version} 或更高。程序将退出。", LogLevel.CRITICAL)
        logger.log("请从官方渠道更新程序。", LogLevel.CRITICAL)
        application_run_event.clear()
        sys.exit(1)
    
    logger.log("远程配置检查通过 (禁用、设备许可、版本)。", LogLevel.INFO)

    # 5. Initialize Data Uploader
    data_uploader = DataUploader(
        logger,
        current_device_id,
        AppConstants.DATA_UPLOAD_GIST_ID,
        AppConstants.DATA_UPLOAD_FILENAME,
        AppConstants.GITHUB_PAT
    )
    # Perform an initial data upload if desired, or let the background job handle it.
    # For now, let background job handle it to avoid startup delay.

    # 6. Setup and Start Background Jobs
    bg_job_manager = BackgroundJobManager(logger)
    
    # Config refresh job
    config_refresh_interval = remote_config_manager.get_setting(
        "config_refresh_interval_seconds", 
        AppConstants.DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS
    )
    bg_job_manager.add_job(remote_config_manager.fetch_config, config_refresh_interval, "RemoteConfigRefresh")

    # Data upload job
    data_upload_interval = remote_config_manager.get_setting(
        "data_upload_interval_seconds",
        AppConstants.DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS
    )
    bg_job_manager.add_job(data_uploader.upload_data, data_upload_interval, "DataUpload")
    
    bg_job_manager.start_jobs()


    # 7. Initialize Local Configuration (data.json)
    local_config_storage = JsonConfigStorage()
    local_config_manager = ConfigManager(local_config_storage, logger)
    config_updater = ConfigUpdater(local_config_manager, logger)
    
    # This will run the interactive wizard if config is missing/invalid
    # or prompt to update if config exists.
    final_local_config = config_updater.init_config()

    if not final_local_config or not application_run_event.is_set(): # Check run event again in case wizard was exited
        logger.log("本地配置未能成功加载或初始化被中断。程序退出。", LogLevel.CRITICAL)
        application_run_event.clear() # Ensure background jobs stop
        if hasattr(bg_job_manager, 'threads'): time.sleep(2) # Give threads a moment
        sys.exit(1)

    # 8. Display Welcome & Summary (after all configs are set)
    logger.log("\n" + "="*60, LogLevel.INFO)
    logger.log(f"{Fore.GREEN}{Style.BRIGHT}🌟 自动签到系统 v{SCRIPT_VERSION} - 配置完成，准备运行 🌟{Style.RESET_ALL}", LogLevel.INFO)
    logger.log("="*60, LogLevel.INFO)
    initial_announcement = remote_config_manager.get_announcement()
    if initial_announcement:
        logger.log(f"{Fore.YELLOW}[系统公告] {initial_announcement['message']}{Style.RESET_ALL}", LogLevel.INFO)
    
    logger.log(f"当前本地配置摘要 (来自 {AppConstants.CONFIG_FILE}):", LogLevel.INFO)
    logger.log(f"  - 班级ID: {final_local_config['class_id']}", LogLevel.INFO)
    logger.log(f"  - 检查间隔: 每 {final_local_config['time']} 秒", LogLevel.INFO)
    if final_local_config.get('enable_time_range'):
        logger.log(f"  - 运行时间段: {final_local_config['start_time']} 至 {final_local_config['end_time']}", LogLevel.INFO)
    else:

        logger.log("  - 运行时间段: 全天候运行", LogLevel.INFO)
    logger.log(f"日志文件位于: {os.path.join(AppConstants.LOG_DIR, 'auto_check.log')}", LogLevel.INFO)
    logger.log("\n系统正在运行中...", LogLevel.INFO) # _monitor_commands 方法会打印实际的命令提示符。
    # 9. Start the Main Sign-in Task
    sign_task_instance = SignTask(
        config=final_local_config, 
        logger=logger,
        run_event=application_run_event,
        remote_config_mgr=remote_config_manager,
        device_id_str=current_device_id
    )
    
    try:
        sign_task_instance.run() # This is a blocking call until SignTask exits
    except Exception as e: # Catch any uncaught exceptions from SignTask.run() itself
        logger.log(f"签到任务执行期间发生顶层错误: {e}", LogLevel.CRITICAL)
        import traceback
        logger.log(traceback.format_exc(), LogLevel.DEBUG) # Log full traceback for debugging
    finally:
        application_run_event.clear() # Ensure it's cleared if SignTask.run() exits unexpectedly
        logger.log("正在关闭后台任务...", LogLevel.INFO)
        # Background threads are daemons, they will exit when the main thread exits.
        # If explicit cleanup is needed for BackgroundJobManager, call it here.
        # bg_job_manager.stop_jobs() # Already signaled by application_run_event
        time.sleep(1) # Brief pause for daemon threads to notice event change
        logger.log(f"--- 自动签到系统 v{SCRIPT_VERSION} 关闭 ---", LogLevel.INFO)
        time.sleep(0.5)
        sys.exit(0)
