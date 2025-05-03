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

# 初始化 colorama
colorama.init(autoreset=True)


# 定义日志级别枚举类
class LogLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


# 定义应用常量数据类
@dataclass
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


# 定义日志记录接口
class LoggerInterface(ABC):
    @abstractmethod
    def log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        pass


# 实现日志记录类
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


# 定义配置存储接口
class ConfigStorageInterface(ABC):
    @abstractmethod
    def load(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save(self, config: Dict[str, Any]) -> None:
        pass


# 实现配置存储类
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


# 定义配置模型类
class ConfigModel(BaseModel):
    class_id: str
    lat: str
    lng: str
    acc: str
    time: int = 60
    cookie: str
    pushplus: str = ""
    remark: str = "自动签到配置"

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
    def validate_search_time(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("检索间隔必须为正整数")
        return v


# 定义配置管理器类
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
            # 如果配置文件存在，进入正常的加载和验证流程
            config = {
                "class_id": raw_config.get("class_id") or raw_config.get("class", ""),
                "lat": raw_config.get("lat", ""),
                "lng": raw_config.get("lng", ""),
                "acc": raw_config.get("acc", ""),
                "time": raw_config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL),
                "cookie": raw_config.get("cookie", ""),
                "pushplus": raw_config.get("pushplus", ""),
                "remark": raw_config.get("remark", "自动签到配置")
            }

            try:
                return ConfigModel(**config).model_dump()
            except ValidationError as e:
                self._handle_validation_error(e)
                return {}
        except FileNotFoundError:
            # 创建新的空配置文件
            self.storage.save({})
            # 导入 ConfigUpdater 类
            from .main import ConfigUpdater
            # 初始化 ConfigUpdater 并调用 init_config 方法
            updater = ConfigUpdater(self, self.logger)
            new_config = updater.init_config()
            # 对于新创建的配置文件，直接返回，跳过验证
            return new_config

    def _handle_validation_error(self, error: ValidationError) -> None:
        error_messages = [f"{err['loc'][0]}: {err['msg']}" for err in error.errors()]
        self.logger.log("配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR)

    def save(self) -> None:
        try:
            self.storage.save(self._config)
            self.logger.log("配置保存成功", LogLevel.INFO)
        except ValueError as e:
            self.logger.log(f"保存配置时出错: {e}", LogLevel.ERROR)


# 定义配置更新器类
class ConfigUpdater:
    def __init__(self, config_manager: ConfigManager, logger: LoggerInterface):
        self.manager = config_manager
        self.logger = logger
        self.login_system = QRLoginSystem()
        self.scanned_class_ids = []
        self.scanned_cookie = None

    def init_config(self) -> Dict[str, Any]:
        if not self.manager.config or not self._validate_config():
            self.logger.log("当前配置无效，需要重新配置", LogLevel.ERROR)
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
            display_value = value if key != "cookie" else "[已隐藏]"
            self.logger.log(f"{key}: {display_value}", LogLevel.INFO)
        self.logger.log("--------------------------------", LogLevel.INFO)

    def _should_update_config(self) -> bool:
        while True:
            choice = input("当前配置有效。是否修改配置？(y/n, 默认n): ").strip().lower()
            if choice in ('', 'n'):
                return False
            if choice == 'y':
                return True
            print(f"\033[31m请输入 y 或 n\033[0m")

    def _update_config_interactively(self) -> Dict[str, Any]:
        self.logger.log("开始交互式配置更新", LogLevel.INFO)
        while True:
            success = self._update_cookie_and_class_id()
            if success:
                break
            retry = input("未获取到有效的 cookie 或 class_id，是否重试？(y/n): ").strip().lower()
            if retry != 'y':
                break
        self._update_coordinates()
        self._update_search_interval()
        self._update_pushplus()
        self._update_remark()

        if self._validate_config():
            self.manager.save()
            return self.manager.config

        self.logger.log("配置仍无效，请重新输入", LogLevel.ERROR)
        return self._update_config_interactively()

    def _get_user_input(self, prompt: str, required: bool = False) -> str:
        while True:
            try:
                sys.stdin.flush()
                value = input(prompt).strip()
                if required and not value:
                    raise ValueError("该字段为必填项")
                return value
            except ValueError as e:
                self.logger.log(f"{e}，请重新输入", LogLevel.ERROR)
            except (EOFError, KeyboardInterrupt):
                self.logger.log("\n输入中断，请重新输入", LogLevel.ERROR)

    def _update_cookie_and_class_id(self) -> bool:
        current_cookie = self.manager.config.get("cookie", "")
        current_class_id = self.manager.config.get("class_id", "")

        if not current_cookie or not current_class_id:
            if self._ask_scan_choice("当前 cookie 或 class_id 无效或缺失，是否通过扫码获取？(y/n, 默认n): "):
                success = self._scan_and_update()
                if success:
                    return True
                else:
                    return False
            else:
                self._update_required_fields()
        else:
            if self._ask_update_choice(current_cookie, current_class_id):
                if self._ask_scan_choice("是否通过扫码获取？(y/n, 默认n): "):
                    success = self._scan_and_update()
                    if success:
                        return True
                    else:
                        return False
                else:
                    self._update_required_fields()
        return True

    def _ask_scan_choice(self, prompt: str) -> bool:
        choice = input(prompt).strip().lower()
        return choice == 'y'

    def _ask_update_choice(self, current_cookie: str, current_class_id: str) -> bool:
        display_cookie = current_cookie if not current_cookie else "[已隐藏]"
        display_class_id = current_class_id
        while True:
            choice = input(f"当前 cookie 为: {display_cookie}，class_id 为: {display_class_id}，是否修改？(y/n, 默认n): ").strip().lower()
            if choice in ('', 'n'):
                return False
            if choice == 'y':
                return True
            print(f"\033[31m请输入 y 或 n\033[0m")

    def _scan_and_update(self) -> bool:
        qr_url = self.login_system.fetch_qr_code_url()
        if qr_url:
            success = self.login_system.display_qr_code(qr_url)
            if success:
                # 创建一个虚拟的 root 对象，因为这里只是为了调用 check_login_status 传递参数
                root = tk.Tk()
                root.withdraw()  # 隐藏窗口
                login_result = self.login_system.check_login_status(root, 0)
                root.destroy()
                if login_result:
                    result = self.login_system.fetch_logged_in_data()
                    if result["status"] == "success":
                        self.scanned_cookie = self.login_system.session.cookies.get(
                            'remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d')
                        if not self.scanned_cookie:
                            return False
                        self.scanned_cookie = f"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d={self.scanned_cookie}"
                        self.scanned_class_ids = [self.login_system.classid]
                        selected_class_id = self._select_class_id()
                        self.manager.config["class_id"] = selected_class_id
                        self.manager.config["cookie"] = self.scanned_cookie
                        return True
        return False

    def _select_class_id(self) -> str:
        return self.login_system.classid

    def _update_required_fields(self):
        self._update_field("cookie", ConfigModel.validate_cookie, is_required=True)
        self._update_field("class_id", ConfigModel.validate_class_id, is_required=True)

    def _update_field(self, field: str, validator: Callable[[str], Any], is_required: bool = False) -> None:
        current_value = self.manager.config.get(field, "")
        while True:
            new_value = self._get_user_input(
                f"请输入 {field}{' [必填]' if is_required else ''}: ",
                required=is_required
            )
            if not is_required and not new_value:
                self.manager.config[field] = ""
                break
            try:
                if field == "time":
                    new_value = int(new_value)
                validated_value = validator(new_value)
                self.manager.config[field] = validated_value
                break
            except ValueError as e:
                self.logger.log(f"{field} 验证失败: {e}", LogLevel.ERROR)

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


# 定义签到任务类
class SignTask:
    def __init__(self, config: Dict[str, Any], logger: LoggerInterface):
        self.config = config
        self.logger = logger
        self.invalid_sign_ids: Set[str] = set()
        self.signed_ids: Set[str] = set()

    def run(self) -> None:
        if not self._check_login():
            self.logger.log("未登录，无法开始签到任务，请先登录。", LogLevel.ERROR)
            return
        while True:
            self._execute_sign_cycle()
            self._wait_for_next_cycle()

    def _check_login(self) -> bool:
        return bool(self.config.get("cookie"))

    def _execute_sign_cycle(self) -> None:
        self.logger.log(f"开始检索签到任务，当前时间: {datetime.now()}", LogLevel.INFO)

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

    def _wait_for_next_cycle(self) -> None:
        interval = self.config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL)
        self.logger.log(f"等待下次检索，间隔: {interval}秒", LogLevel.INFO)
        time.sleep(interval)


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

    def fetch_qr_code_url(self):
        print("正在努力为您获取二维码链接，请稍候...")
        try:
            response = self.session.get(self.base_url, headers=self.headers)
            if response.status_code == 200:
                pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=[^"]+'
                match = re.search(pattern, response.text)
                if match:
                    qr_code_url = match.group(0)
                    print(f"太棒啦！成功为您获取到二维码链接: {qr_code_url}")
                    return qr_code_url
        except requests.RequestException as e:
            print(f"哎呀，获取二维码链接时出问题啦: {e}")
        print("很遗憾，没有找到二维码链接呢。")
        return None

    def display_qr_code(self, qr_code_url):
        print("正在为您准备登录二维码，请稍候...")
        try:
            response = self.session.get(qr_code_url)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                img = img.resize((260, 260), Image.LANCZOS)

                root = tk.Tk()
                root.title("微信登录二维码")

                # 固定窗口大小
                window_width = 320
                window_height = 400
                root.geometry(f"{window_width}x{window_height}")
                root.resizable(False, False)

                # 强制窗口出现在固定位置（距离左上角100,100）
                root.geometry("+100+100")

                # 确保窗口显示在最前面（分两步操作更可靠）
                root.attributes('-topmost', True)
                root.after(10, lambda: root.attributes('-topmost', True))

                # 主框架
                main_frame = tk.Frame(root, padx=20, pady=20)
                main_frame.pack(expand=True, fill=tk.BOTH)

                # 二维码图片
                photo = ImageTk.PhotoImage(img)
                img_frame = tk.Frame(main_frame, bd=2, relief=tk.GROOVE)
                img_frame.pack(pady=(0, 15))
                tk.Label(img_frame, image=photo).pack(padx=5, pady=5)

                # 提示文字
                tk.Label(
                    main_frame,
                    text="请使用微信扫描二维码登录",
                    font=("Microsoft YaHei", 12),
                    fg="#333"
                ).pack(pady=(0, 10))

                # 辅助提示
                tk.Label(
                    main_frame,
                    text="拖动标题栏可移动窗口",
                    font=("Microsoft YaHei", 9),
                    fg="#666"
                ).pack()

                # 保持图片引用
                main_frame.image = photo

                # 实现窗口拖动功能（通过绑定整个窗口）
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

                # 绑定到主框架实现拖动
                main_frame.bind("<ButtonPress-1>", start_move)
                main_frame.bind("<ButtonRelease-1>", stop_move)
                main_frame.bind("<B1-Motion>", do_move)

                # 强制获取焦点
                root.after(100, root.focus_force)

                self.login_success = False
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
            print("很可惜，已经超过最大尝试次数，登录检查失败啦。")
            root.destroy()
            return False
        check_url = f"{self.base_url}?op=checklogin"
        try:
            response = self.session.get(check_url, headers=self.headers)
            print(f"第 {attempt + 1} 次尝试检查登录状态，状态码是 {response.status_code} 哦。")
            data = response.json()
            if data.get('status'):
                print("哇塞，您已成功登录啦！")
                self.handle_successful_login(response, data)
                self.login_success = True
                root.destroy()
                return True
        except Exception as e:
            print(f"哎呀，第 {attempt + 1} 次登录检查尝试失败啦: {str(e)}")
        root.after(self.check_interval * 1000, self.check_login_status, root, attempt + 1)
        return False

    def handle_successful_login(self, initial_response, data):
        print("正在为您处理登录后的相关操作，请稍等...")
        self.extract_and_set_cookies(initial_response)
        new_url = 'https://k8n.cn' + data['url']
        self.send_follow_up_request(new_url)
        cookies = self.get_required_cookies()
        print(f"成功为您获取到关键 Cookies: {cookies}")

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
                    print(f"成功提取到 Cookie: {cookie_value}")

    def send_follow_up_request(self, url):
        print("正在发送登录后的跟进请求，请稍等片刻...")
        try:
            response = self.session.get(url, headers=self.headers)
            self.extract_and_set_cookies(response)
        except requests.RequestException as e:
            print(f"哎呀，跟进请求出错啦: {e}")

    def get_required_cookies(self):
        cookies = self.session.cookies.get_dict()
        return {
            'remember_student': cookies.get("remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d")
        }

    def fetch_logged_in_data(self):
        if not self.login_success:
            return {"status": "error", "message": "未成功登录，无法获取数据"}
        data_url = 'http://k8n.cn/student'
        try:
            response = self.session.get(data_url, headers=self.headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')

                # 提取班级信息
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
                    print("未找到任何班级信息，请检查页面结构是否发生变化。")
                    return {"status": "error"}
                else:
                    print("成功为您获取到登录后的数据啦！")
                    print("班级信息：")
                    for idx, info in enumerate(class_info_list, start=1):
                        print(f"  班级 {idx}: 课程 ID: {info['课程 ID']} 班级名称: {info['班级名称']} 课程名称: {info['课程名称']} 班级码: {info['班级码']}")

                    # 从班级信息中提取所有 classid
                    all_classids = [info['课程 ID'] for info in class_info_list]
                    print(f"所有 classid: {all_classids}")

                    # 处理不同个数的 classid 情况
                    if len(all_classids) == 0:
                        print("未找到有效的 classid，请检查页面结构。")
                        return {"status": "error"}
                    elif len(all_classids) == 1:
                        self.classid = all_classids[0]
                        print(f"已自动选择唯一的 classid: {self.classid}")
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
                                    break
                                else:
                                    print("输入的序号无效，请重新输入。")
                            except ValueError:
                                print("输入无效，请输入一个数字。")

                    return {"status": "success", "classid": self.classid}
            else:
                print(f"请求登录后数据失败，状态码: {response.status_code}")
                return {"status": "error"}
        except requests.RequestException as e:
            print(f"获取登录后数据时发生网络错误: {e}")
            return {"status": "error"}


if __name__ == "__main__":
    logger = FileLogger()
    storage = JsonConfigStorage()
    config_manager = ConfigManager(storage, logger)
    updater = ConfigUpdater(config_manager, logger)
    config = updater.init_config()
    sign_task = SignTask(config, logger)
    sign_task.run()
