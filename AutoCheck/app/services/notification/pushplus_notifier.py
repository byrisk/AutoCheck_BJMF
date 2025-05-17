# app/services/notification/pushplus_notifier.py
import requests
import json # 用于解析 PushPlus 响应
from typing import Any, Dict

from app.logger_setup import LoggerInterface, LogLevel # 假设 LoggerInterface 和 LogLevel 在这里
from .interface import NotifierInterface # 从同级目录的 interface.py 导入

class PushPlusNotifier(NotifierInterface):
    API_URL = "http://www.pushplus.plus/send"

    def __init__(self, token: str, logger: LoggerInterface, app_name: str = "AutoCheckApp"):
        if not token:
            raise ValueError("PushPlusNotifier: 必须提供 token。")
        self.token = token
        self.logger = logger
        self.app_name = app_name # 可用于默认标题或日志中区分来源
        self.logger.log(f"PushPlusNotifier 初始化成功 (Token: ...{token[-6:]})", LogLevel.DEBUG)

    def send(self, title: str, content: str, **kwargs: Any) -> bool:
        """
        通过 PushPlus 发送通知。
        注意：这里的 title 和 content 应该是已经格式化好的。
        PushPlus 支持 HTML 和 Markdown，这里我们默认使用 Markdown。
        """
        if not self.token: # 再次检查，以防 token 在运行时被意外清空
            self.logger.log("PushPlusNotifier: Token 未设置，无法发送通知。", LogLevel.WARNING)
            return False

        # 原始的 SignService._send_notification 中，title 和 content 已经包含了应用名、时间戳等。
        # 这里我们直接使用传入的 title 和 content。
        # PushPlus 的 template 默认为 'html'，如果内容是 Markdown，应指定 'markdown'。
        # 我们假设调用者会传入适合 Markdown 的 content。
        payload = {
            "token": self.token,
            "title": title,
            "content": content, # 期望是 Markdown 格式的字符串
            "template": kwargs.get("template", "markdown"), # 允许通过kwargs覆盖模板
            "channel": kwargs.get("channel", None), # 例如 "wechat", "email", "webhook"
            "webhook": kwargs.get("webhook", None), # 具体 webhook 代码
            "callbackUrl": kwargs.get("callbackUrl", None),
            "timestamp": kwargs.get("timestamp", None) # 毫秒时间戳
        }
        # 移除 None 值的参数，因为 PushPlus API 可能不接受 null
        payload_cleaned = {k: v for k, v in payload.items() if v is not None}

        try:
            response = requests.post(self.API_URL, json=payload_cleaned, timeout=10)
            response.raise_for_status() # 如果是 4xx 或 5xx 错误，会抛出异常

            response_data = {}
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                self.logger.log(f"PushPlusNotifier: 响应不是有效的JSON格式。响应文本: {response.text[:200]}", LogLevel.WARNING)
                # 即使不是JSON，只要HTTP状态码是2xx，也可能意味着发送被接受
                if 200 <= response.status_code < 300:
                    self.logger.log(f"PushPlusNotifier: 通知发送请求被接受 (HTTP {response.status_code})，但响应解析失败。", LogLevel.DEBUG)
                    return True # 认为发送尝试是成功的
                return False # 其他HTTP错误且非JSON

            if response_data.get("code") == 200:
                self.logger.log(f"PushPlusNotifier: 通知 '{title}' 发送成功。", LogLevel.INFO)
                return True
            else:
                self.logger.log(
                    f"PushPlusNotifier: 通知 '{title}' 发送失败。PushPlus返回: "
                    f"Code={response_data.get('code')}, Msg='{response_data.get('msg', '未知错误')}'",
                    LogLevel.ERROR
                )
                return False
        except requests.exceptions.RequestException as e:
            self.logger.log(f"PushPlusNotifier: 发送通知 '{title}' 时发生网络请求错误: {e}", LogLevel.ERROR, exc_info=True)
            return False
        except Exception as e_unknown: # 其他未知错误
             self.logger.log(f"PushPlusNotifier: 发送通知 '{title}' 时发生未知错误: {e_unknown}", LogLevel.ERROR, exc_info=True)
             return False