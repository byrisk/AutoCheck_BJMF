# app/services/notification/k8n_internal_notifier.py
import requests
from typing import Any, Dict, Optional, List, Union # Union for to_course
from datetime import datetime, timedelta

from app.services.notification.interface import NotifierInterface
from app.logger_setup import LoggerInterface, LogLevel

# 定义 Payload 的所有必需键 (根据您的最新详细示例)
_PAYLOAD_KEYS = {
    "TITLE": "title",
    "CONTENT": "content",
    "FILES": "files[]",        # 注意：这是一个可以出现多次的键
    "ATTACHMENT": "attachment",
    "URL": "url",
    "TYPE": "type",
    "TO_COURSE": "to_course[]",
    "TO_STUDENT_IDS": "to_student_ids",
    "TO_STUDENT_NAME": "to_student_name",
    "NO_REPLY": "no_reply",
    "SEND_TO_WX": "sendtowx",
    "MSG_CREATED_AT": "msg_created_at",
    "WX_TASK_DT": "wxtask_dt",
    "VALID_DAYS": "valid_days"
}

class K8nInternalMessageNotifier(NotifierInterface):
    def __init__(self,
                 student_uid: str, # 发送方学生UID (用于认证)
                 student_name: Optional[str], # 发送方学生姓名 (可选, 用于日志)
                 cookie: str, # 发送方Cookie
                 logger: LoggerInterface,
                 base_url: str = "http://k8n.cn",
                 app_name: str = "AutoCheckApp"):
        if not student_uid:
            raise ValueError("K8nInternalMessageNotifier: 必须提供发送方 student_uid。")
        if not cookie:
            raise ValueError("K8nInternalMessageNotifier: 必须提供发送方 cookie。")

        self.sender_student_uid = student_uid
        self.sender_student_name = student_name
        self.cookie = cookie
        self.logger = logger
        self.base_url = base_url
        self.app_name = app_name # 可用于日志或默认信息
        self.logger.log(f"K8nInternalMessageNotifier 初始化成功 (发送方 UID: {self.sender_student_uid})", LogLevel.DEBUG)

    def send(self, title: str, content: str, **kwargs: Any) -> bool:
        """
        发送 K8N 内部消息，支持复杂参数。

        Args:
            title (str): 消息标题。
            content (str): 消息内容。
            **kwargs: 期望包含以下键 (如果值为空，请传入空字符串或对应类型的空值):
                course_id (Union[str, List[str]]): 目标课程ID或ID列表。 (必需)
                files_list (List[str], optional): 用于 'files[]' 参数的字符串列表。
                                                  每个字符串将作为 'files[]' 的一个独立值。
                                                  例如: ["filename.png", "jfiler-value", "[\"json_array_val\"]"]
                attachment_json_string (str, optional): 'attachment' 参数的JSON字符串。默认为 "[]"。
                message_url (str, optional): 'url' 参数。默认为空字符串。
                message_type (str, optional): 'type' 参数。默认为 "1"。
                to_student_ids (str, optional): 'to_student_ids' 参数。默认为空字符串。
                to_student_name (str, optional): 'to_student_name' 参数。默认为空字符串。
                no_reply_flag (str, optional): 'no_reply' 参数。默认为 "1"。
                send_to_wx_flag (str, optional): 'sendtowx' 参数。默认为 "1"。
                valid_days_str (str, optional): 'valid_days' 参数。默认为 "30"。
        Returns:
            bool: True 如果发送请求被服务器接受，否则 False。
        """
        target_course_id: Union[str, List[str], None] = kwargs.get("course_id")
        if not target_course_id:
            self.logger.log("K8nInternalMessageNotifier: 未提供 course_id，无法发送内部消息。", LogLevel.WARNING)
            return False

        # 处理课程ID, API可能期望to_course[]是列表，即使只有一个ID
        # 但您的示例显示 "to_course[]": "81104" (字符串)。
        # 为了与您的示例保持一致，我们先这样处理。
        # 如果API实际需要列表形式，如 to_course[]=81104 (而不是 to_course[]=["81104"])，
        # 那么 requests 的 data 参数应为元组列表，如 [('to_course[]', '81104')]
        # 如果是单个字符串，requests 会自动处理。如果是列表，requests 会将其转换为URL编码的列表字符串。
        # 为确保与表单行为一致，如果 target_course_id 是列表，我们将在 data_list 中多次添加它。
        
        first_course_id_for_url = str(target_course_id[0] if isinstance(target_course_id, list) else target_course_id)
        url = f"{self.base_url}/student/course/{first_course_id_for_url}/messages/newmail"

        user_agent = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "max-age=0",
            "Content-Type": "application/x-www-form-urlencoded", # 重要
            "Cookie": self.cookie,
            "Host": "k8n.cn",
            "Origin": "http://k8n.cn",
            "Referer": url,
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": user_agent
        }

        now = datetime.now()
        # 使用您示例中的时间格式，但日期是当前的
        msg_created_at_str = kwargs.get("msg_created_at", now.strftime("%Y-%m-%d %H:%M:%S"))
        wxtask_dt_str = kwargs.get("wxtask_dt", (now + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")) # 确保wxtask稍晚或等于created_at

        # 构建 data_list 以支持 files[] 可能的多个值
        data_list: List[Tuple[str, str]] = []

        data_list.append((_PAYLOAD_KEYS["TITLE"], title))
        data_list.append((_PAYLOAD_KEYS["CONTENT"], content))

        # 处理 files[] - 它可以有多个条目
        files_data: List[str] = kwargs.get("files_list", [""]) # 默认为包含一个空字符串的列表，以确保key存在
        if not files_data: # 如果传入的是空列表，也确保至少有一个空files[]参数
            files_data = [""]
        for file_entry in files_data:
            data_list.append((_PAYLOAD_KEYS["FILES"], str(file_entry))) # 确保是字符串

        data_list.append((_PAYLOAD_KEYS["ATTACHMENT"], kwargs.get("attachment_json_string", "[]")))
        data_list.append((_PAYLOAD_KEYS["URL"], kwargs.get("message_url", "")))
        data_list.append((_PAYLOAD_KEYS["TYPE"], kwargs.get("message_type", "1"))) # 您示例中是 "1"

        # 处理 to_course[]
        if isinstance(target_course_id, list):
            for course_item_id in target_course_id:
                data_list.append((_PAYLOAD_KEYS["TO_COURSE"], str(course_item_id)))
        else:
            data_list.append((_PAYLOAD_KEYS["TO_COURSE"], str(target_course_id)))

        data_list.append((_PAYLOAD_KEYS["TO_STUDENT_IDS"], kwargs.get("to_student_ids", "")))
        data_list.append((_PAYLOAD_KEYS["TO_STUDENT_NAME"], kwargs.get("to_student_name", "")))
        data_list.append((_PAYLOAD_KEYS["NO_REPLY"], kwargs.get("no_reply_flag", "1"))) # 包含 no_reply
        data_list.append((_PAYLOAD_KEYS["SEND_TO_WX"], kwargs.get("send_to_wx_flag", "1")))
        data_list.append((_PAYLOAD_KEYS["MSG_CREATED_AT"], msg_created_at_str))
        data_list.append((_PAYLOAD_KEYS["WX_TASK_DT"], wxtask_dt_str))
        data_list.append((_PAYLOAD_KEYS["VALID_DAYS"], kwargs.get("valid_days_str", "30"))) # 您示例中是 "3"

        self.logger.log(f"K8nInternalMessageNotifier: 准备发送内部消息。URL: {url}", LogLevel.DEBUG)
        log_headers = {k: (v[:30] + '...' if k.lower() == 'cookie' and len(v) > 30 else v) for k, v in headers.items()}
        self.logger.log(f"K8nInternalMessageNotifier: Request Headers (部分): {log_headers}", LogLevel.DEBUG)
        # 将 data_list 转换为字典进行日志记录可能更易读，但实际发送的是列表
        self.logger.log(f"K8nInternalMessageNotifier: Request Payload (作为元组列表): {data_list}", LogLevel.DEBUG)

        try:
            # 当data是列表或元组时, requests会正确处理重复键名
            response = requests.post(url, headers=headers, data=data_list, timeout=15, allow_redirects=False)

            self.logger.log(f"K8nInternalMessageNotifier: 响应状态码: {response.status_code}", LogLevel.DEBUG)
            self.logger.log(f"K8nInternalMessageNotifier: 响应头: {response.headers}", LogLevel.DEBUG)
            self.logger.log(f"K8nInternalMessageNotifier: 响应内容 (前500字符): {response.text[:500]}", LogLevel.DEBUG)


            if response.status_code == 302:
                location_header = response.headers.get('Location', '未指定')
                self.logger.log(f"K8N内部消息: 收到服务器重定向 (302) 到 '{location_header}'. 视为成功。", LogLevel.INFO)
                return True
            elif 200 <= response.status_code < 300:
                self.logger.log(f"K8N内部消息: 请求被接受 (HTTP {response.status_code}). 视为成功。", LogLevel.INFO)
                return True
            else:
                self.logger.log(f"K8N内部消息: 发送失败。状态码: {response.status_code}, 响应: {response.text[:200]}", LogLevel.ERROR)
                return False
        except requests.exceptions.Timeout:
            self.logger.log(f"K8N内部消息: 发送超时 (URL: {url})。", LogLevel.WARNING)
            return False
        except requests.exceptions.RequestException as e:
            self.logger.log(f"K8N内部消息: 发送时发生网络请求错误: {e}", LogLevel.ERROR, exc_info=True)
            return False
        except Exception as e_unknown:
             self.logger.log(f"K8N内部消息: 发送时发生未知错误: {e_unknown}", LogLevel.ERROR, exc_info=True)
             return False