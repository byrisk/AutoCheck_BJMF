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
import msvcrt

# 初始化 colorama
colorama.init(autoreset=True)

# === 常量定义 ===
class AppConstants:
    REQUIRED_FIELDS: Tuple[str, ...] = ("class_id", "cookie", "lat", "lng", "acc")
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
        'enable_time_range': False,  # 默认不启用时间段控制
        'start_time': '08:00',     # 默认开始时间
        'end_time': '22:00'        # 默认结束时间
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

    def _setup_log_directory(self) -> None:
        if not os.path.exists(AppConstants.LOG_DIR):
            try:
                os.makedirs(AppConstants.LOG_DIR)
            except OSError as e:
                print(f"{Fore.RED}创建日志目录失败: {e}{Style.RESET_ALL}")

    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level.name}] {message}\n"

        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except IOError as e:
            print(f"{Fore.RED}[{timestamp}] [ERROR] 写入日志文件时出错: {e}{Style.RESET_ALL}")

        if "--silent" not in sys.argv:
            color_map = {
                LogLevel.INFO: Fore.GREEN,
                LogLevel.WARNING: Fore.YELLOW,
                LogLevel.ERROR: Fore.RED,
                LogLevel.DEBUG: Fore.CYAN
            }
            color = color_map.get(level, "")
            print(f"{color}[{timestamp}] [{level.name}] {message}{Style.RESET_ALL}")

# === 配置系统 ===
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

class ConfigModel(BaseModel):
    class_id: str
    lat: str
    lng: str
    acc: str
    time: int = 60
    cookie: str
    pushplus: str = ""
    remark: str = "自动签到配置"
    enable_time_range: bool = False  # 是否启用时间段控制
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
    def validate_search_time(cls, v: str) -> int:
        try:
            v = int(v)
            if v <= 0:
                raise ValueError("检索间隔必须为正整数")
            return v
        except ValueError:
            raise ValueError("检索间隔必须为有效的正整数")

    @field_validator('start_time', 'end_time')
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError("时间格式必须为 HH:MM")

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
            config = {
                "class_id": raw_config.get("class_id") or raw_config.get("class", ""),
                "lat": raw_config.get("lat", ""),
                "lng": raw_config.get("lng", ""),
                "acc": raw_config.get("acc", ""),
                "time": raw_config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL),
                "cookie": raw_config.get("cookie", ""),
                "pushplus": raw_config.get("pushplus", ""),
                "remark": raw_config.get("remark", "自动签到配置"),
                "enable_time_range": raw_config.get("enable_time_range", AppConstants.DEFAULT_RUN_TIME['enable_time_range']),
                "start_time": raw_config.get("start_time", AppConstants.DEFAULT_RUN_TIME['start_time']),
                "end_time": raw_config.get("end_time", AppConstants.DEFAULT_RUN_TIME['end_time'])
            }

            try:
                return ConfigModel(**config).model_dump()
            except ValidationError as e:
                self._handle_validation_error(e)
                return {}
        except FileNotFoundError:
            self.storage.save({})
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
        print("正在获取二维码链接...")
        try:
            response = self.session.get(self.base_url, headers=self.headers)
            if response.status_code == 200:
                pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=[^"]+'
                match = re.search(pattern, response.text)
                if match:
                    qr_code_url = match.group(0)
                    print(f"成功获取二维码链接: {qr_code_url}")
                    return qr_code_url
        except requests.RequestException as e:
            print(f"获取二维码链接出错: {e}")
        print("未找到二维码链接")
        return None

    def display_qr_code(self, qr_code_url):
        print("准备显示二维码...")
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
                print("无法显示二维码，请手动复制以下URL到浏览器:")
                print(qr_code_url)
        except Exception as e:
            print(f"发生错误: {e}")
            print("请手动复制以下URL到浏览器:")
            print(qr_code_url)
        return False

    def check_login_status(self, root, attempt):
        if attempt >= self.max_attempts:
            print("超过最大尝试次数，登录检查失败")
            root.destroy()
            return False
        check_url = f"{self.base_url}?op=checklogin"
        try:
            response = self.session.get(check_url, headers=self.headers)
            print(f"第 {attempt + 1} 次检查登录状态，状态码: {response.status_code}")
            data = response.json()
            if data.get('status'):
                print("登录成功")
                self.handle_successful_login(response, data)
                root.destroy()
                return True
        except Exception as e:
            print(f"第 {attempt + 1} 次登录检查出错: {str(e)}")
        root.after(self.check_interval * 1000, self.check_login_status, root, attempt + 1)
        return None

    def handle_successful_login(self, initial_response, data):
        print("处理登录成功后的操作...")
        self.extract_and_set_cookies(initial_response)
        new_url = 'https://k8n.cn' + data['url']
        self.send_follow_up_request(new_url)
        cookies = self.get_required_cookies()
        print(f"获取到Cookies: {cookies}")

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
                    print(f"提取到Cookie: {cookie_value}")

    def send_follow_up_request(self, url):
        print("发送跟进请求...")
        try:
            response = self.session.get(url, headers=self.headers)
            self.extract_and_set_cookies(response)
        except requests.RequestException as e:
            print(f"跟进请求出错: {e}")

    def get_required_cookies(self):
        cookies = self.session.cookies.get_dict()
        return {
            'remember_student': cookies.get("remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d")
        }

    def fetch_logged_in_data(self):
        print("获取登录后数据...")
        data_url = 'http://k8n.cn/student'
        try:
            response = self.session.get(data_url, headers=self.headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                class_info_list = []
                for card in soup.find_all('div', class_='card mb-3 course'):
                    course_id = card.get('course_id')
                    if course_id:
                        course_name = card.find('h5', class_='course_name').text.strip() if card.find('h5', class_='course_name') else "未知课程名称"
                        class_name = card.find('p', style="color: #fff").text.strip() if card.find('p', style="color: #fff") else "未知班级名称"
                        class_code = card.find('span', style="float: right").text.split(' ')[-1].strip() if card.find('span', style="float: right") else "未知班级码"

                        class_info_list.append({
                            '课程 ID': course_id,
                            '班级名称': class_name,
                            '课程名称': course_name,
                            '班级码': class_code
                        })
                    else:
                        print("未找到有效的 course_id 属性")

                if not class_info_list:
                    print("未找到任何班级信息")
                    return {"status": "error"}
                else:
                    print("班级信息：")
                    for idx, info in enumerate(class_info_list, start=1):
                        print(f"  班级 {idx}: 课程 ID: {info['课程 ID']} 班级名称: {info['班级名称']} 课程名称: {info['课程名称']} 班级码: {info['班级码']}")

                    all_classids = [info['课程 ID'] for info in class_info_list]
                    print(f"所有 classid: {all_classids}")

                    if len(all_classids) == 0:
                        print("未找到有效的 classid")
                        return {"status": "error"}
                    elif len(all_classids) == 1:
                        self.classid = all_classids[0]
                        print(f"自动选择 classid: {self.classid}")
                    else:
                        while True:
                            try:
                                print("请选择要使用的 classid：")
                                for idx, classid in enumerate(all_classids, start=1):
                                    print(f"{idx}. {classid}")
                                choice = int(input("请输入对应的序号: ")) - 1
                                if 0 <= choice < len(all_classids):
                                    self.classid = all_classids[choice]
                                    print(f"已选择 classid: {self.classid}")
                                    scanned_cookie = self.session.cookies.get('remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d')
                                    if scanned_cookie:
                                        scanned_cookie = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={scanned_cookie}"
                                        if len(scanned_cookie) > 20:
                                            displayed_cookie = f"{scanned_cookie[:10]}...{scanned_cookie[-10:]}"
                                        else:
                                            displayed_cookie = scanned_cookie
                                            print(f"扫码获取成功")
                                        print(f"配置的 cookie: {displayed_cookie}")
                                    print(f"配置的 classid: {self.classid}")
                                    break
                                else:
                                    print("输入的序号无效")
                            except ValueError:
                                print("输入无效，请输入数字")

                    return {"status": "success", "classid": self.classid}
            else:
                print(f"请求失败，状态码: {response.status_code}")
                return {"status": "error"}
        except requests.RequestException as e:
            print(f"获取数据出错: {e}")
            return {"status": "error"}

# === 配置更新器 ===
class ConfigUpdater:
    def __init__(self, config_manager: ConfigManager, logger: LoggerInterface):
        self.manager = config_manager
        self.logger = logger
        self.login_system = QRLoginSystem()
        self.scanned_class_ids = []
        self.scanned_cookie = None

    def init_config(self) -> Dict[str, Any]:
        if not self.manager.config or not self._validate_config():
            self.logger.log("配置无效，需要重新配置", LogLevel.ERROR)
            return self._update_config_interactively()

        self._show_current_config()
        if self._should_update_config():
            return self._update_config_interactively()

        return self.manager.config

    def _validate_config(self) -> bool:
        try:
            ConfigModel(**self.manager.config)
            return True
        except ValidationError as e:
            self._handle_validation_error(e)
            return False

    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"{err['loc'][0]}: {err['msg']}" for err in error.errors()]
        self.logger.log("配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

    def _show_current_config(self) -> None:
        self.logger.log("---------- 当前配置信息 ----------", LogLevel.INFO)
        for key, value in self.manager.config.items():
            display_value = value if key not in ["cookie", "pushplus"] else "[已隐藏]"
            self.logger.log(f"{key}: {display_value}", LogLevel.INFO)
        self.logger.log("--------------------------------", LogLevel.INFO)

    def _get_user_choice_with_timeout(self, prompt: str, choices: Tuple[str, ...], 
                                   default: Optional[str] = None, 
                                   timeout: int = 10) -> str:
        """
        Windows专用带超时的用户选择输入
        :param prompt: 提示信息
        :param choices: 可选值列表
        :param default: 默认值
        :param timeout: 超时时间(秒)
        :return: 用户选择或默认值
        """
        print(prompt, end='', flush=True)
        start_time = time.time()
        
        while True:
            # 检查是否有按键输入
            if msvcrt.kbhit():
                char = msvcrt.getwch().lower()  # 获取输入字符并转为小写
                if char in choices:
                    print(char)  # 回显用户输入
                    return char
                elif char == '\r' and default:  # 回车键使用默认值
                    print(default)
                    return default
            
            # 检查是否超时
            if time.time() - start_time > timeout:
                print(f"\n{Fore.YELLOW}输入超时，自动选择默认值 '{default}'{Style.RESET_ALL}")
                return default
            
            time.sleep(0.1)  # 避免CPU占用过高

    def _should_update_config(self) -> bool:
        """Windows专用：检查是否需要更新配置，10秒无输入默认返回False"""
        return self._get_user_choice_with_timeout(
            "当前配置有效。是否修改配置？(y/n, 默认n): ",
            ('y', 'n'),
            default='n',
            timeout=10
        ) == 'y'

    def _update_time_range_setting(self) -> None:
        """更新时间段控制设置"""
        current_setting = self.manager.config.get('enable_time_range', False)
        print(f"\n当前时间段控制状态: {'已启用' if current_setting else '已禁用'}")
        
        if self._get_user_choice("是否修改时间段控制? (y/n, 默认n): ", ('y', 'n'), default='n') == 'y':
            enable = self._get_user_choice("启用时间段控制? (y/n, 默认n): ", ('y', 'n'), default='n') == 'y'
            self.manager.config['enable_time_range'] = enable
            
            if enable:
                self._update_field("start_time", ConfigModel.validate_time_format)
                self._update_field("end_time", ConfigModel.validate_time_format)
                print(f"已设置运行时间段: {self.manager.config['start_time']} 至 {self.manager.config['end_time']}")
            else:
                print("已禁用时间段控制，程序将全天候运行")

    def _update_config_interactively(self) -> Dict[str, Any]:
        self.logger.log("开始交互式配置更新", LogLevel.INFO)
        original_config = deepcopy(self.manager.config)
        
        try:
            self._update_cookie_and_class_id()
            self._update_coordinates()
            self._update_search_interval()
            self._update_pushplus()
            self._update_remark()
            self._update_time_range_setting()  # 更新时间段控制设置

            self._show_current_config()
            if self._get_user_choice("确认保存配置? (y/n, 默认y): ", ('y', 'n'), default='y') != 'y':
                self.manager.config = original_config
                return self._update_config_interactively()

            try:
                ConfigModel(**self.manager.config)
                self.manager.save()
                return self.manager.config
            except ValidationError as e:
                self._handle_validation_error(e)
                return self._update_config_interactively()
        except Exception as e:
            self.manager.config = original_config
            raise

    def _get_user_input(self, prompt: str, validator: Callable[[str], Any], required: bool = False) -> str:
        while True:
            try:
                value = input(prompt).strip()
                if required and not value:
                    raise ValueError("该字段为必填项")
                if value:
                    return validator(value)
                return value
            except ValueError as e:
                self.logger.log(f"{e}，请重新输入", LogLevel.ERROR)
            except (EOFError, KeyboardInterrupt):
                self.logger.log("\n输入中断，请重新输入", LogLevel.ERROR)

    def _get_user_choice(self, prompt: str, choices: Tuple[str, ...], default: Optional[str] = None) -> str:
        while True:
            choice = input(prompt).strip().lower()
            if not choice and default:
                return default
            if choice in choices:
                return choice
            print(f"\033[31m请输入 {' 或 '.join(choices)}\033[0m")

    def _update_cookie_and_class_id(self):
        current_cookie = self.manager.config.get("cookie", "")
        current_class_id = self.manager.config.get("class_id", "")

        if not current_cookie or not current_class_id:
            message = "当前 cookie 或 class_id 无效或缺失，选择获取方式：(1. 扫码, 2. 手动输入, 默认扫码): "
        elif self._ask_update_choice(current_cookie, current_class_id):
            message = "选择获取方式：(1. 扫码, 2. 手动输入, 默认扫码): "
        else:
            return

        choice = self._get_user_choice(message, ('1', '2'), default='1')
        if choice == '1':
            success = self._scan_and_update()
            if not success:
                print("扫码获取失败，将进行手动输入。")
                self._update_required_fields()
        else:
            self._update_required_fields()

    def _ask_update_choice(self, current_cookie: str, current_class_id: str) -> bool:
        display_cookie = current_cookie if not current_cookie else "[已隐藏]"
        display_class_id = current_class_id
        return self._get_user_choice(f"当前 cookie 为: {display_cookie}，class_id 为: {display_class_id}，是否修改？(y/n, 默认n): ", ('y', 'n'), default='n') == 'y'

    def _scan_and_update(self):
        for attempt in range(1, 4):
            try:
                qr_url = self.login_system.fetch_qr_code_url()
                if not qr_url:
                    continue
                    
                if not self.login_system.display_qr_code(qr_url):
                    continue
                    
                result = self.login_system.fetch_logged_in_data()
                if result["status"] == "success":
                    self.scanned_cookie = self.login_system.session.cookies.get(
                        'remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d')
                    self.scanned_cookie = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={self.scanned_cookie}"
                    self.scanned_class_ids = [self.login_system.classid]
                    selected_class_id = self._select_class_id()
                    self.manager.config["class_id"] = selected_class_id
                    self.manager.config["cookie"] = self.scanned_cookie
                    return True
            except Exception as e:
                self.logger.log(f"第 {attempt} 次扫码尝试失败: {e}", LogLevel.ERROR)
                
            if attempt < 3:
                if self._get_user_choice("扫码未成功，是否重试? (y/n): ", ('y', 'n')) != 'y':
                    break
        return False

    def _select_class_id(self) -> str:
        return self.login_system.classid

    def _update_required_fields(self):
        self._update_field("cookie", ConfigModel.validate_cookie, is_required=True)
        self._update_field("class_id", ConfigModel.validate_class_id, is_required=True)

    def _update_field(self, field: str, validator: Callable[[str], Any], is_required: bool = False) -> None:
        prompt = f"请输入 {field}{' [必填]' if is_required else ''}: "
        self.manager.config[field] = self._get_user_input(prompt, validator, required=is_required)

    def _update_coordinates(self) -> None:
        self._update_field("lat", ConfigModel.validate_latitude, is_required=True)
        self._update_field("lng", ConfigModel.validate_longitude, is_required=True)
        self._update_field("acc", ConfigModel.validate_altitude, is_required=True)

    def _update_search_interval(self) -> None:
        self._update_field("time", ConfigModel.validate_search_time, is_required=True)

    def _update_pushplus(self) -> None:
        self._update_field("pushplus", lambda x: x)

    def _update_remark(self) -> None:
        self._update_field("remark", lambda x: x)

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
            return True  # 如果未启用时间段控制，则始终返回True
            
        try:
            now = datetime.now()
            current_time = now.strftime('%H:%M')
            
            start_time = self.config.get('start_time', '08:00')
            end_time = self.config.get('end_time', '22:00')
            
            return start_time <= current_time <= end_time
        except Exception as e:
            self.logger.log(f"检查时间段出错: {e}", LogLevel.ERROR)
            return True  # 出错时默认允许运行

    def _log_waiting_message(self) -> None:
        """记录等待日志"""
        current_time = datetime.now().strftime('%H:%M')
        start_time = self.config.get('start_time', '08:00')
        end_time = self.config.get('end_time', '22:00')
        self.logger.log(
            f"当前时间 {current_time} 不在运行时间段内 ({start_time}-{end_time})，等待中...",
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
                cmd = input("输入命令 (q=退出, s=立即签到, c=检查状态): \n").strip().lower()
                if cmd == 'q':
                    self._running = False
                elif cmd == 's':
                    self._execute_sign_cycle()
                elif cmd == 'c':
                    self._show_status()
            except (EOFError, KeyboardInterrupt):
                continue

    def _show_status(self):
        print(f"\n{Fore.CYAN}=== 当前状态 ==={Style.RESET_ALL}")
        print(f"已签到ID: {self.signed_ids}")
        print(f"无效签到ID: {self.invalid_sign_ids}")
        if self.config.get('enable_time_range', False):
            print(f"运行时间段: {self.config.get('start_time', '08:00')} 至 {self.config.get('end_time', '22:00')}")
        else:
            print("运行时间段: 全天候运行")
        print(f"下次检查: {datetime.now() + timedelta(seconds=self.config.get('time', 60))}")

    def _cleanup_control_thread(self):
        if self._control_thread and self._control_thread.is_alive():
            self._control_thread.join(timeout=1)

    def _execute_sign_cycle(self) -> None:
        self.logger.log(f"开始检索签到任务，当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", LogLevel.INFO)

        try:
            sign_ids = self._fetch_sign_ids()
            if not sign_ids:
                self.logger.log("本次未找到有效签到任务", LogLevel.INFO)
                return

            for sign_id in sign_ids:
                self._process_sign_id(sign_id)
        except requests.RequestException as e:
            self.logger.log(f"网络请求出错: {e}", LogLevel.ERROR)

    def _fetch_sign_ids(self) -> List[str]:
        url = f'http://k8n.cn/student/course/{self.config["class_id"]}/punchs'
        headers = self._build_headers()

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        self.logger.log(f"请求响应状态码: {response.status_code}", LogLevel.INFO)
        sign_ids = self._extract_sign_ids(response.text)
        self.logger.log(f"找到的签到ID: {sign_ids}", LogLevel.INFO)

        return sign_ids

    def _extract_sign_ids(self, html: str) -> List[str]:
        pattern = r'punch_gps\((\d+)\)|punchcard_(\d+)'
        matches = re.findall(pattern, html)
        sign_ids = [group for match in matches for group in match if group]
        return list(set(sign_ids))

    def _process_sign_id(self, sign_id: str) -> None:
        if not sign_id.isdigit():
            self.logger.log(f"跳过无效签到ID格式: {sign_id}", LogLevel.WARNING)
            return

        if sign_id in self.invalid_sign_ids:
            self.logger.log(f"跳过需要密码的签到ID: {sign_id}", LogLevel.INFO)
            return

        if sign_id in self.signed_ids:
            self.logger.log(f"跳过已签到的ID: {sign_id}", LogLevel.INFO)
            return

        self.logger.log(f"处理签到ID: {sign_id}", LogLevel.INFO)
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

        try:
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response.raise_for_status()
            self._handle_sign_response(response.text, sign_id)
        except requests.RequestException as e:
            self.logger.log(f"签到请求出错: {e}", LogLevel.ERROR)

    def _handle_sign_response(self, html: str, sign_id: str) -> None:
        soup = BeautifulSoup(html, 'html.parser')
        title_tag = soup.find('div', id='title')
        if not title_tag:
            self.logger.log("无法解析签到响应", LogLevel.ERROR)
            return

        result = title_tag.text.strip()

        if "签到密码错误" in result:
            self.logger.log(f"不支持密码签到: {result}，将忽略此ID {sign_id}", LogLevel.WARNING)
            self.invalid_sign_ids.add(sign_id)
        elif "我已签到过啦" in result:
            self.logger.log(f"已签到: {result}，不再处理此ID {sign_id}", LogLevel.INFO)
            self.signed_ids.add(sign_id)
        else:
            self.logger.log(f"签到结果: {result}", LogLevel.INFO)
            self._send_notification(result, sign_id)

    def _send_notification(self, result: str, sign_id: str) -> None:
        if not self.config.get("pushplus"):
            return

        is_success = "成功" in result
        title = "签到成功通知" if is_success else "签到失败通知"
        content = f"""
{'签到成功' if is_success else '签到失败'}!
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
            self.logger.log(f"推送消息出错: {e}", LogLevel.ERROR)

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
        self.logger.log(f"等待下次检索，间隔: {interval}秒", LogLevel.INFO)
        
        start_time = time.time()
        while time.time() - start_time < interval and self._running:
            time.sleep(1)
            if not self._running:
                return False
        return True

# === 主程序入口 ===
if __name__ == "__main__":
    try:
        # 初始化核心组件
        logger = FileLogger("auto_check.log")
        storage = JsonConfigStorage("data.json")
        config_manager = ConfigManager(storage, logger)
        
        # 配置检查
        if not config_manager.config or not all(
            key in config_manager.config 
            for key in AppConstants.REQUIRED_FIELDS
        ):
            logger.log("检测到无效或缺失的配置", LogLevel.WARNING)
            print(f"{Fore.YELLOW}首次使用或配置不完整，需要初始化{Style.RESET_ALL}")
            choice = input("是否现在进行配置初始化? (y/n, 默认y): ").strip().lower() or 'y'
            if choice != 'y':
                logger.log("用户取消配置初始化", LogLevel.INFO)
                sys.exit(0)
        
        # 配置更新流程
        updater = ConfigUpdater(config_manager, logger)
        try:
            config = updater.init_config()
            if not config:
                raise ValueError("配置初始化失败")
            
            # 显示当前时间段设置
            if config.get('enable_time_range', False):
                print(f"\n{Fore.CYAN}当前运行时间段: {config.get('start_time', '08:00')} 至 {config.get('end_time', '22:00')}{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.CYAN}时间段控制: 已禁用 (程序将全天候运行){Style.RESET_ALL}")
                
        except Exception as e:
            logger.log(f"配置初始化错误: {e}", LogLevel.ERROR)
            sys.exit(1)
        
        # 启动签到任务
        sign_task = SignTask(config=config, logger=logger)
        print(f"\n{Fore.GREEN}=== 自动签到系统已启动 ==={Style.RESET_ALL}")
        print("可用命令:")
        print("  q - 退出程序")
        print("  s - 立即执行签到检查")
        print("  c - 显示当前状态\n")
        
        try:
            sign_task.run()
        except KeyboardInterrupt:
            logger.log("用户手动终止程序", LogLevel.INFO)
            sys.exit(0)
            
    except Exception as e:
        logger.log(f"系统启动失败: {e}", LogLevel.ERROR)
        sys.exit(1)
