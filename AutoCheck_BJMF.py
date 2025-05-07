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
import tempfile
import shutil
import atexit

# 初始化 colorama
colorama.init(autoreset=True)

# === 常量定义 ===
class AppConstants:
    CURRENT_SCRIPT_VERSION: str = "2.0.1"
    REQUIRED_FIELDS: Tuple[str, ...] = ("cookie", "class_id", "lat", "lng", "acc")
    COOKIE_PATTERN: str = r'remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=[^;]+'
    LOG_DIR: str = "logs"
    CONFIG_FILE: str = "data.json"
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
    REMOTE_CONFIG_URLS: List[str] = [
        "https://raw.githubusercontent.com/byrisk/AutoCheck_BJMF/refs/heads/main/master/remote_config.json",
        "https://gitee.com/your_valid_repo/raw/master/remote_config.json"
    ]
    REMOTE_CONFIG_CACHE_FILE: str = "remote_config_cache.json"
    REMOTE_CONFIG_CACHE_DURATION: timedelta = timedelta(hours=1)
    ANNOUNCEMENT_HISTORY_FILE: str = os.path.join(LOG_DIR, "announcement_history.json")
    DEVICE_ID_FILE: str = os.path.join(LOG_DIR, "device_id.txt")
    STATS_GIST_ID: str = "your_valid_gist_id"
    STATS_GIST_FILENAME: str = "script_usage_stats.jsonl"
    GITHUB_PAT_ENV_VAR: str = "AUTOCHECKIN_GITHUB_PAT"
    CONFIG_BACKUP_DIR: str = "config_backups"
    MAX_CONFIG_BACKUPS: int = 5
    THREAD_JOIN_TIMEOUT: float = 2.0

# === 日志系统 ===
class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()

class LoggerInterface(ABC):
    @abstractmethod
    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        pass

class FileLogger(LoggerInterface):
    def __init__(self, log_file: str = "auto_check.log"):
        self.log_file = os.path.join(AppConstants.LOG_DIR, log_file)
        self._setup_log_directory()
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
        try:
            os.makedirs(AppConstants.LOG_DIR, exist_ok=True)
            if not os.access(AppConstants.LOG_DIR, os.W_OK):
                raise PermissionError(f"无写入权限: {AppConstants.LOG_DIR}")
        except Exception as e:
            print(f"{Fore.RED}创建日志目录 {AppConstants.LOG_DIR} 失败: {e}{Style.RESET_ALL}")
            raise

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level.name}] {message}\n"

        if "--silent" not in sys.argv:
            color = self.color_map.get(level, "")
            icon = self.icon_map.get(level, "")
            print(f"{color}{icon} [{timestamp}] {message}{Style.RESET_ALL}")
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"{Fore.RED}[{timestamp}] [ERROR] 写入日志文件时出错: {e}{Style.RESET_ALL}")
            print(f"{Fore.RED}[{timestamp}] [ERROR] Log entry was: {log_entry.strip()}{Style.RESET_ALL}")

logger = FileLogger()

# === StatisticsReporter ===
class StatisticsReporter:
    def __init__(self, gist_id: str, gist_filename: str, pat_env_var: str, device_id_file: str):
        self.gist_id = gist_id
        self.gist_filename = gist_filename
        self.github_pat = os.getenv(pat_env_var)
        self.device_id = self._get_or_create_device_id(device_id_file)
        self.os_info = platform.system()
        self.session = requests.Session()
        if self.github_pat:
            self.session.headers.update({
                'Authorization': f'token {self.github_pat}',
                'Accept': 'application/vnd.github.v3+json'
            })
        self._remote_config: Optional[Dict[str, Any]] = None
        self._report_pending = False

    def _get_or_create_device_id(self, filepath: str) -> str:
        """增强的设备ID处理，确保目录存在和文件权限"""
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # 检查文件权限
            if os.path.exists(filepath):
                if not os.access(filepath, os.R_OK | os.W_OK):
                    logger.log(f"设备ID文件权限不足: {filepath}", LogLevel.WARNING)
                    os.chmod(filepath, 0o600)
            
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    dev_id = f.read().strip()
                    if dev_id: 
                        return dev_id
            
            dev_id = str(uuid.uuid4())
            with open(filepath, 'w') as f:
                f.write(dev_id)
            os.chmod(filepath, 0o600)
            return dev_id
        except Exception as e:
            logger.log(f"处理设备ID文件 {filepath} 时出错: {e}", LogLevel.WARNING)
            try:
                temp_id = str(uuid.uuid4())
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(temp_id.encode())
                    tmp_path = tmp.name
                logger.log(f"使用临时设备ID文件: {tmp_path}", LogLevel.WARNING)
                return temp_id
            except Exception as tmp_e:
                logger.log(f"创建临时设备ID失败: {tmp_e}", LogLevel.ERROR)
                return "unknown_device_id_" + str(os.getpid())

    def set_remote_config(self, remote_config: Optional[Dict[str, Any]]):
        self._remote_config = remote_config

    def _can_report(self) -> bool:
        if not self.github_pat:
            if not hasattr(self, "_pat_warning_logged"):
                logger.log(f"GitHub PAT (env var {AppConstants.GITHUB_PAT_ENV_VAR}) 未设置，跳过Gist统计上报。", LogLevel.WARNING)
                self._pat_warning_logged = True
            return False
        if self.gist_id == "YOUR_STATS_GIST_ID_HERE":
             if not hasattr(self, "_gist_id_warning_logged"):
                logger.log("STATS_GIST_ID 未配置，跳过Gist统计上报。", LogLevel.WARNING)
                self._gist_id_warning_logged = True
             return False
        if self._remote_config:
            script_control = self._remote_config.get("script_control", {})
            if not script_control.get("enable_statistics_reporting", False):
                logger.log("远程配置禁用了统计信息上报。", LogLevel.DEBUG)
                return False
        return True

    def _fetch_gist_content(self) -> str:
        if not self.gist_id or not self.gist_filename: return ""
        url = f"https://api.github.com/gists/{self.gist_id}"
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            gist_data = response.json()
            if self.gist_filename in gist_data.get("files", {}):
                return gist_data["files"][self.gist_filename].get("content", "")
            logger.log(f"文件 '{self.gist_filename}' 未在Gist '{self.gist_id}' 中找到。", LogLevel.WARNING)
        except requests.RequestException as e:
            logger.log(f"获取Gist内容失败 ({self.gist_id}): {e}", LogLevel.ERROR)
        except json.JSONDecodeError as e:
            logger.log(f"解析Gist内容JSON失败 ({self.gist_id}): {e}", LogLevel.ERROR)
        return ""

    def _update_gist_content(self, new_content_str: str) -> bool:
        if not self.gist_id or not self.gist_filename: return False
        url = f"https://api.github.com/gists/{self.gist_id}"
        payload = {
            "files": {
                self.gist_filename: {
                    "content": new_content_str
                }
            }
        }
        try:
            response = self.session.patch(url, json=payload, timeout=15)
            response.raise_for_status()
            logger.log(f"Gist ({self.gist_id}/{self.gist_filename}) 更新成功。", LogLevel.INFO)
            return True
        except requests.RequestException as e:
            logger.log(f"更新Gist ({self.gist_id}) 失败: {e}. 响应: {e.response.text if e.response else 'N/A'}", LogLevel.ERROR)
        return False

    def report_script_start(self) -> None:
        if self._report_pending:
            return
        self._report_pending = True

        if not self._can_report():
            return

        event_data = {
            "event_type": "script_start",
            "device_id": self.device_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "os_type": self.os_info,
            "script_version": AppConstants.CURRENT_SCRIPT_VERSION
        }
        
        current_content = self._fetch_gist_content()
        new_log_entry = json.dumps(event_data)
        
        if current_content:
            updated_content = current_content.strip() + "\n" + new_log_entry
        else:
            updated_content = new_log_entry
            
        self._update_gist_content(updated_content)
        self._report_pending = False

stats_reporter = StatisticsReporter(
    gist_id=AppConstants.STATS_GIST_ID,
    gist_filename=AppConstants.STATS_GIST_FILENAME,
    pat_env_var=AppConstants.GITHUB_PAT_ENV_VAR,
    device_id_file=AppConstants.DEVICE_ID_FILE
)

# === Remote Configuration Fetcher ===
class RemoteConfigFetcher:
    def __init__(self, urls: List[str], cache_file: str, cache_duration: timedelta):
        self.urls = [url for url in urls if url and "YOUR_" not in url.upper()]
        self.cache_file = cache_file
        self.cache_duration = cache_duration
        self.config: Optional[Dict[str, Any]] = None

    def _load_from_cache(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.cache_file):
            return None
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            timestamp_str = cached_data.get("timestamp")
            if not timestamp_str: return None
            
            timestamp = datetime.fromisoformat(timestamp_str)
            if datetime.now() - timestamp < self.cache_duration:
                logger.log("从缓存加载远程配置.", LogLevel.DEBUG)
                return cached_data.get("config")
            logger.log("远程配置缓存已过期.", LogLevel.DEBUG)
        except (IOError, json.JSONDecodeError, ValueError) as e:
            logger.log(f"加载远程配置缓存时出错: {e}", LogLevel.WARNING)
        return None

    def _save_to_cache(self, config_data: Dict[str, Any]) -> None:
        try:
            # 确保目录存在
            cache_dir = os.path.dirname(self.cache_file)
            if cache_dir:  # 如果路径包含目录部分
                os.makedirs(cache_dir, exist_ok=True)
                if not os.access(cache_dir, os.W_OK):
                    raise PermissionError(f"无写入权限: {cache_dir}")

            # 使用临时文件安全写入
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=cache_dir or '.',  # 如果无目录则用当前目录
                    delete=False
                ) as tmp_file:
                    temp_path = tmp_file.name
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "config": config_data
                    }, tmp_file, indent=4)
                
                # 原子性替换
                if os.path.exists(self.cache_file):
                    os.replace(temp_path, self.cache_file)
                else:
                    os.rename(temp_path, self.cache_file)
                
                logger.log(f"远程配置缓存已保存到: {self.cache_file}", LogLevel.DEBUG)
            except Exception as e:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
                raise
        except Exception as e:
            logger.log(f"保存远程配置缓存时出错: {e}", LogLevel.ERROR)
            # 回退到临时目录
            try:
                temp_cache = os.path.join(tempfile.gettempdir(), "remote_config_cache.json")
                with open(temp_cache, 'w', encoding='utf-8') as f:
                    json.dump({
                        "timestamp": datetime.now().isoformat(),
                        "config": config_data
                    }, f, indent=4)
                logger.log(f"使用临时文件保存远程配置缓存: {temp_cache}", LogLevel.WARNING)
            except Exception as temp_e:
                logger.log(f"连临时文件也无法保存: {temp_e}", LogLevel.ERROR)

    def fetch_config(self) -> Optional[Dict[str, Any]]:
        cached_config = self._load_from_cache()
        if cached_config:
            self.config = cached_config
            stats_reporter.set_remote_config(self.config)
            return self.config

        if not self.urls:
            logger.log("未配置有效远程配置URL (REMOTE_CONFIG_URLS).", LogLevel.WARNING)
            return None

        for i, url in enumerate(self.urls):
            try:
                logger.log(f"尝试从源 {i+1}/{len(self.urls)} 获取远程配置: {url}", LogLevel.INFO)
                response = requests.get(url, timeout=10, headers={'User-Agent': f'AutoCheckinScript/{AppConstants.CURRENT_SCRIPT_VERSION}'})
                response.raise_for_status()
                self.config = response.json()
                if self.config:
                    self._save_to_cache(self.config)
                    logger.log(f"成功从 {url} 获取远程配置.", LogLevel.INFO)
                    stats_reporter.set_remote_config(self.config)
                    return self.config
            except requests.RequestException as e:
                logger.log(f"从 {url} 获取远程配置失败 (源 {i+1}): {e}", LogLevel.WARNING)
            except json.JSONDecodeError as e:
                logger.log(f"解析来自 {url} 的远程配置JSON时失败 (源 {i+1}): {e}", LogLevel.WARNING)
        
        logger.log("所有远程配置源均获取失败.", LogLevel.ERROR)
        return None

# === Update Handler ===
class UpdateHandler:
    def __init__(self, current_version: str, remote_config_data: Optional[Dict[str, Any]]):
        self.current_version_str = current_version
        self.remote_config = remote_config_data

    def _version_tuple(self, version_str: str) -> Tuple[int, ...]:
        try:
            return tuple(map(int, version_str.split('.')))
        except ValueError:
            logger.log(f"版本号格式无效: {version_str}. 视为旧版本.", LogLevel.WARNING)
            return (0, 0, 0)

    def check_for_updates(self) -> None:
        if not self.remote_config or "script_control" not in self.remote_config:
            logger.log("远程配置中缺少 'script_control'，跳过更新检查.", LogLevel.DEBUG)
            return

        script_control = self.remote_config["script_control"]
        latest_version_str = script_control.get("latest_version")
        force_update_below_str = script_control.get("force_update_below_version")
        
        current_v_tuple = self._version_tuple(self.current_version_str)

        if force_update_below_str:
            force_v_tuple = self._version_tuple(force_update_below_str)
            if current_v_tuple < force_v_tuple:
                msg = (f"强制更新: 脚本版本 {self.current_version_str} 过旧，必须更新到版本 "
                       f"{force_update_below_str} 或更高版本才能继续使用。\n"
                       "请访问项目地址获取最新版本 (地址请咨询脚本提供者)。")
                logger.log(msg, LogLevel.CRITICAL)
                print(f"{Fore.RED}{Style.BRIGHT}{msg}{Style.RESET_ALL}")
                sys.exit(10)

        if latest_version_str:
            latest_v_tuple = self._version_tuple(latest_version_str)
            if current_v_tuple < latest_v_tuple:
                msg = (f"建议更新: 检测到新版本 {latest_version_str} (当前: {self.current_version_str}).\n"
                       "建议更新以获取最新功能和修复 (地址请咨询脚本提供者)。")
                logger.log(msg, LogLevel.INFO)
                print(f"{Fore.YELLOW}💡 {msg}{Style.RESET_ALL}")

# === Announcement Displayer ===
class AnnouncementDisplayer:
    def __init__(self, remote_config_data: Optional[Dict[str, Any]], history_file: str):
        self.remote_config = remote_config_data
        self.history_file = history_file
        self.shown_history: List[str] = self._load_history()

    def _load_history(self) -> List[str]:
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.log(f"加载公告历史失败: {e}", LogLevel.WARNING)
        return []

    def _save_history(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.shown_history, f, indent=4)
        except IOError as e:
            logger.log(f"保存公告历史失败: {e}", LogLevel.WARNING)

    def display_announcement(self) -> None:
        if not self.remote_config or "announcement" not in self.remote_config:
            return

        announcement = self.remote_config.get("announcement")
        if not announcement or not isinstance(announcement, dict) or \
           not announcement.get("message") or not announcement.get("id"):
            return

        anno_id = announcement["id"]
        show_once = announcement.get("show_once", True)

        if show_once and anno_id in self.shown_history:
            return

        title = announcement.get("title", "📢 系统公告")
        message = announcement["message"]
        
        print("\n" + "="*10 + f" {Style.BRIGHT}{Fore.CYAN}{title}{Style.RESET_ALL} " + "="*10)
        print(message)
        print("="* (22 + len(title)))
        print()
        
        logger.log(f"显示公告 (ID: {anno_id}): {title}", LogLevel.INFO)

        if anno_id not in self.shown_history:
            self.shown_history.append(anno_id)
            self._save_history()

# === 配置模型 ===
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
            lat_val = float(v)
            if not -90 <= lat_val <= 90:
                raise ValueError("纬度需在 -90 到 90 之间")
            return v
        except ValueError:
            raise ValueError("纬度必须是有效数字且在-90到90之间")

    @field_validator('lng')
    @classmethod
    def validate_longitude(cls, v: str) -> str:
        if not v:
            raise ValueError("经度不能为空")
        try:
            lng_val = float(v)
            if not -180 <= lng_val <= 180:
                raise ValueError("经度需在 -180 到 180 之间")
            return v
        except ValueError:
            raise ValueError("经度必须是有效数字且在-180到180之间")

    @field_validator('acc')
    @classmethod
    def validate_altitude(cls, v: str) -> str:
        if not v:
            raise ValueError("海拔/精度不能为空")
        try:
            float(v)
            return v
        except ValueError:
            raise ValueError("海拔/精度必须是有效数字")

    @field_validator('cookie')
    @classmethod
    def validate_cookie(cls, v: str) -> str:
        if not v:
            raise ValueError("Cookie 不能为空")
        if not re.search(AppConstants.COOKIE_PATTERN, v):
            raise ValueError(f"Cookie 缺少关键字段，需包含 {AppConstants.COOKIE_PATTERN}")
        return v

    @field_validator('time')
    @classmethod
    def validate_search_time(cls, v: Any) -> int:
        if isinstance(v, str):
            try:
                v = int(v)
            except ValueError:
                raise ValueError("检索间隔必须为有效的整数")
        if not isinstance(v, int) or v <= 0:
            raise ValueError("检索间隔必须为正整数")
        return v

    @field_validator('start_time', 'end_time')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError("时间格式必须为 HH:MM")

# === 配置存储 ===
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
        self.backup_dir = AppConstants.CONFIG_BACKUP_DIR
        os.makedirs(self.backup_dir, exist_ok=True)

    def _create_backup(self) -> bool:
        """创建配置备份"""
        if not os.path.exists(self.config_path):
            return False
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(self.backup_dir, f"config_backup_{timestamp}.json")
            shutil.copy2(self.config_path, backup_path)
            
            # 清理旧备份
            backups = sorted([f for f in os.listdir(self.backup_dir) if f.startswith("config_backup_")])
            while len(backups) > AppConstants.MAX_CONFIG_BACKUPS:
                os.remove(os.path.join(self.backup_dir, backups[0]))
                backups.pop(0)
            return True
        except Exception as e:
            logger.log(f"创建配置备份失败: {e}", LogLevel.WARNING)
            return False

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件 {self.config_path} 格式错误: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        """原子性保存配置，使用临时文件+重命名方式"""
        self._create_backup()
        temp_path = None
        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=os.path.dirname(self.config_path) or '.',
                delete=False
            ) as tmp_file:
                temp_path = tmp_file.name
                json.dump(config, tmp_file, indent=4, ensure_ascii=False)
            
            # 原子性替换
            if os.path.exists(self.config_path):
                os.replace(temp_path, self.config_path)
            else:
                os.rename(temp_path, self.config_path)
            
            # 设置安全权限
            os.chmod(self.config_path, 0o600)
            logger.log(f"配置已安全保存到 {self.config_path}", LogLevel.INFO)
        except Exception as e:
            logger.log(f"保存配置文件 {self.config_path} 时出错: {e}", LogLevel.ERROR)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise ValueError(f"保存配置文件 {self.config_path} 时出错: {e}")

# === 配置管理器 ===
class ConfigManager:
    def __init__(self, storage: ConfigStorageInterface, logger_instance: LoggerInterface, remote_config_data: Optional[Dict[str, Any]] = None):
        self.storage = storage
        self.logger = logger_instance
        self.remote_config_data = remote_config_data
        self._config: Dict[str, Any] = self._load_config()

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        self._config = value

    def _load_config(self) -> Dict[str, Any]:
        current_config: Dict[str, Any] = {}
        try:
            raw_config_from_file = self.storage.load()
        except ValueError as e:
            self.logger.log(f"无法加载本地配置文件: {e}", LogLevel.ERROR)
            raw_config_from_file = {}

        defaults = {
            "time": AppConstants.DEFAULT_SEARCH_INTERVAL,
            "remark": "自动签到配置",
            "enable_time_range": False,
            "start_time": "08:00",
            "end_time": "22:00",
            "pushplus": ""
        }
        
        if self.remote_config_data:
            overrides = self.remote_config_data.get("client_overrides", {})
            if overrides.get("search_interval") is not None:
                try:
                    validated_remote_time = ConfigModel.validate_search_time(overrides["search_interval"])
                    defaults["time"] = validated_remote_time
                    self.logger.log(f"远程配置已覆盖检查间隔为: {validated_remote_time} 秒.", LogLevel.INFO)
                except ValueError as ve:
                    self.logger.log(f"远程配置中的 search_interval ({overrides['search_interval']}) 无效: {ve}. 使用默认值.", LogLevel.WARNING)

        current_config = {**defaults, **raw_config_from_file}

        if raw_config_from_file:
            missing_fields = []
            for field_name in AppConstants.REQUIRED_FIELDS:
                if field_name not in current_config or not current_config[field_name]:
                    missing_fields.append(field_name)
            if missing_fields:
                self.logger.log(f"本地配置文件 {self.storage.config_path} 缺少必填字段: {', '.join(missing_fields)}.", LogLevel.ERROR)
                return {}

        if not raw_config_from_file and not all(rf in current_config for rf in AppConstants.REQUIRED_FIELDS):
             return {}

        try:
            return ConfigModel(**current_config).model_dump()
        except ValidationError as e:
            self._handle_validation_error(e)
            return {}
            
    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"字段 '{err['loc'][0]}': {err['msg']}" for err in error.errors()]
        self.logger.log("配置数据验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

    def save(self) -> None:
        try:
            ConfigModel(**self._config).model_dump()
            self.storage.save(self._config)
            self.logger.log("配置已成功保存到本地。", LogLevel.INFO)
        except ValidationError as e:
            self._handle_validation_error(e)
            self.logger.log("由于验证错误，配置未保存。", LogLevel.ERROR)
        except ValueError as e:
            self.logger.log(f"保存配置到 {self.storage.config_path} 时出错: {e}", LogLevel.ERROR)

# === 扫码登录系统 ===
class QRLoginSystem:
    def __init__(self):
        self.base_url = 'http://k8n.cn/weixin/qrlogin/student'
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Cache-Control': 'max-age=0',
            'Host': 'k8n.cn',
            'Proxy-Connection': 'keep-alive',
            'Referer': 'http://k8n.cn/student/login?ref=%2Fstudent',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.max_attempts = 20
        self.check_interval = 2
        self.classid: Optional[str] = None
        self.login_successful_event = threading.Event()
        self._login_success_flag = False

    def fetch_qr_code_url(self) -> Optional[str]:
        logger.log("正在获取二维码页面...", LogLevel.DEBUG)
        try:
            response = self.session.get(self.base_url)
            response.raise_for_status()
            
            pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=[^"]+'
            match = re.search(pattern, response.text)
            if match:
                qr_code_url = match.group(0)
                logger.log("成功从页面提取二维码图片链接。", LogLevel.INFO)
                return qr_code_url
            logger.log("未在页面中找到二维码图片链接。", LogLevel.ERROR)
        except requests.RequestException as e:
            logger.log(f"获取二维码页面出错: {e}", LogLevel.ERROR)
        return None

    def display_qr_code(self, qr_code_url: str) -> None:
        logger.log("准备显示二维码...", LogLevel.DEBUG)
        self.login_successful_event.clear()
        self._login_success_flag = False

        try:
            qr_response = requests.get(qr_code_url, timeout=10)
            qr_response.raise_for_status()
            
            img = Image.open(BytesIO(qr_response.content))
            img = img.resize((260, 260), Image.LANCZOS)

            root = tk.Tk()
            root.title("微信登录二维码")
            window_width = 320; window_height = 400
            screen_width = root.winfo_screenwidth(); screen_height = root.winfo_screenheight()
            x_cordinate = int((screen_width/2) - (window_width/2))
            y_cordinate = int((screen_height/2) - (window_height/2))
            root.geometry(f"{window_width}x{window_height}+{x_cordinate}+{y_cordinate-30}")
            root.resizable(False, False)
            root.attributes('-topmost', True)

            main_frame = tk.Frame(root, padx=20, pady=20)
            main_frame.pack(expand=True, fill=tk.BOTH)
            photo = ImageTk.PhotoImage(img)
            tk.Label(main_frame, image=photo, bd=2, relief=tk.GROOVE).pack(pady=(0,15), padx=5)
            tk.Label(main_frame, text="请使用微信扫描二维码登录", font=("Microsoft YaHei", 12), fg="#333").pack(pady=(0,10))
            main_frame.image = photo

            def on_closing():
                logger.log("二维码窗口被用户关闭。", LogLevel.WARNING)
                if root.winfo_exists(): root.destroy()
                self.login_successful_event.set()

            root.protocol("WM_DELETE_WINDOW", on_closing)
            root.after(100, root.focus_force)
            root.after(0, lambda r=root, att=0: self._check_login_status_poll(r, att))
            root.mainloop()

        except requests.RequestException as e:
            logger.log(f"获取二维码图片失败: {e}", LogLevel.ERROR)
        except Exception as e:
            logger.log(f"显示二维码时发生错误: {e}", LogLevel.ERROR)
            logger.log(f"{Fore.YELLOW}若二维码无法显示，请尝试手动复制链接到浏览器扫码: {qr_code_url}{Style.RESET_ALL}")

    def _check_login_status_poll(self, root_window: tk.Tk, attempt: int) -> None:
        if not root_window.winfo_exists():
            self.login_successful_event.set()
            return

        if attempt >= self.max_attempts:
            logger.log("超过最大尝试次数，登录检查失败。", LogLevel.ERROR)
            if root_window.winfo_exists(): root_window.destroy()
            self.login_successful_event.set()
            return

        check_url = f"{self.base_url}?op=checklogin"
        try:
            response = self.session.get(check_url, timeout=5)
            response.raise_for_status()
            logger.log(f"第 {attempt + 1} 次检查登录状态，状态码: {response.status_code}", LogLevel.DEBUG)
            data = response.json()
            if data.get('status'):
                logger.log("微信扫码确认成功!", LogLevel.INFO)
                self._login_success_flag = True
                redirect_url_path = data.get('url')
                if redirect_url_path:
                    full_redirect_url = 'http://k8n.cn' + redirect_url_path
                    try:
                        logger.log(f"处理登录后跳转: {full_redirect_url}", LogLevel.DEBUG)
                        self.session.get(full_redirect_url, allow_redirects=True, timeout=10)
                    except requests.RequestException as e:
                        logger.log(f"处理登录后跳转失败: {e}", LogLevel.WARNING)
                
                self.login_successful_event.set()
                if root_window.winfo_exists(): root_window.destroy()
                return
        except requests.RequestException as e:
            logger.log(f"第 {attempt + 1} 次登录检查网络出错: {e}", LogLevel.WARNING)
        except json.JSONDecodeError:
            logger.log(f"第 {attempt + 1} 次登录检查JSON解析错误. Response: {response.text[:100]}", LogLevel.WARNING)
        except Exception as e:
             logger.log(f"第 {attempt + 1} 次登录检查时未知错误: {e}", LogLevel.WARNING)

        if root_window.winfo_exists():
            root_window.after(self.check_interval * 1000, 
                              lambda r=root_window, att=attempt+1: self._check_login_status_poll(r, att))

    def fetch_logged_in_data(self) -> Dict[str, Any]:
        logger.log("获取登录后用户数据 (班级等)...", LogLevel.INFO)
        data_url = 'http://k8n.cn/student'
        try:
            response = self.session.get(data_url, timeout=10)
            response.raise_for_status()

            class_ids = self._extract_class_ids(response.text)
            if not class_ids:
                logger.log("未找到任何班级信息。Cookie可能无效或账户无班级。", LogLevel.ERROR)
                return {"status": "error", "message": "No classes found"}
            
            logger.log(f"找到的班级ID: {', '.join(class_ids)}", LogLevel.DEBUG)
            if len(class_ids) == 1:
                self.classid = class_ids[0]
                logger.log(f"自动选择班级ID: {self.classid}", LogLevel.INFO)
            else:
                print(f"{Fore.GREEN}找到多个班级信息：{Style.RESET_ALL}")
                for idx, cid in enumerate(class_ids, start=1): print(f"  {idx}. {cid}")
                while True:
                    try:
                        choice_str = input("请输入要使用的班级序号: ").strip()
                        if not choice_str: raise ValueError("输入不能为空")
                        choice = int(choice_str) - 1
                        if 0 <= choice < len(class_ids):
                            self.classid = class_ids[choice]
                            logger.log(f"已选择班级ID: {self.classid}", LogLevel.INFO)
                            break
                        else: print(f"{Fore.RED}输入的序号无效。{Style.RESET_ALL}")
                    except ValueError as e: print(f"{Fore.RED}输入无效 ({e})，请输入数字。{Style.RESET_ALL}")
            
            main_cookie_value = self.session.cookies.get('remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d')
            if main_cookie_value:
                cookie_str_for_config = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={main_cookie_value}"
                logger.log("成功获取用户数据和Session Cookie。", LogLevel.INFO)
                return {
                    "status": "success",
                    "classid": self.classid,
                    "cookie": cookie_str_for_config
                }
            else:
                logger.log("登录后未能从会话中提取关键Cookie 'remember_student_...'.", LogLevel.ERROR)
                return {"status": "error", "message": "Critical cookie missing post-login"}

        except requests.RequestException as e:
            logger.log(f"获取用户数据时网络出错: {e}", LogLevel.ERROR)
            return {"status": "error", "message": f"Network error: {e}"}
        except Exception as e:
            logger.log(f"获取用户数据时发生未知错误: {e}", LogLevel.ERROR)
            return {"status": "error", "message": f"Unknown error: {e}"}

    def _extract_class_ids(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, 'html.parser')
        return [div.get('course_id') for div in soup.find_all('div', class_='card mb-3 course') if div.get('course_id')]

# === 配置更新器 ===
class ConfigUpdater:
    def __init__(self, config_manager_instance: ConfigManager, logger_instance: LoggerInterface):
        self.manager = config_manager_instance
        self.logger = logger_instance
        self.login_system = QRLoginSystem()
        self.scanned_class_ids: List[str] = []
        self.scanned_cookie: Optional[str] = None

    def init_config(self) -> Dict[str, Any]:
        if not self.manager.config or not self._validate_config(self.manager.config):
            self.logger.log("配置无效或首次运行，进入配置向导...", LogLevel.INFO)
            return self._first_run_config_wizard()
        
        self._show_current_config()
        if self._should_update_config():
            return self._update_config_interactively()
        
        return self.manager.config

    def _first_run_config_wizard(self) -> Dict[str, Any]:
        self.logger.log(f"\n{Fore.GREEN}🌟 欢迎使用自动签到系统 v{AppConstants.CURRENT_SCRIPT_VERSION} 🌟{Style.RESET_ALL}", LogLevel.INFO)
        self.logger.log(f"{Fore.YELLOW}首次运行或配置重置，需要进行初始配置。{Style.RESET_ALL}", LogLevel.INFO)
        print("="*50)
        
        new_config_data: Dict[str, Any] = {}
        
        login_info = self._setup_login_method()
        if not login_info.get("cookie") or not login_info.get("class_id"):
            self.logger.log("未能获取登录凭证，无法继续配置。", LogLevel.CRITICAL)
            if input("获取登录凭证失败。按 Enter 重试，或输入 'q' 退出: ").lower() == 'q':
                sys.exit(1)
            return self._first_run_config_wizard()
        new_config_data.update(login_info)

        self._setup_location_info(new_config_data)
        self._setup_other_settings(new_config_data)
        
        try:
            validated_config = ConfigModel(**new_config_data).model_dump()
            self.manager.config = validated_config
            self.manager.save()
            self.logger.log(f"\n{Fore.GREEN}✅ 初始配置完成并已保存！{Style.RESET_ALL}", LogLevel.INFO)
            return validated_config
        except ValidationError as e:
            self._handle_validation_error(e)
            self.logger.log("配置输入有误，请重新开始配置向导。", LogLevel.ERROR)
            if input("按 Enter 重试配置，或输入 'q' 退出: ").lower() == 'q':
                sys.exit(1)
            return self._first_run_config_wizard()

    def _setup_login_method(self) -> Dict[str, Any]:
        self.logger.log(f"\n{Fore.CYAN}=== 第一步：登录方式设置 ==={Style.RESET_ALL}", LogLevel.INFO)
        print("请选择获取Cookie和班级ID的方式：")
        print(f"1. {Fore.GREEN}扫码登录（推荐）{Style.RESET_ALL}")
        print("2. 手动输入")
        
        while True:
            choice = input("\n请选择 (1/2，默认1): ").strip() or "1"
            if choice == "1":
                if self._perform_scan_login_flow():
                    if self.scanned_cookie and self.scanned_class_ids:
                        return {
                            "cookie": self.scanned_cookie,
                            "class_id": self.scanned_class_ids[0]
                        }
                self.logger.log("扫码登录未能完成或未获取到所需信息。", LogLevel.WARNING)
                if input("扫码未成功。尝试手动输入吗？ (y/n, 默认n): ").lower() == 'y':
                    return self._manual_input_credentials()
            elif choice == "2":
                return self._manual_input_credentials()
            else:
                print(f"{Fore.RED}无效输入，请选择1或2。{Style.RESET_ALL}")

    def _perform_scan_login_flow(self) -> bool:
        self.scanned_cookie = None
        self.scanned_class_ids = []

        for attempt in range(1, 4):
            self.logger.log(f"\n发起第 {attempt} 次扫码登录尝试...", LogLevel.INFO)
            qr_url = self.login_system.fetch_qr_code_url()
            if not qr_url:
                self.logger.log("获取二维码链接失败。", LogLevel.WARNING)
                if attempt < 3 and input("重试获取二维码链接? (y/n): ").lower() != 'y': break
                continue
            
            self.login_system.display_qr_code(qr_url)
            self.login_system.login_successful_event.wait(timeout=120)

            if not self.login_system.login_successful_event.is_set():
                logger.log("等待扫码超时或二维码窗口未正确发出信号。", LogLevel.WARNING)
            
            if self.login_system._login_success_flag:
                login_data = self.login_system.fetch_logged_in_data()
                if login_data.get("status") == "success":
                    self.scanned_cookie = login_data.get("cookie")
                    class_id_val = login_data.get("classid")
                    self.scanned_class_ids = [class_id_val] if class_id_val else []

                    if self.scanned_cookie and self.scanned_class_ids:
                        self.logger.log("扫码登录并成功获取凭证!", LogLevel.INFO)
                        self.logger.log(f"- 班级ID: {self.scanned_class_ids[0]}", LogLevel.DEBUG)
                        return True
                    else:
                         self.logger.log("扫码后数据提取不完整 (Cookie或ClassID缺失)。", LogLevel.WARNING)
                else:
                    self.logger.log(f"扫码后获取用户数据失败: {login_data.get('message', '未知错误')}", LogLevel.WARNING)
            
            if attempt < 3 and input("本次扫码尝试未成功，是否再次尝试? (y/n): ").lower() != 'y':
                break

        self.logger.log("扫码登录多次尝试后失败。", LogLevel.ERROR)
        return False

    def _manual_input_credentials(self) -> Dict[str, Any]:
        self.logger.log(f"\n{Fore.YELLOW}⚠️ 请手动输入必要凭证信息。{Style.RESET_ALL}", LogLevel.INFO)
        data = {}
        data["cookie"] = self._get_validated_input(
            "请输入Cookie: ", ConfigModel.validate_cookie, is_required=True
        )
        data["class_id"] = self._get_validated_input(
            "请输入班级ID: ", ConfigModel.validate_class_id, is_required=True
        )
        return data

    def _get_validated_input(self, prompt: str, validator: Callable[[Any], str], 
                             default_value: Optional[str] = None, is_required: bool = False) -> str:
        while True:
            try:
                value = input(prompt).strip()
                if not value and default_value is not None and not is_required:
                    value = default_value
                
                if is_required and not value:
                    raise ValueError("该字段为必填项，不能为空。")
                
                if value:
                    return validator(value)
                
                if not is_required:
                    return ""
                
            except ValueError as e:
                self.logger.log(f"输入错误: {e}", LogLevel.WARNING)

    def _setup_location_info(self, config_data: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.CYAN}=== 第二步：位置信息设置 ==={Style.RESET_ALL}", LogLevel.INFO)
        print("请提供您常用的签到位置坐标：")
        config_data["lat"] = self._get_validated_input("请输入纬度（如39.9042）: ", ConfigModel.validate_latitude, is_required=True)
        config_data["lng"] = self._get_validated_input("请输入经度（如116.4074）: ", ConfigModel.validate_longitude, is_required=True)
        config_data["acc"] = self._get_validated_input("请输入海拔/精度（如50.0）: ", ConfigModel.validate_altitude, is_required=True)

    def _setup_other_settings(self, config_data: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.CYAN}=== 第三步：其他设置 ==={Style.RESET_ALL}", LogLevel.INFO)
        while True:
            try:
                time_input = input(f"请输入检查间隔（秒，默认{AppConstants.DEFAULT_SEARCH_INTERVAL}）: ").strip()
                val_to_validate = time_input if time_input else str(AppConstants.DEFAULT_SEARCH_INTERVAL)
                config_data["time"] = ConfigModel.validate_search_time(val_to_validate)
                break
            except ValueError as e: print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

        config_data["pushplus"] = input("请输入PushPlus令牌（可选，回车跳过）: ").strip()
        self._setup_time_range(config_data)
        config_data["remark"] = input("请输入备注信息（可选，默认为 '自动签到配置'）: ").strip() or "自动签到配置"

    def _setup_time_range(self, config_data: Dict[str, Any]) -> None:
        enable = input("是否启用时间段控制？(y/n, 默认n): ").strip().lower() == 'y'
        config_data["enable_time_range"] = enable
        if enable:
            print("请设置运行时间段（格式: HH:MM）")
            while True:
                try:
                    start = input("开始时间（如08:00）: ").strip()
                    end = input("结束时间（如22:00）: ").strip()
                    datetime.strptime(start, '%H:%M'); datetime.strptime(end, '%H:%M')
                    if datetime.strptime(start, '%H:%M').time() >= datetime.strptime(end, '%H:%M').time():
                        raise ValueError("开始时间必须早于结束时间")
                    config_data["start_time"] = start; config_data["end_time"] = end
                    break
                except ValueError as e: print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

    def _validate_config(self, config_to_validate: Dict[str, Any]) -> bool:
        if not config_to_validate: return False
        try:
            ConfigModel(**config_to_validate)
            for field_name in AppConstants.REQUIRED_FIELDS:
                if field_name not in config_to_validate or not config_to_validate[field_name]:
                    return False
            return True
        except ValidationError:
            return False

    def _show_current_config(self) -> None:
        config_data = self.manager.config
        if not config_data:
            self.logger.log("当前无有效配置可显示。", LogLevel.INFO)
            return

        self.logger.log("\n📋 当前配置信息", LogLevel.INFO)
        self.logger.log("--------------------------------", LogLevel.INFO)
        cookie_display = config_data.get("cookie", "未设置")
        if len(cookie_display) > 40: cookie_display = f"{cookie_display[:25]}...{cookie_display[-15:]}"
        
        config_items = [
            ("班级ID", config_data.get("class_id")), ("纬度", config_data.get("lat")),
            ("经度", config_data.get("lng")), ("海拔/精度", config_data.get("acc")),
            ("检查间隔", f"{config_data.get('time')}秒"), ("Cookie", cookie_display),
            ("PushPlus", config_data.get("pushplus") or "未设置"), ("备注", config_data.get("remark")),
            ("时间段控制", "已启用" if config_data.get("enable_time_range") else "已禁用")
        ]
        if config_data.get("enable_time_range"):
            config_items.append(("运行时间段", f"{config_data.get('start_time')} 至 {config_data.get('end_time')}"))
        for name, value in config_items:
            self.logger.log(f"🔹 {name.ljust(10)}: {value if value is not None else '未设置'}", LogLevel.INFO)
        self.logger.log("--------------------------------", LogLevel.INFO)

    def _should_update_config(self) -> bool:
        print("\n是否要修改当前配置？(y/n, 默认n, 10秒后自动选n): ", end='', flush=True)
        timeout = 10; default_choice = 'n'; user_input_container = [default_choice]
        
        def get_input_thread_target(container):
            try:
                raw_input_val = sys.stdin.readline().strip().lower()
                if raw_input_val: container[0] = raw_input_val
            except Exception: pass
        
        input_thread = threading.Thread(target=get_input_thread_target, args=(user_input_container,))
        input_thread.daemon = True; input_thread.start(); input_thread.join(timeout)
        
        final_choice = user_input_container[0]
        if input_thread.is_alive():
            print(f"\n{Fore.YELLOW}输入超时，自动选择默认值 '{default_choice}'{Style.RESET_ALL}")
            final_choice = default_choice
        elif not final_choice:
            final_choice = default_choice
        
        if final_choice not in ['y', 'n']: final_choice = default_choice

        if final_choice != default_choice or not input_thread.is_alive():
             print(final_choice if final_choice else default_choice)

        return final_choice == 'y'

    def _update_config_interactively(self) -> Dict[str, Any]:
        original_config = deepcopy(self.manager.config)
        working_config = deepcopy(self.manager.config)

        try:
            self._update_cookie_and_class_id_interactive(working_config)
            
            while True:
                print("\n" + "="*10 + " 当前待修改配置 " + "="*10)
                temp_manager_display = ConfigManager(self.manager.storage, self.logger)
                temp_manager_display.config = working_config
                ConfigUpdater(temp_manager_display, self.logger)._show_current_config()
                print("="*35)

                print("\n🔧 请选择要修改的配置项:")
                print("1. 位置信息 (纬度/经度/海拔)")
                print("2. 检查间隔时间")
                print("3. PushPlus通知设置")
                print("4. 备注信息")
                print("5. 运行时间段设置")
                print("6. 重新获取Cookie和班级ID (通过扫码/手动)")
                print("0. 完成配置并保存")
                
                choice = input("\n请输入选项编号 (0-6, 默认0完成): ").strip() or "0"
                
                if choice == "0": break
                elif choice == "1": self._setup_location_info(working_config)
                elif choice == "2": self._update_search_interval_interactive(working_config)
                elif choice == "3": self._update_pushplus_interactive(working_config)
                elif choice == "4": self._update_remark_interactive(working_config)
                elif choice == "5": self._setup_time_range(working_config)
                elif choice == "6": self._update_cookie_and_class_id_interactive(working_config)
                else: print(f"{Fore.RED}⚠️ 无效选项，请重新输入。{Style.RESET_ALL}")
            
            print("\n" + "="*10 + " 最终配置预览 " + "="*10)
            temp_manager_display = ConfigManager(self.manager.storage, self.logger)
            temp_manager_display.config = working_config
            ConfigUpdater(temp_manager_display, self.logger)._show_current_config()
            print("="*30)

            if input("\n确认保存以上修改？(y/n, 默认y): ").strip().lower() in ['y', '']:
                try:
                    ConfigModel(**working_config)
                    self.manager.config = working_config
                    self.manager.save()
                    self.logger.log("✅ 配置已更新并成功保存！", LogLevel.INFO)
                    return self.manager.config
                except ValidationError as e:
                    self._handle_validation_error(e)
                    self.logger.log("配置更新因验证错误未能保存。", LogLevel.ERROR)
                    self.manager.config = original_config
                    if input("是否重试修改配置？(y/n): ").lower() == 'y':
                        return self._update_config_interactively()
                    return original_config 
            else:
                self.manager.config = original_config
                self.logger.log("🔄 用户取消，配置已恢复到修改前状态。", LogLevel.INFO)
                return original_config
                
        except Exception as e:
            self.manager.config = original_config
            self.logger.log(f"配置更新过程中发生意外错误: {e}. 配置已恢复。", LogLevel.ERROR)
            return original_config

    def _update_cookie_and_class_id_interactive(self, current_config_dict: Dict[str, Any]):
        self.logger.log("\n🛠️ 更新登录凭证 (Cookie 和 班级ID)", LogLevel.INFO)
        if input("是否要更新Cookie和班级ID？(y/n, 默认n): ").strip().lower() == 'y':
            login_details = self._setup_login_method()
            if login_details.get("cookie") and login_details.get("class_id"):
                current_config_dict["cookie"] = login_details["cookie"]
                current_config_dict["class_id"] = login_details["class_id"]
                self.logger.log("临时配置中的Cookie和Class ID已更新。", LogLevel.INFO)
            else:
                self.logger.log("未能获取新的Cookie和Class ID，临时配置中对应项未更改。", LogLevel.WARNING)

    def _update_search_interval_interactive(self, current_config_dict: Dict[str, Any]):
        current_val = current_config_dict.get('time', AppConstants.DEFAULT_SEARCH_INTERVAL)
        while True:
            try:
                time_input = input(f"请输入新的检查间隔（秒，当前{current_val}，回车不修改）: ").strip()
                if not time_input: break
                new_time_val = ConfigModel.validate_search_time(time_input)
                current_config_dict["time"] = new_time_val
                self.logger.log(f"临时配置中检查间隔已更新为: {new_time_val}秒", LogLevel.INFO)
                break
            except ValueError as e: print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

    def _update_pushplus_interactive(self, current_config_dict: Dict[str, Any]):
        current_val = current_config_dict.get("pushplus", "")
        new_val = input(f"请输入新的PushPlus令牌（当前: '{current_val}', 回车不修改, 输入 'none' 清空）: ").strip()
        if new_val.lower() == 'none':
            current_config_dict["pushplus"] = ""
            self.logger.log("临时配置中PushPlus令牌已清空。", LogLevel.INFO)
        elif new_val:
            current_config_dict["pushplus"] = new_val
            self.logger.log("临时配置中PushPlus令牌已更新。", LogLevel.INFO)

    def _update_remark_interactive(self, current_config_dict: Dict[str, Any]):
        current_val = current_config_dict.get("remark", "自动签到配置")
        new_val = input(f"请输入新的备注信息（当前: '{current_val}', 回车不修改）: ").strip()
        if new_val:
            current_config_dict["remark"] = new_val
        elif not new_val and not current_val:
            current_config_dict["remark"] = "自动签到配置"
        if new_val or (not new_val and not current_val):
            self.logger.log(f"临时配置中备注信息已更新为: '{current_config_dict['remark']}'", LogLevel.INFO)

    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"字段 '{err['loc'][0]}': {err['msg']}" for err in error.errors()]
        self.logger.log("配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

# === 签到任务 ===
class SignTask:
    def __init__(self, config: Dict[str, Any], logger_instance: LoggerInterface, stats_reporter_instance: StatisticsReporter):
        self.config = config
        self.logger = logger_instance
        self.stats_reporter = stats_reporter_instance
        self.invalid_sign_ids: Set[str] = set()
        self.signed_ids: Set[str] = set()
        self._running = True
        self._control_thread: Optional[threading.Thread] = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread_lock = threading.Lock()
        self._active_threads = []
        self._shutdown_hook_registered = False

    def _register_shutdown_hook(self):
        """注册关闭钩子以确保线程清理"""
        if not self._shutdown_hook_registered:
            atexit.register(self._cleanup_on_exit)
            self._shutdown_hook_registered = True

    def _cleanup_on_exit(self):
        """退出时的清理操作"""
        if self._running:
            self._running = False
            self._pause_event.set()
            self._cleanup_threads()

    def _register_thread(self, thread: threading.Thread):
        """注册线程以便正确清理"""
        with self._thread_lock:
            self._active_threads.append(thread)
            self._register_shutdown_hook()

    def _unregister_thread(self, thread: threading.Thread):
        """注销线程"""
        with self._thread_lock:
            try:
                self._active_threads.remove(thread)
            except ValueError:
                pass

    def _cleanup_threads(self):
        """清理所有活动线程"""
        with self._thread_lock:
            for thread in self._active_threads[:]:
                if thread.is_alive():
                    try:
                        thread.join(timeout=AppConstants.THREAD_JOIN_TIMEOUT)
                        if thread.is_alive():
                            logger.log(f"线程 {thread.name} 未能及时终止", LogLevel.WARNING)
                    except Exception as e:
                        logger.log(f"终止线程 {thread.name} 时出错: {e}", LogLevel.WARNING)
            self._active_threads.clear()

    def run(self):
        """增强的run方法，确保线程安全"""
        self._setup_control_thread()
        try:
            while self._running:
                self._pause_event.wait()
                if not self._running:
                    break
                self._pause_event.clear()

                if self._should_run_now():
                    self._execute_sign_cycle()
                else:
                    self._log_waiting_message()

                if not self._running:
                    break
                self._wait_for_next_cycle()
        except KeyboardInterrupt:
            self.logger.log("用户中断程序 (Ctrl+C 在签到任务中)。", LogLevel.INFO)
            self._running = False
        except Exception as e:
            self.logger.log(f"签到任务发生未捕获异常: {e}", LogLevel.CRITICAL)
            self._running = False
        finally:
            self.logger.log("签到任务正在清理和退出...", LogLevel.INFO)
            self._running = False
            self._pause_event.set()
            self._cleanup_control_thread()
            self._cleanup_threads()
            logger.log("所有线程已清理完毕", LogLevel.INFO)

    def _setup_control_thread(self):
        """设置控制线程并注册"""
        self._control_thread = threading.Thread(
            target=self._monitor_commands,
            daemon=True,
            name="CommandMonitorThread"
        )
        self._control_thread.start()
        self._register_thread(self._control_thread)

    def _monitor_commands(self):
        """增强的命令监控线程"""
        thread = threading.current_thread()
        try:
            while self._running:
                if sys.stdin.isatty():
                    cmd = input("\n(签到运行中) 命令 (q=退出, s=立即执行, c=状态): ").strip().lower()
                else:
                    time.sleep(5)
                    if not self._running:
                        break
                    continue

                if not self._running:
                    break

                if cmd == 'q':
                    self.logger.log("收到退出命令 'q'。", LogLevel.INFO)
                    self._running = False
                    self._pause_event.set()
                    break
                elif cmd == 's':
                    self.logger.log("\n🔍 收到立即签到命令 's'...", LogLevel.INFO)
                    self._pause_event.set()
                elif cmd == 'c':
                    self._show_status()
        except Exception as e:
            if self._running:
                logger.log(f"命令监听线程出错: {e}", LogLevel.ERROR)
        finally:
            self._unregister_thread(thread)

    def _cleanup_control_thread(self):
        """增强的线程清理"""
        if self._control_thread and self._control_thread.is_alive():
            self.logger.log("等待命令监听线程退出...", LogLevel.DEBUG)
            self._control_thread.join(timeout=AppConstants.THREAD_JOIN_TIMEOUT)
            if self._control_thread.is_alive():
                logger.log("命令监听线程未能及时退出", LogLevel.WARNING)
            self._unregister_thread(self._control_thread)
            self._control_thread = None

    def _show_status(self):
        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== 当前签到状态 ==={Style.RESET_ALL}")
        print(f"✅ 已成功签到ID (本次运行): {self.signed_ids if self.signed_ids else '无'}")
        print(f"❌ 密码错误/无效ID (本次运行): {self.invalid_sign_ids if self.invalid_sign_ids else '无'}")
        if self.config.get('enable_time_range', False):
            st, et = self.config.get('start_time', '??:??'), self.config.get('end_time', '??:??')
            print(f"⏰ 运行时间段: {st} 至 {et}" + 
                  (f"{Fore.YELLOW} (当前不在运行时间段内){Style.RESET_ALL}" if not self._should_run_now() else ""))
        else: print("⏰ 运行时间段: 全天候运行")
        interval = self.config.get('time', AppConstants.DEFAULT_SEARCH_INTERVAL)
        print(f"⏱️ 检查间隔: {interval} 秒 (下次大致在: {(datetime.now() + timedelta(seconds=interval)).strftime('%H:%M:%S')})")
        print(f"🏃 程序运行状态: {'运行中' if self._running else '正在停止'}")

    def _should_run_now(self) -> bool:
        if not self.config.get('enable_time_range', False): return True
        try:
            now_time = datetime.now().time()
            start_time = datetime.strptime(self.config.get('start_time', '08:00'), '%H:%M').time()
            end_time = datetime.strptime(self.config.get('end_time', '22:00'), '%H:%M').time()
            return start_time <= now_time <= end_time
        except ValueError as e:
            self.logger.log(f"检查运行时间段时格式错误: {e}. 默认允许运行。", LogLevel.ERROR)
            return True
        except Exception as e:
            self.logger.log(f"检查运行时间段时未知错误: {e}. 默认允许运行。", LogLevel.ERROR)
            return True

    def _log_waiting_message(self) -> None:
        current_time_str = datetime.now().strftime('%H:%M')
        start_t, end_t = self.config.get('start_time', '08:00'), self.config.get('end_time', '22:00')
        self.logger.log(f"⏳ 当前时间 {current_time_str} 不在运行时间段 ({start_t}-{end_t})，等待中...", LogLevel.INFO)

    def _wait_for_next_cycle(self) -> bool:
        interval = self.config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL)
        self.logger.log(f"⏳ 等待下次检索，间隔: {interval}秒. (按 Enter 或输入命令 s c q)", LogLevel.INFO)
        woken_by_event = self._pause_event.wait(timeout=float(interval))
        if woken_by_event:
            self.logger.log("等待被事件中断 (例如：立即执行或退出命令)。", LogLevel.DEBUG)
        return self._running

    def _execute_sign_cycle(self) -> None:
        self.logger.log(f"🚀 开始新一轮签到任务检索，时间: {datetime.now().strftime('%H:%M:%S')}", LogLevel.INFO)
        try:
            sign_ids_found = self._fetch_sign_ids()
            if not sign_ids_found:
                self.logger.log("ℹ️ 本轮未找到有效签到任务ID。", LogLevel.INFO)
                return

            processed_count = 0
            for sign_id in sign_ids_found:
                if not self._running: break
                self._process_sign_id(sign_id)
                processed_count +=1
            
            if processed_count == 0 and sign_ids_found:
                self.logger.log("ℹ️ 本轮找到的签到任务均已处理或不适用。", LogLevel.INFO)

        except requests.RequestException as e:
            self.logger.log(f"❌ 签到周期网络请求出错: {e}", LogLevel.ERROR)
        except Exception as e:
            self.logger.log(f"❌ 执行签到周期时发生未知错误: {e}", LogLevel.ERROR)

    def _fetch_sign_ids(self) -> List[str]:
        class_id_val = self.config.get("class_id")
        if not class_id_val:
            self.logger.log("配置中缺少 class_id，无法获取签到任务。", LogLevel.ERROR)
            return []
        url = f'http://k8n.cn/student/course/{class_id_val}/punchs'
        headers = self._build_headers()
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        self.logger.log(f"获取签到列表响应状态码: {response.status_code}", LogLevel.DEBUG)
        extracted_ids = self._extract_sign_ids_from_html(response.text)
        self.logger.log(f"从HTML提取到的签到ID: {extracted_ids}", LogLevel.DEBUG)
        return extracted_ids

    def _extract_sign_ids_from_html(self, html: str) -> List[str]:
        pattern = r'punch_gps\((\d+)\)|punchcard_(\d+)'
        matches = re.findall(pattern, html)
        sign_ids = [group for match_tuple in matches for group in match_tuple if group]
        return list(set(sign_ids))

    def _process_sign_id(self, sign_id: str) -> None:
        if not sign_id.isdigit():
            self.logger.log(f"⚠️ 跳过格式无效的签到ID: {sign_id}", LogLevel.WARNING)
            return
        if sign_id in self.invalid_sign_ids:
            self.logger.log(f"ℹ️ 跳过已知无效或需密码的签到ID: {sign_id}", LogLevel.DEBUG)
            return
        if sign_id in self.signed_ids:
            self.logger.log(f"ℹ️ 跳过已成功签到的ID: {sign_id}", LogLevel.DEBUG)
            return
        self.logger.log(f"⏳ 尝试处理签到ID: {sign_id}", LogLevel.INFO)
        self._attempt_sign(sign_id)

    def _attempt_sign(self, sign_id: str) -> None:
        class_id_val = self.config.get("class_id")
        if not class_id_val:
            self.logger.log(f"无法签到ID {sign_id}，配置中缺少class_id。", LogLevel.ERROR)
            return

        url = f'http://k8n.cn/student/punchs/course/{class_id_val}/{sign_id}'
        headers = self._build_headers()
        payload = {'id': sign_id, 'lat': self.config["lat"], 'lng': self.config["lng"], 
                   'acc': self.config["acc"], 'res': '', 'gps_addr': ''}
        max_retries = 2; retry_delay = 3

        for attempt in range(1, max_retries + 1):
            if not self._running: return
            try:
                self.logger.log(f"向 {url} 发送签到POST (尝试 {attempt}/{max_retries}) ID: {sign_id}", LogLevel.DEBUG)
                response = requests.post(url, headers=headers, data=payload, timeout=10)
                response.raise_for_status()
                if not response.text.strip():
                    self.logger.log(f"签到ID {sign_id} 响应为空 (尝试 {attempt})。", LogLevel.WARNING)
                    if attempt < max_retries: time.sleep(retry_delay); continue
                    else: raise ValueError(f"签到ID {sign_id} 多次响应为空。")
                
                self._handle_sign_response(response.text, sign_id)
                return
            except requests.RequestException as e:
                self.logger.log(f"❌ 签到ID {sign_id} 请求出错 (尝试 {attempt}/{max_retries}): {e}", LogLevel.ERROR)
                if attempt == max_retries: 
                    self.stats_reporter.report_event("sign_in_failure_network", {"id": sign_id, "error": str(e)})
                time.sleep(retry_delay)
            except ValueError as ve:
                 self.logger.log(f"❌ 签到ID {sign_id} 处理错误: {ve}", LogLevel.ERROR)
                 self.stats_reporter.report_event("sign_in_failure_empty_response", {"id": sign_id})
                 break 
            except Exception as e:
                self.logger.log(f"❌ 处理签到ID {sign_id} 时未知错误: {e}", LogLevel.ERROR)
                self.stats_reporter.report_event("sign_in_failure_unknown", {"id": sign_id, "error": str(e)})
                break

    def _handle_sign_response(self, html: str, sign_id: str) -> None:
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('div', id='title')
        if not title_tag:
            self.logger.log(f"❌ 无法从ID {sign_id} 的响应中解析结果 (未找到 #title)。响应: {html[:100]}", LogLevel.ERROR)
            self.stats_reporter.report_event("sign_in_failure_parse_error", {"id": sign_id})
            return

        result_text = title_tag.text.strip()
        is_success_flag = False

        if "签到密码错误" in result_text:
            self.logger.log(f"⚠️ ID {sign_id} 需密码: '{result_text}'. 忽略此ID.", LogLevel.WARNING)
            self.invalid_sign_ids.add(sign_id)
            self.stats_reporter.report_event("sign_in_failure_password", {"id": sign_id})
        elif "我已签到过啦" in result_text or "您已签到" in result_text:
            self.logger.log(f"ℹ️ ID {sign_id} 已签到过: '{result_text}'.", LogLevel.INFO)
            self.signed_ids.add(sign_id)
        elif "成功" in result_text:
            self.logger.log(f"✅ ID {sign_id} 签到成功: '{result_text}'", LogLevel.INFO)
            self.signed_ids.add(sign_id)
            self.stats_reporter.report_event("sign_in_success", {"id": sign_id})
            is_success_flag = True
        else:
            self.logger.log(f"🔍 ID {sign_id} 结果: '{result_text}' (未明确成功，需人工判断)", LogLevel.WARNING)
            self.stats_reporter.report_event("sign_in_unknown_result", {"id": sign_id, "result_text": result_text[:30]})

        self._send_notification(result_text, sign_id, is_success_flag)

    def _send_notification(self, result: str, sign_id: str, is_success: bool) -> None:
        pushplus_token = self.config.get("pushplus")
        if not pushplus_token: return

        title_text = f"✅签到成功通知 [{self.config.get('remark','自动签到')}]" if is_success \
                else f"⚠️签到通知 [{self.config.get('remark','自动签到')}]"
        
        content_body = f"""
**结果**: {result}
**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**班级ID**: {self.config.get("class_id", "N/A")}
**签到ID**: {sign_id}
"""
        if not is_success:
            content_body += "\n**提示**: 若为失败或未知结果，请检查配置(坐标/Cookie)或查看日志。"
        
        push_payload = {
            "token": pushplus_token,
            "title": title_text,
            "content": content_body.strip(),
            "template": "markdown"
        }
        push_url = 'http://www.pushplus.plus/send'
        try:
            self.logger.log(f"发送PushPlus通知: {title_text}", LogLevel.DEBUG)
            response = requests.post(push_url, json=push_payload, timeout=10)
            response.raise_for_status()
            resp_data = response.json()
            if resp_data.get("code") == 200:
                self.logger.log("PushPlus通知发送成功。", LogLevel.INFO)
            else:
                self.logger.log(f"PushPlus API错误: {resp_data.get('msg', '未知错误')}", LogLevel.ERROR)
        except requests.RequestException as e:
            self.logger.log(f"❌ 推送PushPlus消息时网络出错: {e}", LogLevel.ERROR)
        except json.JSONDecodeError:
            self.logger.log(f"❌ 推送PushPlus后无法解析响应: {response.text[:100]}", LogLevel.ERROR)

    def _build_headers(self) -> Dict[str, str]:
        class_id_val = self.config.get("class_id")
        referer = f'http://k8n.cn/student/course/{class_id_val}' if class_id_val else 'http://k8n.cn/student/'
        return {
            'User-Agent': self._generate_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'X-Requested-With': 'com.tencent.mm', 'Referer': referer,
            'Accept-Encoding': 'gzip, deflate', 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cookie': self.config.get("cookie","")
        }

    def _generate_user_agent(self) -> str:
        android_versions = ["10", "11", "12", "13", "14"]
        devices = ["MI 9", "HUAWEI P40", "OPPO R17", "vivo X27", "Samsung Galaxy S21", "Google Pixel 6"]
        build_numbers = ["QKQ1.190828.002", "P40.201012.005", "R17.200515.003", "X27.210303.001", "GD1A.220019.007"]
        chrome_versions = ["92.0.4515.107", "100.0.4896.127", "108.0.5359.128", "114.0.5735.196"]
        wechat_versions = ["8.0.30", "8.0.32", "8.0.33", "8.0.34", "8.0.35"]
        net_types = ["WIFI", "4G", "5G"]
        return AppConstants.USER_AGENT_TEMPLATE.format(
            android_version=random.choice(android_versions), device=random.choice(devices),
            build_number=random.choice(build_numbers), chrome_version=random.choice(chrome_versions),
            wechat_version=random.choice(wechat_versions), net_type=random.choice(net_types)
        )

# === 主程序入口 ===
def main_entry_point():
    # --- Remote Config Handling ---
    remote_fetcher = RemoteConfigFetcher(
        urls=AppConstants.REMOTE_CONFIG_URLS,
        cache_file=AppConstants.REMOTE_CONFIG_CACHE_FILE,
        cache_duration=AppConstants.REMOTE_CONFIG_CACHE_DURATION
    )
    remote_config = remote_fetcher.fetch_config()

    stats_reporter.set_remote_config(remote_config)
    stats_reporter.report_script_start()

    if remote_config:
        script_control_cfg = remote_config.get("script_control", {})
        if script_control_cfg.get("globally_disabled", False):
            disabled_msg = script_control_cfg.get("disabled_message", "此脚本已被管理员远程禁用。")
            logger.log(disabled_msg, LogLevel.CRITICAL)
            print(f"{Fore.RED}{Style.BRIGHT}🚨 {disabled_msg} 🚨{Style.RESET_ALL}")
            sys.exit(20)

        update_h = UpdateHandler(AppConstants.CURRENT_SCRIPT_VERSION, remote_config)
        update_h.check_for_updates()

        announcement_d = AnnouncementDisplayer(remote_config, AppConstants.ANNOUNCEMENT_HISTORY_FILE)
        announcement_d.display_announcement()
    else:
        logger.log("未能获取远程配置。部分远程控制功能 (如全局禁用、强制更新、公告) 将不可用。", LogLevel.WARNING)
        logger.log("脚本将继续使用本地缓存的远程配置 (如果存在且有效) 或完全本地模式运行。", LogLevel.WARNING)

    # --- Welcome Message ---
    print("\n" + "="*50)
    print(f"{Fore.GREEN}{Style.BRIGHT}🌟 自动签到系统 v{AppConstants.CURRENT_SCRIPT_VERSION} 🌟{Style.RESET_ALL}")
    print("="*50)
    print("使用说明 (在程序运行时输入):")
    print("- q: 退出程序")
    print("- s: 立即执行一次签到检查")
    print("- c: 查看当前签到任务状态")
    print("="*50 + "\n")
    
    # --- Core Components Initialization ---
    storage = JsonConfigStorage()
    config_manager = ConfigManager(storage, logger, remote_config_data=remote_config)
    
    updater = ConfigUpdater(config_manager, logger)
    active_config = updater.init_config()
    
    if not active_config:
        logger.log("❌ 配置未能成功初始化或加载，程序退出。", LogLevel.CRITICAL)
        sys.exit(1)
    
    # --- Display Config Summary & Start Task ---
    logger.log(f"\n{Fore.GREEN}✅ 配置加载/更新完成！开始监控签到任务...{Style.RESET_ALL}", LogLevel.INFO)
    logger.log(f"{Fore.CYAN}当前生效配置摘要:{Style.RESET_ALL}", LogLevel.INFO)
    logger.log(f"- 班级ID: {active_config['class_id']}", LogLevel.INFO)
    logger.log(f"- 检查间隔: 每 {active_config['time']} 秒", LogLevel.INFO)
    if active_config.get('enable_time_range', False):
        logger.log(f"- 运行时间段: {active_config.get('start_time','N/A')} 至 {active_config.get('end_time','N/A')}", LogLevel.INFO)
    else: logger.log("- 运行时间段: 全天候运行", LogLevel.INFO)
    logger.log("\n系统正在运行中...\n", LogLevel.INFO)
    
    sign_task_instance = SignTask(config=active_config, logger_instance=logger, stats_reporter_instance=stats_reporter)
    sign_task_instance.run()
    
    logger.log("主签到任务已结束。", LogLevel.INFO)

if __name__ == "__main__":
    exit_code = 0
    try:
        main_entry_point()
    except KeyboardInterrupt:
        logger.log(f"\n{Fore.YELLOW}👋 程序被用户强制退出 (顶层Ctrl+C)。{Style.RESET_ALL}", LogLevel.INFO)
        exit_code = 130
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 1
        if exit_code == 0:
            logger.log(f"{Fore.GREEN}程序正常退出。{Style.RESET_ALL}", LogLevel.INFO)
        elif exit_code == 10:
            pass
        elif exit_code == 20:
            pass
        else:
            logger.log(f"{Fore.RED}程序因特定原因退出，代码: {exit_code}{Style.RESET_ALL}", LogLevel.WARNING)
    except Exception as e:
        logger.log(f"\n{Fore.RED}{Style.BRIGHT}❌ 程序顶层发生未捕获的严重错误: {e}{Style.RESET_ALL}", LogLevel.CRITICAL)
        import traceback
        logger.log(f"Traceback:\n{traceback.format_exc()}", LogLevel.ERROR)
        exit_code = 1
    finally:
        logger.log(f"程序最终关闭。退出代码: {exit_code}", LogLevel.INFO)
        if 'colorama' in sys.modules: colorama.deinit()
        sys.exit(exit_code)
