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
from datetime import datetime
from abc import ABC, abstractmethod
from pydantic import BaseModel, field_validator, ValidationError
from typing import Dict, List, Set, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
import threading
from copy import deepcopy
from datetime import timedelta

# 初始化 colorama
colorama.init(autoreset=True)

# === 常量定义 ===
class AppConstants:
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

# === 日志系统 ===
class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()

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
            LogLevel.ERROR: Fore.RED
        }
        self.icon_map = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌"
        }

    def _setup_log_directory(self) -> None:
        if not os.path.exists(AppConstants.LOG_DIR):
            try:
                os.makedirs(AppConstants.LOG_DIR)
            except OSError as e:
                print(f"{Fore.RED}创建日志目录失败: {e}{Style.RESET_ALL}")

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level.name}] {message}\n"

        # 控制台输出
        if "--silent" not in sys.argv:
            color = self.color_map.get(level, "")
            icon = self.icon_map.get(level, "")
            print(f"{color}{icon} [{timestamp}] {message}{Style.RESET_ALL}")

        # 文件记录
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except IOError as e:
            print(f"{Fore.RED}[{timestamp}] [ERROR] 写入日志文件时出错: {e}{Style.RESET_ALL}")

# === 配置模型 ===
class ConfigModel(BaseModel):
    cookie: str
    class_id: str
    lat: str
    lng: str
    acc: str
    time: int = 60
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
            lat = float(v)
            if not -90 <= lat <= 90:
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
            lng = float(v)
            if not -180 <= lng <= 180:
                raise ValueError("经度需在 -180 到 180 之间")
            return v
        except ValueError:
            raise ValueError("经度必须是有效数字")

    @field_validator('acc')
    @classmethod
    def validate_altitude(cls, v: str) -> str:
        if not v:
            raise ValueError("海拔不能为空")
        try:
            float(v)
            return v
        except ValueError:
            raise ValueError("海拔必须是有效数字")

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

# === 配置管理器 ===
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
                "enable_time_range": False,
                "start_time": "08:00",
                "end_time": "22:00",
                "pushplus": ""
            }
            config = {**defaults, **raw_config}

            # 验证必填字段
            for field in AppConstants.REQUIRED_FIELDS:
                if field not in config or not config[field]:
                    raise ValueError(f"缺少必填字段: {field}")

            try:
                return ConfigModel(**config).model_dump()
            except ValidationError as e:
                self._handle_validation_error(e)
                return {}
        except FileNotFoundError:
            self.storage.save(defaults)
            return defaults
        except ValueError as e:
            self.logger.log(f"配置加载错误: {e}", LogLevel.ERROR)
            return {}

    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"{err['loc'][0]}: {err['msg']}" for err in error.errors()]
        self.logger.log("配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

    def save(self) -> None:
        try:
            self.storage.save(self._config)
            self.logger.log("配置保存成功", LogLevel.INFO)
        except ValueError as e:
            self.logger.log(f"保存配置时出错: {e}", LogLevel.ERROR)

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
        self.max_attempts = 20
        self.check_interval = 2
        self.classid = None

    def fetch_qr_code_url(self):
        print(f"{Fore.CYAN}正在获取二维码链接...{Style.RESET_ALL}")
        try:
            response = self.session.get(self.base_url, headers=self.headers)
            if response.status_code == 200:
                pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=[^"]+'
                match = re.search(pattern, response.text)
                if match:
                    qr_code_url = match.group(0)
                    print(f"{Fore.GREEN}成功获取二维码链接{Style.RESET_ALL}")
                    return qr_code_url
        except requests.RequestException as e:
            print(f"{Fore.RED}获取二维码链接出错: {e}{Style.RESET_ALL}")
        print(f"{Fore.RED}未找到二维码链接{Style.RESET_ALL}")
        return None

    def display_qr_code(self, qr_code_url):
        print(f"{Fore.CYAN}准备显示二维码...{Style.RESET_ALL}")
        try:
            response = self.session.get(qr_code_url)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                img = img.resize((260, 260), Image.LANCZOS)

                root = tk.Tk()
                root.title("微信登录二维码")
                window_width = 320
                window_height = 400
                root.geometry(f"{window_width}x{window_height}")
                root.resizable(False, False)
                root.geometry("+100+100")
                root.attributes('-topmost', True)
                root.after(10, lambda: root.attributes('-topmost', True))

                main_frame = tk.Frame(root, padx=20, pady=20)
                main_frame.pack(expand=True, fill=tk.BOTH)

                photo = ImageTk.PhotoImage(img)
                img_frame = tk.Frame(main_frame, bd=2, relief=tk.GROOVE)
                img_frame.pack(pady=(0, 15))
                tk.Label(img_frame, image=photo).pack(padx=5, pady=5)

                tk.Label(
                    main_frame,
                    text="请使用微信扫描二维码登录",
                    font=("Microsoft YaHei", 12),
                    fg="#333"
                ).pack(pady=(0, 10))

                tk.Label(
                    main_frame,
                    text="拖动标题栏可移动窗口",
                    font=("Microsoft YaHei", 9),
                    fg="#666"
                ).pack()

                main_frame.image = photo

                def start_move(event):
                    root.x = event.x
                    root.y = event.y

                def stop_move(event):
                    root.x = None
                    root.y = None

                def do_move(event):
                    x = root.winfo_x() + (event.x - root.x)
                    y = root.winfo_y() + (event.y - root.y)
                    root.geometry(f"+{x}+{y}")

                main_frame.bind("<ButtonPress-1>", start_move)
                main_frame.bind("<ButtonRelease-1>", stop_move)
                main_frame.bind("<B1-Motion>", do_move)

                root.after(100, root.focus_force)
                root.after(0, self.check_login_status, root, 0)
                root.mainloop()
                return True
            else:
                print(f"{Fore.RED}无法显示二维码，请手动复制以下URL到浏览器:{Style.RESET_ALL}")
                print(qr_code_url)
        except Exception as e:
            print(f"{Fore.RED}发生错误: {e}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}请手动复制以下URL到浏览器:{Style.RESET_ALL}")
            print(qr_code_url)
        return False

    def check_login_status(self, root, attempt):
        if attempt >= self.max_attempts:
            print(f"{Fore.RED}超过最大尝试次数，登录检查失败{Style.RESET_ALL}")
            root.destroy()
            return False
        check_url = f"{self.base_url}?op=checklogin"
        try:
            response = self.session.get(check_url, headers=self.headers)
            print(f"{Fore.CYAN}第 {attempt + 1} 次检查登录状态，状态码: {response.status_code}{Style.RESET_ALL}")
            data = response.json()
            if data.get('status'):
                print(f"{Fore.GREEN}登录成功{Style.RESET_ALL}")
                self.handle_successful_login(response, data)
                root.destroy()
                return True
        except Exception as e:
            print(f"{Fore.RED}第 {attempt + 1} 次登录检查出错: {str(e)}{Style.RESET_ALL}")
        root.after(self.check_interval * 1000, self.check_login_status, root, attempt + 1)
        return None

    def handle_successful_login(self, initial_response, data):
        print(f"{Fore.CYAN}处理登录成功后的操作...{Style.RESET_ALL}")
        self.extract_and_set_cookies(initial_response)
        new_url = 'https://k8n.cn' + data['url']
        self.send_follow_up_request(new_url)
        cookies = self.get_required_cookies()
        print(f"{Fore.GREEN}获取到Cookies{Style.RESET_ALL}")

    def extract_and_set_cookies(self, response):
        set_cookies = response.headers.get('Set-Cookie')
        if set_cookies:
            if isinstance(set_cookies, str):
                set_cookies = [set_cookies]
            for set_cookie in set_cookies:
                pattern = r'remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=([^;]+)'
                match = re.search(pattern, set_cookie)
                if match:
                    cookie_value = match.group(1)
                    print(f"{Fore.GREEN}提取到Cookie{Style.RESET_ALL}")

    def send_follow_up_request(self, url):
        print(f"{Fore.CYAN}发送跟进请求...{Style.RESET_ALL}")
        try:
            response = self.session.get(url, headers=self.headers)
            self.extract_and_set_cookies(response)
        except requests.RequestException as e:
            print(f"{Fore.RED}跟进请求出错: {e}{Style.RESET_ALL}")

    def get_required_cookies(self):
        cookies = self.session.cookies.get_dict()
        return {
            'remember_student': cookies.get("remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d")
        }

    def fetch_logged_in_data(self):
        print(f"{Fore.CYAN}获取登录后数据...{Style.RESET_ALL}")
        data_url = 'http://k8n.cn/student'
        try:
            response = self.session.get(data_url, headers=self.headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                class_ids = self._extract_class_ids(response.text)
                
                if not class_ids:
                    print(f"{Fore.RED}未找到任何班级信息{Style.RESET_ALL}")
                    return {"status": "error"}
                
                print(f"{Fore.GREEN}班级信息：{Style.RESET_ALL}")
                for idx, class_id in enumerate(class_ids, start=1):
                    print(f"  {idx}. {class_id}")
                
                if len(class_ids) == 1:
                    self.classid = class_ids[0]
                    print(f"{Fore.GREEN}自动选择 classid: {self.classid}{Style.RESET_ALL}")
                else:
                    while True:
                        try:
                            choice = int(input("请输入要使用的班级序号: ")) - 1
                            if 0 <= choice < len(class_ids):
                                self.classid = class_ids[choice]
                                print(f"{Fore.GREEN}已选择 classid: {self.classid}{Style.RESET_ALL}")
                                break
                            else:
                                print(f"{Fore.RED}输入的序号无效{Style.RESET_ALL}")
                        except ValueError:
                            print(f"{Fore.RED}输入无效，请输入数字{Style.RESET_ALL}")
                
                scanned_cookie = self.session.cookies.get('remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d')
                if scanned_cookie:
                    scanned_cookie = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={scanned_cookie}"
                    print(f"{Fore.GREEN}扫码获取成功{Style.RESET_ALL}")
                
                return {
                    "status": "success",
                    "classid": self.classid,
                    "cookie": scanned_cookie
                }
            else:
                print(f"{Fore.RED}请求失败，状态码: {response.status_code}{Style.RESET_ALL}")
                return {"status": "error"}
        except requests.RequestException as e:
            print(f"{Fore.RED}获取数据出错: {e}{Style.RESET_ALL}")
            return {"status": "error"}

    def _extract_class_ids(self, html: str) -> List[str]:
        """从HTML中提取所有班级ID"""
        soup = BeautifulSoup(html, 'html.parser')
        return [div.get('course_id') 
                for div in soup.find_all('div', class_='card mb-3 course') 
                if div.get('course_id')]

# === 配置更新器 ===
class ConfigUpdater:
    def __init__(self, config_manager: ConfigManager, logger: LoggerInterface):
        self.manager = config_manager
        self.logger = logger
        self.login_system = QRLoginSystem()
        self.scanned_class_ids = []
        self.scanned_cookie = None

    def init_config(self) -> Dict[str, Any]:
        """首次运行自动进入配置向导"""
        if not self._validate_config():
            self.logger.log("配置无效或首次运行，进入配置向导", LogLevel.INFO)
            return self._first_run_config_wizard()
        
        self._show_current_config()
        if self._should_update_config():
            return self._update_config_interactively()
        
        return self.manager.config

    def _first_run_config_wizard(self) -> Dict[str, Any]:
        """首次运行配置向导"""
        print(f"\n{Fore.GREEN}🌟 欢迎使用自动签到系统 🌟{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}这是您首次运行，需要进行初始配置{Style.RESET_ALL}")
        print("="*50)
        
        # 第一步：优先推荐扫码登录
        config = self._setup_login_method()
        
        # 第二步：补充位置信息
        self._setup_location_info(config)
        
        # 第三步：其他设置
        self._setup_other_settings(config)
        
        # 验证并保存配置
        try:
            validated_config = ConfigModel(**config).model_dump()
            self.manager.config = validated_config
            self.manager.save()
            print(f"\n{Fore.GREEN}✅ 初始配置完成！{Style.RESET_ALL}")
            return validated_config
        except ValidationError as e:
            self._handle_validation_error(e)
            return self._first_run_config_wizard()

    def _setup_login_method(self) -> Dict[str, Any]:
        """设置登录方式（优先扫码）"""
        print(f"\n{Fore.CYAN}=== 第一步：登录方式设置 ==={Style.RESET_ALL}")
        print("请选择获取Cookie和班级ID的方式：")
        print(f"1. {Fore.GREEN}扫码登录（推荐）{Style.RESET_ALL}")
        print("2. 手动输入")
        
        while True:
            choice = input("\n请选择(1/2，默认1): ").strip() or "1"
            
            if choice == "1":
                if self._scan_and_update():
                    return {
                        "cookie": self.scanned_cookie,
                        "class_id": self.scanned_class_ids[0] if self.scanned_class_ids else ""
                    }
                else:
                    print(f"{Fore.RED}扫码登录失败，请选择其他方式{Style.RESET_ALL}")
            elif choice == "2":
                return self._manual_input_credentials()
            else:
                print(f"{Fore.RED}无效输入，请选择1或2{Style.RESET_ALL}")

    def _scan_and_update(self) -> bool:
        """执行扫码登录流程"""
        for attempt in range(1, 4):
            try:
                print(f"\n🔄 尝试获取二维码 (第 {attempt} 次)...")
                qr_url = self.login_system.fetch_qr_code_url()
                if not qr_url:
                    continue
                    
                print("✅ 二维码获取成功，正在显示...")
                if not self.login_system.display_qr_code(qr_url):
                    print("⚠️ 二维码显示失败，请尝试手动复制以下URL到浏览器:")
                    print(qr_url)
                    continue
                    
                print("\n⏳ 正在等待扫码登录...")
                result = self.login_system.fetch_logged_in_data()
                
                if result["status"] == "success":
                    self.scanned_cookie = result["cookie"]
                    self.scanned_class_ids = [result["classid"]]
                    
                    print("\n✅ 登录成功！获取到以下信息:")
                    print(f"- 班级ID: {result['classid']}")
                    cookie_display = f"{self.scanned_cookie[:15]}...{self.scanned_cookie[-15:]}" if len(self.scanned_cookie) > 30 else self.scanned_cookie
                    print(f"- Cookie: {cookie_display}")
                    return True
                    
            except Exception as e:
                print(f"⚠️ 第 {attempt} 次扫码尝试失败: {str(e)}")
                
            if attempt < 3:
                if input("\n扫码未成功，是否重试？(y/n): ").lower() != 'y':
                    break
                
        print("\n❌ 扫码登录失败，请尝试手动输入配置")
        return False

    def _manual_input_credentials(self) -> Dict[str, Any]:
        """手动输入凭证信息"""
        print(f"\n{Fore.YELLOW}⚠️ 请手动输入必要信息{Style.RESET_ALL}")
        config = {}
        
        # 使用验证器确保输入有效
        config["cookie"] = self._get_validated_input(
            "请输入Cookie: ",
            ConfigModel.validate_cookie,
            is_required=True
        )
        
        config["class_id"] = self._get_validated_input(
            "请输入班级ID: ",
            ConfigModel.validate_class_id,
            is_required=True
        )
        
        return config

    def _get_validated_input(self, prompt: str, validator: Callable, is_required: bool = False) -> str:
        """获取并验证用户输入"""
        while True:
            try:
                value = input(prompt).strip()
                if is_required and not value:
                    raise ValueError("该字段为必填项")
                if value:
                    return validator(value)
                return value
            except ValueError as e:
                print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

    def _setup_location_info(self, config: Dict[str, Any]) -> None:
        """设置位置信息"""
        print(f"\n{Fore.CYAN}=== 第二步：位置信息设置 ==={Style.RESET_ALL}")
        print("请提供您常用的签到位置坐标：")
        
        config["lat"] = self._get_validated_input(
            "请输入纬度（如39.9042）: ",
            ConfigModel.validate_latitude,
            is_required=True
        )
        
        config["lng"] = self._get_validated_input(
            "请输入经度（如116.4074）: ",
            ConfigModel.validate_longitude,
            is_required=True
        )
        
        config["acc"] = self._get_validated_input(
            "请输入海拔（如50.0）: ",
            ConfigModel.validate_altitude,
            is_required=True
        )

    def _setup_other_settings(self, config: Dict[str, Any]) -> None:
        """设置其他选项"""
        print(f"\n{Fore.CYAN}=== 第三步：其他设置 ==={Style.RESET_ALL}")
        
        # 检查间隔
        while True:
            try:
                time_input = input(
                    f"请输入检查间隔（秒，默认{AppConstants.DEFAULT_SEARCH_INTERVAL}）: "
                ).strip()
                config["time"] = int(time_input) if time_input else AppConstants.DEFAULT_SEARCH_INTERVAL
                ConfigModel.validate_search_time(config["time"])
                break
            except ValueError as e:
                print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")
        
        # PushPlus通知
        config["pushplus"] = input("请输入PushPlus令牌（可选）: ").strip()
        
        # 时间段控制
        self._setup_time_range(config)
        
        # 备注信息
        config["remark"] = input("请输入备注信息（可选）: ").strip() or "自动签到配置"

    def _setup_time_range(self, config: Dict[str, Any]) -> None:
        """设置运行时间段"""
        enable = input("是否启用时间段控制？(y/n, 默认n): ").strip().lower() == 'y'
        
        config["enable_time_range"] = enable
        
        if enable:
            print("请设置运行时间段（格式: HH:MM）")
            while True:
                try:
                    start = input("开始时间（如08:00）: ").strip()
                    end = input("结束时间（如22:00）: ").strip()
                    
                    # 验证时间格式
                    datetime.strptime(start, '%H:%M')
                    datetime.strptime(end, '%H:%M')
                    
                    if start >= end:
                        raise ValueError("开始时间必须早于结束时间")
                        
                    config["start_time"] = start
                    config["end_time"] = end
                    break
                except ValueError as e:
                    print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

    def _validate_config(self) -> bool:
        try:
            ConfigModel(**self.manager.config)
            return True
        except ValidationError:
            return False

    def _show_current_config(self) -> None:
        """显示当前配置信息"""
        config = self.manager.config
        self.logger.log("\n📋 当前配置信息", LogLevel.INFO)
        self.logger.log("--------------------------------", LogLevel.INFO)
        
        cookie_display = config["cookie"]
        if len(cookie_display) > 30:
            cookie_display = f"{cookie_display[:15]}...{cookie_display[-15:]}"
        
        config_items = [
            ("班级ID", config["class_id"]),
            ("纬度", config["lat"]),
            ("经度", config["lng"]),
            ("海拔", config["acc"]),
            ("检查间隔", f"{config['time']}秒"),
            ("Cookie", cookie_display),
            ("PushPlus", config["pushplus"] or "未设置"),
            ("备注", config["remark"]),
            ("时间段控制", "已启用" if config["enable_time_range"] else "已禁用")
        ]
        
        if config["enable_time_range"]:
            config_items.append(("运行时间段", f"{config['start_time']} 至 {config['end_time']}"))
        
        for name, value in config_items:
            self.logger.log(f"🔹 {name.ljust(10)}: {value}", LogLevel.INFO)
        
        self.logger.log("--------------------------------", LogLevel.INFO)

    def _should_update_config(self) -> bool:
        """询问用户是否要更新配置（10秒超时自动选择默认值n）"""
        print("\n是否要修改当前配置？(y/n, 默认n): ", end='', flush=True)
        
        # 设置超时时间（秒）
        timeout = 10
        default_choice = 'n'
        user_input = [default_choice]  # 使用列表以便在嵌套函数中修改
        
        def get_input():
            try:
                user_input[0] = input().strip().lower() or default_choice
            except:
                pass  # 忽略所有输入异常
        
        # 创建并启动输入线程
        input_thread = threading.Thread(target=get_input)
        input_thread.daemon = True
        input_thread.start()
        
        # 等待线程结束或超时
        input_thread.join(timeout)
        
        # 如果线程还在运行（超时），则终止它
        if input_thread.is_alive():
            print(f"\n{Fore.YELLOW}输入超时，自动选择默认值 '{default_choice}'{Style.RESET_ALL}")
            # 由于input()是阻塞的，我们需要强制结束控制台输入
            # 在Windows和Linux/macOS上方法不同
            try:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()  # 清空输入缓冲区
            except:
                pass  # 非Windows系统忽略
        
        return user_input[0] == 'y'

    def _update_config_interactively(self) -> Dict[str, Any]:
        """交互式更新配置"""
        original_config = deepcopy(self.manager.config)
        
        try:
            # 1. 首先询问是否要修改cookie和class_id
            self._update_cookie_and_class_id()
            
            # 2. 显示当前配置并询问是否继续修改其他项
            self._show_current_config()
            
            # 3. 提供选择性修改各项配置
            while True:
                print("\n🔧 请选择要修改的配置项:")
                print("1. 位置信息 (纬度/经度/海拔)")
                print("2. 检查间隔时间")
                print("3. PushPlus通知设置")
                print("4. 备注信息")
                print("5. 运行时间段设置")
                print("6. 查看当前所有配置")
                print("0. 完成配置")
                
                choice = input("\n请输入要修改的选项编号 (0-6, 默认0): ").strip() or "0"
                
                if choice == "0":
                    break
                elif choice == "1":
                    print("\n📍 更新位置信息")
                    self._update_coordinates()
                elif choice == "2":
                    print("\n⏱️ 更新检查间隔")
                    self._update_search_interval()
                elif choice == "3":
                    print("\n📨 更新PushPlus设置")
                    self._update_pushplus()
                elif choice == "4":
                    print("\n📝 更新备注信息")
                    self._update_remark()
                elif choice == "5":
                    print("\n⏰ 更新时间段设置")
                    self._update_time_range_setting()
                elif choice == "6":
                    self._show_current_config()
                else:
                    print("⚠️ 无效的选项，请重新输入")
            
            # 确认保存
            self._show_current_config()
            if input("\n确认保存以上配置？(y/n, 默认y): ").strip().lower() or 'y' == 'y':
                try:
                    ConfigModel(**self.manager.config)
                    self.manager.save()
                    print("✅ 配置保存成功！")
                    return self.manager.config
                except ValidationError as e:
                    self._handle_validation_error(e)
                    return self._update_config_interactively()
            else:
                self.manager.config = original_config
                print("🔄 已恢复原始配置")
                return self._update_config_interactively()
                
        except Exception as e:
            self.manager.config = original_config
            self.logger.log(f"配置过程中出错: {e}", LogLevel.ERROR)
            raise

    def _update_cookie_and_class_id(self):
        """更新cookie和class_id"""
        print("\n🛠️ 更新登录凭证")
        choice = input("是否要更新Cookie和班级ID？(y/n, 默认n): ").strip().lower() or 'n'
        if choice == 'y':
            self._setup_login_method()

    def _update_coordinates(self):
        """更新坐标信息"""
        self._setup_location_info(self.manager.config)

    def _update_search_interval(self):
        """更新检查间隔"""
        while True:
            try:
                time_input = input(
                    f"请输入新的检查间隔（秒，当前{self.manager.config.get('time', 60)}）: "
                ).strip()
                new_time = int(time_input) if time_input else self.manager.config.get('time', 60)
                ConfigModel.validate_search_time(new_time)
                self.manager.config["time"] = new_time
                break
            except ValueError as e:
                print(f"{Fore.RED}错误: {e}{Style.RESET_ALL}")

    def _update_pushplus(self):
        """更新PushPlus设置"""
        self.manager.config["pushplus"] = input("请输入新的PushPlus令牌（当前: {}）: ".format(
            self.manager.config.get("pushplus", "")
        )).strip()

    def _update_remark(self):
        """更新备注信息"""
        self.manager.config["remark"] = input("请输入新的备注信息（当前: {}）: ".format(
            self.manager.config.get("remark", "")
        )).strip() or "自动签到配置"

    def _update_time_range_setting(self):
        """更新时间段设置"""
        self._setup_time_range(self.manager.config)

    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"{err['loc'][0]}: {err['msg']}" for err in error.errors()]
        self.logger.log("配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

# === 签到任务 ===
class SignTask:
    def __init__(self, config: Dict[str, Any], logger: LoggerInterface):
        self.config = config
        self.logger = logger
        self.invalid_sign_ids: Set[str] = set()
        self.signed_ids: Set[str] = set()
        self._running = True
        self._control_thread = None

    def run(self) -> None:
        self._setup_control_thread()
        
        try:
            while self._running:
                if self._should_run_now():
                    self._execute_sign_cycle()
                else:
                    self._log_waiting_message()
                
                self._wait_for_next_cycle()
        except KeyboardInterrupt:
            self.logger.log("用户中断程序", LogLevel.INFO)
        finally:
            self._cleanup_control_thread()

    def _should_run_now(self) -> bool:
        """检查当前是否应该运行签到任务"""
        if not self.config.get('enable_time_range', False):
            return True
            
        try:
            now = datetime.now()
            current_time = now.strftime('%H:%M')
            start_time = self.config.get('start_time', '08:00')
            end_time = self.config.get('end_time', '22:00')
            return start_time <= current_time <= end_time
        except Exception as e:
            self.logger.log(f"检查时间段出错: {e}", LogLevel.ERROR)
            return True

    def _log_waiting_message(self) -> None:
        """记录等待日志"""
        current_time = datetime.now().strftime('%H:%M')
        start_time = self.config.get('start_time', '08:00')
        end_time = self.config.get('end_time', '22:00')
        self.logger.log(
            f"⏳ 当前时间 {current_time} 不在运行时间段内 ({start_time}-{end_time})，等待中...",
            LogLevel.INFO
        )

    def _setup_control_thread(self):
        self._control_thread = threading.Thread(
            target=self._monitor_commands,
            daemon=True
        )
        self._control_thread.start()

    def _monitor_commands(self):
        while self._running:
            try:
                cmd = input("\n输入命令 (q=退出, s=立即签到, c=检查状态): ").strip().lower()
                if cmd == 'q':
                    self._running = False
                    print("\n🛑 正在停止程序...")
                elif cmd == 's':
                    print("\n🔍 立即执行签到检查...")
                    self._execute_sign_cycle()
                elif cmd == 'c':
                    self._show_status()
                else:
                    print("⚠️ 未知命令，可用命令: q=退出, s=立即签到, c=检查状态")
            except (EOFError, KeyboardInterrupt):
                continue

    def _show_status(self):
        print(f"\n{Fore.CYAN}=== 当前状态 ==={Style.RESET_ALL}")
        print(f"✅ 已签到ID: {self.signed_ids}")
        print(f"❌ 无效签到ID: {self.invalid_sign_ids}")
        if self.config.get('enable_time_range', False):
            print(f"⏰ 运行时间段: {self.config.get('start_time', '08:00')} 至 {self.config.get('end_time', '22:00')}")
        else:
            print("⏰ 运行时间段: 全天候运行")
        print(f"⏱️ 下次检查: {datetime.now() + timedelta(seconds=self.config.get('time', 60))}")

    def _cleanup_control_thread(self):
        if self._control_thread and self._control_thread.is_alive():
            self._control_thread.join(timeout=1)

    def _execute_sign_cycle(self) -> None:
        self.logger.log(f"🔍 开始检索签到任务，当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", LogLevel.INFO)

        try:
            sign_ids = self._fetch_sign_ids()
            if not sign_ids:
                self.logger.log("ℹ️ 本次未找到有效签到任务", LogLevel.INFO)
                return

            for sign_id in sign_ids:
                self._process_sign_id(sign_id)
        except requests.RequestException as e:
            self.logger.log(f"❌ 网络请求出错: {e}", LogLevel.ERROR)

    def _fetch_sign_ids(self) -> List[str]:
        url = f'http://k8n.cn/student/course/{self.config["class_id"]}/punchs'
        headers = self._build_headers()

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        self.logger.log(f"ℹ️ 请求响应状态码: {response.status_code}", LogLevel.INFO)
        sign_ids = self._extract_sign_ids(response.text)
        self.logger.log(f"🔍 找到的签到ID: {sign_ids}", LogLevel.INFO)

        return sign_ids

    def _extract_sign_ids(self, html: str) -> List[str]:
        pattern = r'punch_gps\((\d+)\)|punchcard_(\d+)'
        matches = re.findall(pattern, html)
        sign_ids = [group for match in matches for group in match if group]
        return list(set(sign_ids))

    def _process_sign_id(self, sign_id: str) -> None:
        if not sign_id.isdigit():
            self.logger.log(f"⚠️ 跳过无效签到ID格式: {sign_id}", LogLevel.WARNING)
            return

        if sign_id in self.invalid_sign_ids:
            self.logger.log(f"ℹ️ 跳过需要密码的签到ID: {sign_id}", LogLevel.INFO)
            return

        if sign_id in self.signed_ids:
            self.logger.log(f"ℹ️ 跳过已签到的ID: {sign_id}", LogLevel.INFO)
            return

        self.logger.log(f"🔍 处理签到ID: {sign_id}", LogLevel.INFO)
        self._attempt_sign(sign_id)

    def _attempt_sign(self, sign_id: str) -> None:
        url = f'http://k8n.cn/student/punchs/course/{self.config["class_id"]}/{sign_id}'
        headers = self._build_headers()
        payload = {
            'id': sign_id,
            'lat': self.config["lat"],
            'lng': self.config["lng"],
            'acc': self.config["acc"],
            'res': '',
            'gps_addr': ''
        }

        max_retries = 3
        retry_delay = 5
        
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, headers=headers, data=payload, timeout=10)
                response.raise_for_status()
                
                if not response.text:
                    raise ValueError("空响应内容")
                    
                self._handle_sign_response(response.text, sign_id)
                return
                
            except requests.RequestException as e:
                self.logger.log(
                    f"❌ 签到请求出错 (尝试 {attempt}/{max_retries}): {str(e)}", 
                    LogLevel.ERROR
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    self.logger.log(
                        f"❌ 达到最大重试次数 ({max_retries})，放弃签到ID: {sign_id}", 
                        LogLevel.ERROR
                    )
            except Exception as e:
                self.logger.log(
                    f"❌ 处理签到响应时出错: {str(e)}", 
                    LogLevel.ERROR
                )
                break

    def _handle_sign_response(self, html: str, sign_id: str) -> None:
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('div', id='title')
        if not title_tag:
            self.logger.log("❌ 无法解析签到响应", LogLevel.ERROR)
            return

        result = title_tag.text.strip()

        if "签到密码错误" in result:
            self.logger.log(f"⚠️ 不支持密码签到: {result}，将忽略此ID {sign_id}", LogLevel.WARNING)
            self.invalid_sign_ids.add(sign_id)
        elif "我已签到过啦" in result:
            self.logger.log(f"ℹ️ 已签到: {result}，不再处理此ID {sign_id}", LogLevel.INFO)
            self.signed_ids.add(sign_id)
        else:
            self.logger.log(f"✅ 签到结果: {result}", LogLevel.INFO)
            self._send_notification(result, sign_id)

    def _send_notification(self, result: str, sign_id: str) -> None:
        if not self.config.get("pushplus"):
            return

        is_success = "成功" in result
        title = "签到成功通知" if is_success else "签到失败通知"
        content = f"""
{'🎉 签到成功' if is_success else '❌ 签到失败'}!
- 班级ID: {self.config["class_id"]}
- 签到ID: {sign_id}
- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 结果: {result}
"""

        if not is_success:
            content += "\n可能原因: 请检查坐标信息或Cookie是否正确"

        try:
            push_url = (
                f'http://www.pushplus.plus/send?token={self.config["pushplus"]}'
                f'&title={title}&content={content}'
            )
            requests.get(push_url, timeout=10).raise_for_status()
        except requests.RequestException as e:
            self.logger.log(f"❌ 推送消息出错: {e}", LogLevel.ERROR)

    def _build_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': self._generate_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'X-Requested-With': 'com.tencent.mm',
            'Referer': f'http://k8n.cn/student/course/{self.config["class_id"]}',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh-SG;q=0.9,zh;q=0.8,en-SG;q=0.7,en-US;q=0.6,en;q=0.5',
            'Cookie': self.config["cookie"]
        }

    def _generate_user_agent(self) -> str:
        android_versions = ["9", "10", "11", "12", "13", "14"]
        devices = ["MI 9", "HUAWEI P40", "OPPO R17", "vivo X27", "Samsung Galaxy S21", "Google Pixel 6", "OnePlus 9"]
        build_numbers = ["QKQ1.190828.002", "HUAWEIP40", "OPPOR17", "vivoX27", "S21U1.210811.001", "Pixel6A.211203.017",
                         "LE2117_11_C.16"]
        chrome_versions = ["88.0.4324.150", "89.0.4389.105", "90.0.4430.210", "91.0.4472.120", "92.0.4515.107",
                           "93.0.4577.63"]
        wechat_versions = ["8.0.23", "8.0.24", "8.0.25", "8.0.26", "8.0.27", "8.0.28"]
        net_types = ["WIFI", "2G", "3G", "4G", "5G"]

        return AppConstants.USER_AGENT_TEMPLATE.format(
            android_version=random.choice(android_versions),
            device=random.choice(devices),
            build_number=random.choice(build_numbers),
            chrome_version=random.choice(chrome_versions),
            wechat_version=random.choice(wechat_versions),
            net_type=random.choice(net_types)
        )

    def _wait_for_next_cycle(self) -> bool:
        interval = self.config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL)
        self.logger.log(f"⏳ 等待下次检索，间隔: {interval}秒", LogLevel.INFO)
        
        start_time = time.time()
        while time.time() - start_time < interval and self._running:
            time.sleep(1)
            if not self._running:
                return False
        return True

# === 主程序入口 ===
if __name__ == "__main__":
    try:
        # 显示欢迎信息
        print("\n" + "="*50)
        print(f"{Fore.GREEN}{Style.BRIGHT}🌟 自动签到系统 v1.0 🌟{Style.RESET_ALL}")
        print("="*50)
        print(f"{Fore.CYAN}欢迎使用自动签到系统{Style.RESET_ALL}")
        print("="*50)
        print("使用说明:")
        print("- 按 q 退出程序")
        print("- 按 s 立即签到")
        print("- 按 c 查看状态")
        print("="*50 + "\n")
        
        # 初始化核心组件
        logger = FileLogger()
        storage = JsonConfigStorage()
        config_manager = ConfigManager(storage, logger)
        
        # 配置检查与初始化
        updater = ConfigUpdater(config_manager, logger)
        config = updater.init_config()
        
        if not config:
            print(f"\n{Fore.RED}❌ 配置失败，程序退出{Style.RESET_ALL}")
            sys.exit(1)
        
        # 显示配置摘要
        print(f"\n{Fore.GREEN}✅ 配置完成！开始监控签到任务...{Style.RESET_ALL}")
        print(f"{Fore.CYAN}当前配置摘要:{Style.RESET_ALL}")
        print(f"- 班级ID: {config['class_id']}")
        print(f"- 检查间隔: 每 {config['time']} 秒")
        
        if config.get('enable_time_range', False):
            print(f"- 运行时间段: {config.get('start_time', '08:00')} 至 {config.get('end_time', '22:00')}")
        else:
            print("- 运行时间段: 全天候运行")
            
        print("\n系统正在运行中...\n")
        
        # 启动签到任务
        SignTask(config=config, logger=logger).run()
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}👋 程序已退出{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Fore.RED}❌ 程序出错: {e}{Style.RESET_ALL}")
        sys.exit(1)
