# autocheckf/app/services/sign_service.py
import requests
import re
import time
import json 
import random
from bs4 import BeautifulSoup, Tag # type: ignore
from typing import Dict, Any, Optional, List, Set, TYPE_CHECKING 
from datetime import datetime 

from colorama import Fore, Style

from app.constants import AppConstants, SCRIPT_VERSION 
from app.logger_setup import LoggerInterface, LogLevel
from app.config.remote_manager import RemoteConfigManager
from app.exceptions import LocationError


if TYPE_CHECKING: # pragma: no cover
    from app.services.notification import NotificationManager

SignTaskDetails = Dict[str, Any]


class SignService:
    def __init__(self,
                 logger: LoggerInterface,
                 app_config: Dict[str, Any], 
                 remote_config_manager: RemoteConfigManager,
                 notification_manager: 'NotificationManager' 
                 ):
        self.logger = logger
        self.base_config = app_config 
        self.remote_config_manager = remote_config_manager
        self.notification_manager = notification_manager
        
        self.signed_ids: Set[str] = set() # Tracks tasks confirmed as signed in this session
        self.invalid_sign_ids: Set[str] = set() # Tracks tasks deemed permanently invalid (e.g., needs password, 404)
        
        # Sets to track if a notification for a specific outcome has been sent for a task ID
        self.notified_success_ids: Set[str] = set()
        self.notified_password_failure_ids: Set[str] = set()
        
        self.total_successful_sign_ins: int = int(self.base_config.get('total_successful_sign_ins', 0))
        self.current_dynamic_coords: Dict[str, str] = {}
        self.user_agent = self._generate_random_user_agent()

    def set_current_coordinates(self, coords: Dict[str, str]):
        self.current_dynamic_coords = coords
        self.logger.log(f"SignService 当前签到坐标已更新为: {coords}", LogLevel.DEBUG)

    def get_total_successful_sign_ins(self) -> int:
        return self.total_successful_sign_ins

    def _build_headers(self, current_class_id: str) -> Dict[str, str]:
        referer_url = f'http://k8n.cn/student/course/{current_class_id}/punchs' if current_class_id and current_class_id.isdigit() else 'http://k8n.cn/student/'
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/wxpic,image/tpg,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "X-Requested-With": "com.tencent.mm", 
            "Referer": referer_url,
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cookie": self.base_config.get("cookie", ""),
        }

    def _generate_random_user_agent(self) -> str:
        ua_pool_config = self.remote_config_manager.get_config_value(
            ["settings", "user_agent_pool"], 
            AppConstants.DEFAULT_REMOTE_CONFIG.get("settings", {}).get("user_agent_pool", {}) 
        )
        active_pool = {
            "android_versions": ua_pool_config.get("android_versions") or ["12", "13", "14", "15"],
            "devices": ua_pool_config.get("devices") or ["Pixel 6", "Pixel 7 Pro", "Galaxy S23"],
            "build_numbers": ua_pool_config.get("build_numbers") or ["SP1A.210812.016", "TQ3A.230705.001"],
            "chrome_versions": ua_pool_config.get("chrome_versions") or ["115.0.5790.166", "120.0.6099.40", "124.0.6367.113"],
            "wechat_versions": ua_pool_config.get("wechat_versions") or ["8.0.32", "8.0.40", "8.0.48"],
            "net_types": ua_pool_config.get("net_types") or ["WIFI", "5G"]
        }
        if ua_pool_config.get("enabled"): self.logger.log("使用远程配置的User-Agent池。", LogLevel.DEBUG)
        else: self.logger.log("远程User-Agent池未启用或配置无效，使用内置默认UA组件。", LogLevel.DEBUG)
        try:
            return AppConstants.USER_AGENT_TEMPLATE.format(
                android_version=random.choice(active_pool["android_versions"]),
                device=random.choice(active_pool["devices"]),                
                build_number=random.choice(active_pool["build_numbers"]),      
                chrome_version=random.choice(active_pool["chrome_versions"]),  
                wechat_version=random.choice(active_pool["wechat_versions"]),  
                net_type=random.choice(active_pool["net_types"])               
            )
        except IndexError: 
            self.logger.log("生成User-Agent时列表为空，回退到硬编码UA。", LogLevel.ERROR)
            return "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.40 NetType/WIFI"
        except Exception as e: 
            self.logger.log(f"生成User-Agent时发生未知错误: {e}", LogLevel.ERROR, exc_info=True)
            return AppConstants.USER_AGENT_TEMPLATE.format( 
                android_version=active_pool["android_versions"][0] if active_pool["android_versions"] else "13", 
                device=active_pool["devices"][0] if active_pool["devices"] else "Pixel 7",
                build_number=active_pool["build_numbers"][0] if active_pool["build_numbers"] else "TQ3A.230705.001", 
                chrome_version=active_pool["chrome_versions"][0] if active_pool["chrome_versions"] else "120.0.0.0",
                wechat_version=active_pool["wechat_versions"][0] if active_pool["wechat_versions"] else "8.0.40", 
                net_type=active_pool["net_types"][0] if active_pool["net_types"] else "WIFI"
            )

    def fetch_sign_task_details(self, class_id_to_fetch: str) -> Optional[List[SignTaskDetails]]:
        if not class_id_to_fetch or not class_id_to_fetch.isdigit():
            self.logger.log(f"无效的班级ID '{class_id_to_fetch}' 传递给 fetch_sign_task_details。", LogLevel.ERROR)
            return None
        url = f'http://k8n.cn/student/course/{class_id_to_fetch}/punchs'
        headers = self._build_headers(class_id_to_fetch)
        self.logger.log(f"班级 {class_id_to_fetch}: 获取详细签到任务列表 URL: {url}", LogLevel.DEBUG)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            tasks: List[SignTaskDetails] = []
            card_containers = soup.find_all("div", class_="layui-col-xs6") 
            if not card_containers:
                self.logger.log(f"班级 {class_id_to_fetch}: 未找到 'layui-col-xs6' (签到卡片容器) 元素。", LogLevel.DEBUG)
                if "请先加入班级或等待老师开启上课点名" in response.text: self.logger.log(f"班级 {class_id_to_fetch}: 页面提示未加入班级或无签到任务。", LogLevel.INFO)
                return []
            for card_container_div in card_containers:
                card_main_div = card_container_div.find("div", class_="card")
                card_body = card_container_div.find("div", class_="card-body", id=re.compile(r"punchcard_(\d+)"))
                if not card_body or not card_main_div: continue
                
                task_id_match = re.search(r"punchcard_(\d+)", card_body.get("id", ""))
                if not task_id_match: continue
                task_id = task_id_match.group(1)

                subtitle_tag = card_body.find("div", class_="subtitle")
                task_title_on_card = subtitle_tag.text.strip() if subtitle_tag else "未知类型签到"

                raw_onclick = card_main_div.get("onclick", "")
                
                status_tag = card_body.find("span", class_=re.compile(r"layui-badge\s+(layui-bg-danger|layui-bg-green|layui-bg-orange)"))
                task_status = status_tag.text.strip() if status_tag else "未知状态"
                if status_tag: 
                    if "layui-bg-green" in status_tag.get("class", []): task_status = "已签"
                    elif "layui-bg-danger" in status_tag.get("class", []): task_status = "未签"
                    elif "layui-bg-orange" in status_tag.get("class", []): task_status = "未开始" 
                
                activity_name_parts = []
                end_time_text = None
                countdown_seconds = None
                
                title_divs = card_body.find_all("div", class_="title")
                for title_div in title_divs:
                    title_text = title_div.text.strip()
                    if "结束" in title_text and ("后" in title_text or re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}结束', title_text)): 
                        end_time_text = title_text
                        countdown_span = title_div.find("span", class_="countdown", attrs={"ct": True})
                        if countdown_span and countdown_span.get("ct", "").isdigit(): 
                            countdown_seconds = int(countdown_span["ct"])
                    elif "已开始" == title_text: 
                        if task_status == "未知状态" and "layui-bg-danger" in card_main_div.get("style",""): task_status = "未签"
                    elif "已结束" == title_text: task_status = "已结束"
                    elif "未开始" == title_text or "考勤未开始" in title_text: task_status = "未开始"
                    else: 
                        if title_text: activity_name_parts.append(title_text)
                
                activity_name_str = " ".join(activity_name_parts) if activity_name_parts else task_title_on_card

                task_type = "unknown"
                photo_hint_text = None
                requires_password_flag = False
                if "punch_gps_photo" in raw_onclick:
                    task_type = "photo_gps"
                    hint_match = re.search(r"punch_gps_photo\(\s*\d+\s*,\s*['\"](.*?)['\"]\)", raw_onclick)
                    if hint_match: photo_hint_text = hint_match.group(1)
                elif "punch_gps" in raw_onclick: task_type = "gps"
                elif "scanqr()" in raw_onclick or "扫码" in task_title_on_card: task_type = "qr"
                elif "密码" in task_title_on_card: task_type = "password"; requires_password_flag = True
                elif "点名" in task_title_on_card: task_type = "roll_call"

                is_gps_limited_range = None
                gps_ranges_data = None
                if task_type in ["gps", "photo_gps"]:
                    inrange_input = soup.find("input", id=f"punch_gps_inrange_{task_id}")
                    if inrange_input and inrange_input.get("value") is not None:
                        is_gps_limited_range = (inrange_input.get("value") == "1")
                    
                    ranges_input = soup.find("input", id=f"punch_gps_ranges_{task_id}")
                    if ranges_input and ranges_input.get("value"):
                        try:
                            parsed_ranges = json.loads(ranges_input.get("value"))
                            if isinstance(parsed_ranges, list) and \
                               all(isinstance(item, list) and len(item) == 3 for item in parsed_ranges) and \
                               all(isinstance(coord, str) for item in parsed_ranges for coord in item[:2]) and \
                               all(isinstance(item[2], (int, float, str)) or str(item[2]).isdigit() for item in parsed_ranges):
                                gps_ranges_data = parsed_ranges
                            else: self.logger.log(f"任务ID {task_id}: GPS范围数据格式不符合预期: {parsed_ranges}", LogLevel.WARNING)
                        except json.JSONDecodeError: 
                            self.logger.log(f"任务ID {task_id}: 解析GPS范围JSON数据失败: '{ranges_input.get('value')}'", LogLevel.WARNING)
                    
                    if is_gps_limited_range and not gps_ranges_data:
                        self.logger.log(f"任务ID {task_id}: 标记为范围限制但GPS范围数据缺失或无效，将按无限制处理。", LogLevel.WARNING)
                        is_gps_limited_range = False 

                task_detail: SignTaskDetails = {
                    "id": task_id, 
                    "type": task_type, 
                    "status": task_status,
                    "title": task_title_on_card, 
                    "activity_name": activity_name_str,
                    "end_time_text": end_time_text, 
                    "countdown_seconds": countdown_seconds,
                    "is_gps_limited_range": is_gps_limited_range, 
                    "gps_ranges": gps_ranges_data, 
                    "photo_hint": photo_hint_text, 
                    "requires_password": requires_password_flag, 
                    "raw_onclick": raw_onclick,
                    "raw_card_html": str(card_main_div)
                }
                tasks.append(task_detail)

            if not tasks and card_containers:
                 self.logger.log(f"班级 {class_id_to_fetch}: 找到 {len(card_containers)} 个签到卡片容器，但未能解析出任何任务详情。", LogLevel.WARNING)
            
            if tasks: self.logger.log(f"班级 {class_id_to_fetch}: 成功解析到 {len(tasks)} 个签到任务的详细信息。", LogLevel.INFO)
            else: self.logger.log(f"班级 {class_id_to_fetch}: 未解析到任何签到任务的详细信息。", LogLevel.INFO)
            return tasks
        except requests.RequestException as e:
            self.logger.log(f"班级 {class_id_to_fetch}: 获取详细签到任务列表失败 (网络请求): {e}", LogLevel.ERROR)
            if e.response is not None: self.logger.log(f"班级 {class_id_to_fetch}: 响应内容(部分): {e.response.text[:200]}", LogLevel.DEBUG)
            return None
        except Exception as e_fetch_detail:
            self.logger.log(f"班级 {class_id_to_fetch}: 获取详细签到任务列表时发生内部错误: {e_fetch_detail}", LogLevel.ERROR, exc_info=True)
            return None

    def attempt_sign(self, sign_id: str, class_id_for_sign: str) -> bool:
        if not self.current_dynamic_coords or not self.current_dynamic_coords.get("lat") or not self.current_dynamic_coords.get("lng"):
            self.logger.log(f"班级 {class_id_for_sign}: 尝试签到ID {sign_id} 失败：坐标无效或未设置。", LogLevel.ERROR)
            self._print_formatted_sign_status("⚠️", Fore.RED, class_id_for_sign, sign_id, "签到失败：内部坐标未设置")
            return False
        
        url = f'{self.base_config.get("base_k8n_url", "http://k8n.cn")}/student/punchs/course/{class_id_for_sign}/{sign_id}'
        payload = {
            "id": sign_id, 
            "lat": self.current_dynamic_coords["lat"], 
            "lng": self.current_dynamic_coords["lng"],
            "acc": self.current_dynamic_coords.get("acc", str(AppConstants.DEFAULT_ACCURACY)),
            "res": "s46grRvFJukcJc3CFnqHcKQLxAvxJYJ-Uh8bsD1YcXiVMN-MoqkVmZPDzpUhTMyf", 
            "gps_addr": "" 
        }
        headers = self._build_headers(class_id_for_sign)
        max_retries = 2 
        is_handled = False

        self.logger.log(f"班级 {class_id_for_sign}: 尝试签到ID {sign_id} 使用坐标: {self.current_dynamic_coords}", LogLevel.INFO)
        
        for attempt in range(1, max_retries + 1):
            if attempt > 1: 
                self.logger.log(f"班级 {class_id_for_sign}: 重试签到ID {sign_id} (尝试 {attempt}/{max_retries})", LogLevel.DEBUG)
            try:
                response = requests.post(url, headers=headers, data=payload, timeout=20)
                response.raise_for_status()
                
                if not response.text.strip():
                    self.logger.log(f"班级 {class_id_for_sign}: 签到ID {sign_id} 响应为空 (尝试 {attempt})。", LogLevel.WARNING)
                    if attempt < max_retries: 
                        time.sleep(2 * attempt)
                        continue
                    else:
                        self.logger.log(f"班级 {class_id_for_sign}: ID {sign_id} 多次响应为空。", LogLevel.ERROR)
                        self._print_formatted_sign_status("⚠️", Fore.RED, class_id_for_sign, sign_id, "签到失败：服务器响应为空")
                        break 
                
                is_handled = self._handle_sign_response(response.text, sign_id, class_id_for_sign)
                return is_handled

            except requests.exceptions.Timeout: 
                self.logger.log(f"班级 {class_id_for_sign}: ID {sign_id} 超时 (尝试 {attempt})。", LogLevel.WARNING)
                if attempt == max_retries:
                    self._print_formatted_sign_status("⏱️", Fore.YELLOW, class_id_for_sign, sign_id, "签到失败：请求超时")
            except requests.exceptions.RequestException as e_req:
                self.logger.log(f"班级 {class_id_for_sign}: ID {sign_id} 请求错误 (尝试 {attempt}): {e_req}", LogLevel.ERROR)
                if e_req.response is not None:
                    self.logger.log(f"班级 {class_id_for_sign}: 错误响应(部分): {e_req.response.text[:250]}", LogLevel.DEBUG)
                    if e_req.response.status_code in [401, 403]:
                        self.logger.log(f"请求错误({e_req.response.status_code})，Cookie可能无效或已过期。", LogLevel.CRITICAL)
                        self._print_formatted_sign_status("🚫", Fore.RED, class_id_for_sign, sign_id, "签到失败：认证错误 (Cookie无效?)")
                        return False 
                    elif e_req.response.status_code == 404:
                        self.logger.log(f"请求错误(404)，签到任务 {sign_id} 可能不存在或已结束。", LogLevel.WARNING)
                        self.invalid_sign_ids.add(sign_id)
                        self._print_formatted_sign_status("🚫", Fore.MAGENTA, class_id_for_sign, sign_id, "签到失败：任务未找到 (404)")
                        return True 
                if attempt == max_retries and not is_handled:
                    self._print_formatted_sign_status("⚠️", Fore.RED, class_id_for_sign, sign_id, "签到失败：网络请求错误")
            except Exception as e_inner: 
                self.logger.log(f"班级 {class_id_for_sign}: 处理ID {sign_id} 时未知错误 (尝试 {attempt}): {e_inner}", LogLevel.ERROR, exc_info=True)
                if attempt == max_retries:
                    self._print_formatted_sign_status("💥", Fore.RED, class_id_for_sign, sign_id, "签到失败：发生内部错误")
                return False 
            
            if attempt < max_retries:
                time.sleep(2 * attempt)
        
        if not is_handled:
            self.logger.log(f"班级 {class_id_for_sign}: ID {sign_id} {max_retries} 次尝试后仍未成功处理。", LogLevel.ERROR)
        return is_handled

    def _print_formatted_sign_status(self, status_icon: str, status_color: Any, class_id: str, sign_id: str, message: str, details: Optional[str] = None):
        main_color = status_color 
        line_width = 80 
        header = f" {status_icon} 签到任务状态 [班级ID: {class_id} | 任务ID: {sign_id}] "
        
        print(f"{main_color}{Style.BRIGHT}┌{'─' * (line_width - 2)}┐{Style.RESET_ALL}")
        print(f"{main_color}{Style.BRIGHT}│{header.ljust(line_width - 2)}│{Style.RESET_ALL}")
        print(f"{main_color}{Style.BRIGHT}├{'─' * (line_width - 2)}┤{Style.RESET_ALL}")
        
        msg_line = f"│  消息: {message}"
        print(f"{main_color}{msg_line.ljust(line_width + len(main_color) + len(Style.RESET_ALL) -1 )}│{Style.RESET_ALL}")


        if details:
            details_single_line = details.replace("\n", " ").replace("\r", "")
            max_detail_len = line_width - 12 
            display_details = (details_single_line[:max_detail_len-3] + "...") if len(details_single_line) > max_detail_len else details_single_line
            detail_line = f"│  详情: {display_details}"
            print(f"{main_color}{detail_line.ljust(line_width + len(main_color) + len(Style.RESET_ALL)-1)}│{Style.RESET_ALL}")
        print(f"{main_color}{Style.BRIGHT}└{'─' * (line_width - 2)}┘{Style.RESET_ALL}")

    def _handle_sign_response(self, html_response: str, sign_id: str, class_id_context: str) -> bool:
        soup = BeautifulSoup(html_response, "html.parser")
        title_tag = soup.find("div", id="title") or soup.find("div", class_="weui-msg__title")
        desc_tag = soup.find("div", id="text") or soup.find("div", class_="weui-msg__desc")
        
        result_message_raw = ""
        if title_tag and title_tag.text: result_message_raw += title_tag.text.strip()
        if desc_tag and desc_tag.text: result_message_raw += (" " + desc_tag.text.strip() if result_message_raw else desc_tag.text.strip())
        if not result_message_raw:
            body_text_tags = soup.find_all(["p", "h1", "h2", "h3", "div"], class_=lambda x: not x or ("button" not in str(x).lower() and "icon" not in str(x).lower()))
            candidate_messages = [tag.text.strip() for tag in body_text_tags if tag.text and tag.text.strip()]
            result_message_raw = ". ".join(list(dict.fromkeys(candidate_messages[:3]))) if candidate_messages else "未能解析签到响应HTML"
        
        self.logger.log(f"班级 {class_id_context} - 签到ID {sign_id} 响应原文: '{result_message_raw}'", LogLevel.INFO)

        is_handled_definitively = False
        should_send_notify = False 
        event_type = "SIGN_IN_OTHER" 
        console_status_icon = "❓"; console_status_color = Fore.WHITE 
        console_message = result_message_raw; console_details = None

        user_info_cfg = self.base_config.get("user_info", {})
        event_context: Dict[str, Any] = {
            "timestamp": datetime.now(),
            "user_name": user_info_cfg.get("uname", "N/A"),
            "user_id": user_info_cfg.get("uid", "N/A"),
            "device_remark": self.base_config.get("remark", "N/A"),
            "app_name": AppConstants.APP_NAME,
            "app_version": SCRIPT_VERSION,
            "class_id": class_id_context,
            "task_id": sign_id,
            "status_message": result_message_raw, 
        }

        if "密码错误" in result_message_raw or "请输入密码" in result_message_raw:
            self.invalid_sign_ids.add(sign_id) # Mark as permanently invalid
            is_handled_definitively = True
            event_type = "SIGN_IN_FAILURE_PASSWORD"
            event_context["details"] = "该签到需要密码，脚本不支持。"
            console_status_icon = "🔑"; console_status_color = Fore.RED; console_message = "失败：需要密码"
            if sign_id not in self.notified_password_failure_ids:
                should_send_notify = True
                self.notified_password_failure_ids.add(sign_id)

        elif "已签到过啦" in result_message_raw or "您已签到" in result_message_raw or "签过啦" in result_message_raw or ("打卡成功" in result_message_raw and "重复" in result_message_raw):
            if sign_id not in self.signed_ids: # If not previously known as signed in this session
                self.signed_ids.add(sign_id)
                self.total_successful_sign_ins += 1
                if sign_id not in self.notified_success_ids: # Send notification only on first confirmation
                    should_send_notify = True
                    self.notified_success_ids.add(sign_id)
                    event_type = "SIGN_IN_ALREADY_DONE" # Or SIGN_IN_SUCCESS if preferred for this case
            is_handled_definitively = True
            console_status_icon = "👍"; console_status_color = Fore.CYAN
            console_message = "状态确认：已签到过"
            if should_send_notify: # If we are notifying (i.e., first time confirming "already signed")
                 event_type = "SIGN_IN_ALREADY_DONE" # Explicitly for notification
                 console_message = "成功 (先前已签到)" # More positive console message for first confirm
                 console_status_color = Fore.GREEN

        elif "成功" in result_message_raw: 
            if sign_id not in self.signed_ids:
                self.signed_ids.add(sign_id)
                self.total_successful_sign_ins += 1
            is_handled_definitively = True
            event_type = "SIGN_IN_SUCCESS"
            console_status_icon = "🎉"; console_status_color = Fore.GREEN; console_message = "签到成功！"
            if sign_id not in self.notified_success_ids:
                should_send_notify = True
                self.notified_success_ids.add(sign_id)
        
        # For other cases, should_send_notify remains False by default
        elif "不在签到时间" in result_message_raw or "还未开始" in result_message_raw or "已结束" in result_message_raw or "考勤未开始" in result_message_raw:
            is_handled_definitively = False 
            console_status_icon = "⏱️"; console_status_color = Fore.YELLOW; console_message = "状态：非签到时间/未开始/已结束"
            console_details = result_message_raw 
        elif "不在签到范围" in result_message_raw or "距离太远" in result_message_raw:
            is_handled_definitively = False 
            console_status_icon = "🗺️"; console_status_color = Fore.RED; console_message = "失败：不在签到范围"
            console_details = result_message_raw
        elif "不存在" in result_message_raw or "参数错误" in result_message_raw or "无效的参数" in result_message_raw:
            self.invalid_sign_ids.add(sign_id)
            is_handled_definitively = True
            console_status_icon = "🚫"; console_status_color = Fore.MAGENTA; console_message = "失败：任务无效/不存在"
            console_details = result_message_raw
        else: 
            is_handled_definitively = False
            console_status_icon = "❔"; console_status_color = Fore.CYAN; console_message = "结果未知"
            console_details = result_message_raw

        self._print_formatted_sign_status(console_status_icon, console_status_color, class_id_context, sign_id, console_message, console_details)
        
        if should_send_notify and self.notification_manager and self.notification_manager.has_active_notifiers():
            event_context["event_type"] = event_type 
            event_context["status_message"] = console_message # Use the processed console message
            
            all_class_details = self.base_config.get("all_fetched_class_details", [])
            class_detail_found = next((cd for cd in all_class_details if str(cd.get("id")) == class_id_context), None)
            if class_detail_found:
                event_context["class_name"] = class_detail_found.get("name", class_id_context)
            
            # To get task_title, we'd need to pass the SignTaskDetails object or its title
            # For now, this is omitted from event_context unless fetched separately or passed down.
            # Example: event_context["task_title"] = task_item.get("title", "N/A") if task_item available

            if hasattr(self.notification_manager, 'dispatch') and callable(self.notification_manager.dispatch):
                 self.notification_manager.dispatch(event_context=event_context)
            else:
                 self.logger.log("SignService: notification_manager实例不正确或缺少dispatch方法。", LogLevel.ERROR)
        
        return is_handled_definitively