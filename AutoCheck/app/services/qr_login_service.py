# autocheckf/app/services/qr_login_service.py
import requests
import re
import time
import json # Still needed for other parts of the class, e.g. check_login_status response
import tkinter as tk
from io import BytesIO
from PIL import Image, ImageTk # type: ignore
from bs4 import BeautifulSoup, Tag # type: ignore
from typing import Dict, Any, Optional, List
import sys

from colorama import Fore, Style

from app.constants import AppConstants
from app.logger_setup import LoggerInterface, LogLevel
from app.config.models import UserInfo # UserInfo is a TypedDict


class QRLoginSystem:
    def __init__(self, logger: LoggerInterface):
        self.logger = logger
        self.base_k8n_url = "http://k8n.cn"
        self.qr_login_page_url = f"{self.base_k8n_url}/weixin/qrlogin/student"
        self.student_dashboard_url = f"{self.base_k8n_url}/student"
        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "max-age=0",
            "Host": "k8n.cn",
            "Referer": f"{self.base_k8n_url}/student/login?ref=%2Fstudent",
            "Upgrade-Insecure-Requests": "1",
        }
        self.session = requests.Session()
        self.max_login_check_attempts = 30
        self.login_check_interval = 2
        self.login_confirmed = False
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"

    def _get_request_headers(self, target_host: Optional[str] = "k8n.cn") -> Dict[str, str]:
        headers = self.base_headers.copy()
        headers["User-Agent"] = self.user_agent
        if target_host:
            headers["Host"] = target_host
        return headers

    def fetch_qr_code_url(self) -> Optional[str]:
        self.logger.log("正在获取二维码链接...", LogLevel.DEBUG)
        self.login_confirmed = False
        try:
            with requests.Session() as temp_qr_session:
                temp_qr_session.headers.update(self._get_request_headers(target_host="k8n.cn"))
                response = temp_qr_session.get(self.qr_login_page_url, timeout=15)
                response.raise_for_status()
                self.session.cookies.clear()
                self.session.cookies.update(temp_qr_session.cookies)
                self.logger.log(f"k8n.cn为QR会话设置的Cookies已捕获: {temp_qr_session.cookies.get_dict()}", LogLevel.DEBUG)

            if response.status_code == 200:
                pattern = r'https://mp.weixin.qq.com/cgi-bin/showqrcode\?ticket=([a-zA-Z0-9_\-=@]+)'
                match = re.search(pattern, response.text)
                if match:
                    qr_code_url = match.group(0)
                    self.logger.log(f"成功获取二维码链接: {qr_code_url[:70]}...", LogLevel.INFO)
                    return qr_code_url
                self.logger.log(f"未在页面响应中找到二维码链接。", LogLevel.ERROR)
                self.logger.log(f"响应体(部分): {response.text[:1000]}", LogLevel.DEBUG)
            else:
                self.logger.log(f"获取二维码链接请求失败，状态码: {response.status_code}", LogLevel.ERROR)
        except requests.RequestException as e:
            self.logger.log(f"获取二维码链接请求出错: {e}", LogLevel.ERROR, exc_info=True)
        return None

    def display_qr_code(self, qr_code_url: str) -> bool:
        self.logger.log(f"准备显示二维码 (URL: {qr_code_url[:70]}...)", LogLevel.DEBUG)
        qr_image_response: Optional[requests.Response] = None
        try:
            with requests.Session() as img_session:
                 img_session.headers.update({
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "User-Agent": self.user_agent,
                    "Referer": "https://mp.weixin.qq.com/"
                })
                 qr_image_response = img_session.get(qr_code_url, timeout=15)
                 qr_image_response.raise_for_status()

            img = Image.open(BytesIO(qr_image_response.content))
            img = img.resize((280, 280), Image.LANCZOS) # type: ignore
            root = tk.Tk()
            root.title("微信登录二维码")
            window_width, window_height = 320, 400
            screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
            center_x, center_y = int(screen_width/2 - window_width/2), int(screen_height/2 - window_height/2)
            root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
            root.resizable(False, False); root.attributes("-topmost", True); # type: ignore
            root.after(100, lambda: root.attributes("-topmost", True)) # type: ignore
            main_frame = tk.Frame(root, padx=20, pady=20); main_frame.pack(expand=True, fill=tk.BOTH)
            photo = ImageTk.PhotoImage(img)
            img_frame = tk.Frame(main_frame, bd=2, relief=tk.GROOVE); img_frame.pack(pady=(0, 15))
            img_label = tk.Label(img_frame, image=photo); img_label.pack(padx=5, pady=5); img_label.image = photo
            tk.Label(main_frame, text="请使用微信扫描二维码登录", font=("Microsoft YaHei", 12), fg="#333").pack(pady=(0, 10))
            root.x_root_drag, root.y_root_drag = 0,0; # type: ignore
            def start_move(event): root.x_root_drag,root.y_root_drag = event.x_root,event.y_root # type: ignore
            def do_move(event):
                deltax,deltay = event.x_root-root.x_root_drag,event.y_root-root.y_root_drag; # type: ignore
                x,y = root.winfo_x()+deltax,root.winfo_y()+deltay
                root.geometry(f"+{x}+{y}");root.x_root_drag,root.y_root_drag=event.x_root,event.y_root # type: ignore
            draggable_widgets = [main_frame,img_frame,img_label]+[c for c in main_frame.winfo_children() if isinstance(c,tk.Label)]
            for widget in draggable_widgets: widget.bind("<ButtonPress-1>",start_move);widget.bind("<B1-Motion>",do_move)
            root.after(100, root.focus_force)
            root.after(0, self.check_login_status, root, 0)
            root.mainloop()
            return True
        except requests.exceptions.HTTPError as e_http:
            self.logger.log(f"获取二维码图片HTTP错误: {e_http} (URL: {qr_code_url})。票据可能已失效或网络问题。", LogLevel.ERROR, exc_info=True)
        except requests.RequestException as e_req:
            self.logger.log(f"获取二维码图片网络请求失败: {e_req}", LogLevel.ERROR, exc_info=True)
        except tk.TclError: self.logger.log(f"Tkinter显示二维码时出错 (可能无GUI环境)。回退到URL打印。", LogLevel.WARNING)
        except ImportError: self.logger.log("错误：显示二维码需要 Pillow (PIL) 库。请运行 'pip install Pillow'", LogLevel.CRITICAL)
        except Exception as e_disp: self.logger.log(f"显示二维码时发生未知错误: {e_disp}", LogLevel.ERROR, exc_info=True)

        self.logger.log(f"无法以GUI方式显示二维码, 请手动复制以下URL到浏览器扫码: {qr_code_url}", LogLevel.WARNING)
        print(f"{Fore.YELLOW}请手动复制以下URL到浏览器扫码 (或在无头服务器上等待超时):{Style.RESET_ALL}\n{qr_code_url}")
        self.check_login_status(None, 0)
        timeout_for_manual_scan = self.max_login_check_attempts * self.login_check_interval + 5
        elapsed_time = 0
        while not self.login_confirmed and elapsed_time < timeout_for_manual_scan:
            time.sleep(1); elapsed_time += 1
        if not self.login_confirmed: self.logger.log("手动扫码/复制URL后登录未在规定时间内确认。", LogLevel.WARNING)
        return self.login_confirmed

    def check_login_status(self, root_window_or_none: Optional[tk.Tk], attempt: int):
        if self.login_confirmed:
             if root_window_or_none and root_window_or_none.winfo_exists():
                try: root_window_or_none.destroy()
                except tk.TclError: pass
             return
        if attempt >= self.max_login_check_attempts:
            self.logger.log("超过最大登录检查次数，登录失败 (超时)", LogLevel.ERROR)
            if sys.stdout.isatty(): print(f"\r{Fore.RED}登录超时，请关闭二维码窗口（如果存在）。{Style.RESET_ALL}         ")
            if root_window_or_none and root_window_or_none.winfo_exists():
                try: root_window_or_none.destroy()
                except tk.TclError: pass
            return
        check_url = f"{self.qr_login_page_url}?op=checklogin"
        try:
            response = self.session.get(check_url, headers=self._get_request_headers(target_host="k8n.cn"), timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get("status"):
                self.logger.log("微信扫码登录成功!", LogLevel.INFO)
                if sys.stdout.isatty(): print(f"\r{Fore.GREEN}✓ 微信扫码登录成功!{Style.RESET_ALL}                           ")
                self.handle_successful_login(response, data)
                if root_window_or_none and root_window_or_none.winfo_exists():
                    try: root_window_or_none.destroy()
                    except tk.TclError: pass
                return
            else:
                wait_msg = data.get('msg', '等待扫码')
                status_text = f"{wait_msg}... (检查 {attempt + 1}/{self.max_login_check_attempts})"
                if sys.stdout.isatty(): sys.stdout.write(f"\r{Fore.YELLOW}{status_text}{Style.RESET_ALL}\033[K"); sys.stdout.flush()
        except (requests.RequestException, json.JSONDecodeError, Exception) as e_check: # Catch json.JSONDecodeError explicitly
            log_msg = f"登录检查时发生错误 (尝试 {attempt + 1}): {type(e_check).__name__} - {e_check}"
            if sys.stdout.isatty(): print(f"\r{Fore.RED}{log_msg}{Style.RESET_ALL}\033[K")
            self.logger.log(log_msg, LogLevel.WARNING, exc_info=not isinstance(e_check, (requests.Timeout, json.JSONDecodeError)))
            if root_window_or_none and root_window_or_none.winfo_exists():
                try: root_window_or_none.destroy()
                except tk.TclError: pass
            self.login_confirmed = False; return # Stop checking on error
        if not self.login_confirmed:
            if root_window_or_none and root_window_or_none.winfo_exists():
                try: root_window_or_none.after(self.login_check_interval * 1000, self.check_login_status, root_window_or_none, attempt + 1)
                except tk.TclError: self.logger.log("尝试安排下一次检查时Tkinter窗口已销毁。", LogLevel.DEBUG); self.login_confirmed = False
            elif not root_window_or_none: # Non-GUI mode
                time.sleep(self.login_check_interval)
                self.check_login_status(None, attempt + 1)

    def handle_successful_login(self, initial_response: requests.Response, data_from_checklogin: Dict[str, Any]):
        self.logger.log("处理登录成功后的操作...", LogLevel.DEBUG)
        self.login_confirmed = True
        redirect_url_path = data_from_checklogin.get("url")
        if not redirect_url_path:
            self.logger.log("登录成功但未找到跳转URL路径", LogLevel.ERROR); self.login_confirmed = False; return
        final_redirect_url = self.base_k8n_url + redirect_url_path
        try:
            response_after_redirect = self.session.get(final_redirect_url, headers=self._get_request_headers(target_host="k8n.cn"), allow_redirects=True, timeout=10)
            response_after_redirect.raise_for_status()
            self.logger.log(f"登录后跳转完成, 最终URL: {response_after_redirect.url}", LogLevel.DEBUG)
            # Key cookies should now be in self.session.cookies
        except requests.RequestException as e:
            self.logger.log(f"登录后跳转请求失败: {e}", LogLevel.ERROR, exc_info=True); self.login_confirmed = False

    def _extract_user_and_class_info_from_html(self, html_content: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_content, "html.parser")
        user_info_data: UserInfo = {"uid": None, "uname": ""} 
        
        extracted_uid = None
        extracted_uname = None

        gconfig_script_tag = soup.find("script", string=re.compile(r"var\s+gconfig\s*=\s*{"))
        if gconfig_script_tag and gconfig_script_tag.string:
            script_content = gconfig_script_tag.string 
            self.logger.log(f"找到包含gconfig的script标签内容(部分): {script_content[:300]}", LogLevel.DEBUG)

            uid_match = re.search(r"uid\s*:\s*(\d+)", script_content)
            uname_match = re.search(r"uname\s*:\s*['\"](.*?)['\"]", script_content) 
            
            if uid_match: 
                extracted_uid = uid_match.group(1)
                self.logger.log(f"Regex从gconfig提取到 uid: '{extracted_uid}'", LogLevel.DEBUG)
            else:
                self.logger.log(f"未能从gconfig用Regex匹配到uid。Script内容(部分): {script_content[:300]}", LogLevel.WARNING)
            
            if uname_match: 
                extracted_uname = uname_match.group(1)
                self.logger.log(f"Regex从gconfig提取到 uname: '{extracted_uname}'", LogLevel.DEBUG)
            else:
                self.logger.log(f"未能从gconfig用Regex匹配到uname。Script内容(部分): {script_content[:300]}", LogLevel.WARNING)
        else:
            self.logger.log("未找到包含 'var gconfig' 的script标签。", LogLevel.WARNING)

        user_info_data["uid"] = extracted_uid
        user_info_data["uname"] = extracted_uname if extracted_uname is not None else ""
        
        # --- 提取班级信息 ---
        extracted_classes: List[Dict[str, str]] = []
        seen_ids = set()
        course_divs = soup.find_all("div", class_="course", attrs={"course_id": True})

        for div_tag in course_divs: 
            course_id_val = div_tag.get("course_id")
            if not course_id_val or not str(course_id_val).isdigit() or str(course_id_val) in seen_ids:
                continue
            
            course_id_str = str(course_id_val)
            course_name_str, class_code_str, description_str = "未知名称", "未知班级码", ""
            
            name_tag = div_tag.find("h5", class_="course_name")
            if name_tag and name_tag.string:
                course_name_str = name_tag.string.strip()
            
            description_str = course_name_str 

            p_tag = div_tag.find("p")
            if p_tag:
                code_span = p_tag.find("span", style=re.compile(r"float:\s*right", re.IGNORECASE))
                if code_span and code_span.string:
                    class_code_str = code_span.string.strip().replace("班级码", "").strip()
                
                p_clone_soup = BeautifulSoup(str(p_tag), 'html.parser')
                p_clone_tag_candidate = p_clone_soup.find('p')
                if p_clone_tag_candidate:
                    span_to_remove = p_clone_tag_candidate.find("span", style=re.compile(r"float:\s*right", re.IGNORECASE))
                    if span_to_remove:
                        span_to_remove.decompose()
                    
                    desc_text_parts = [text.strip() for text in p_clone_tag_candidate.get_text(separator=" ", strip=True).splitlines() if text.strip()]
                    desc_text_candidate_str = " ".join(desc_text_parts)

                    if desc_text_candidate_str:
                        description_str = desc_text_candidate_str
            
            extracted_classes.append({
                "id": course_id_str,
                "name": course_name_str,
                "code": class_code_str,
                "description": description_str
            })
            seen_ids.add(course_id_str)
        
        if not extracted_classes:
            self.logger.log("解析HTML未提取到任何班级详细信息。", LogLevel.DEBUG)
        
        self.logger.log(f"HTML解析完成: uid='{user_info_data['uid']}', uname='{user_info_data['uname']}', 班级数={len(extracted_classes)}", LogLevel.INFO)

        return {
            "user_info": user_info_data,
            "classes": sorted(extracted_classes, key=lambda x: x.get("name", ""))
        }

    def get_all_class_details_from_server(self) -> Dict[str, Any]:
        self.logger.log("静默从服务器获取所有班级详情和用户信息...", LogLevel.DEBUG)
        cookie_name_to_check_parts = AppConstants.COOKIE_PATTERN.split("=", 1)
        cookie_name_to_check = cookie_name_to_check_parts[0] if cookie_name_to_check_parts else "remember_student_"

        if not self.session.cookies.get(cookie_name_to_check):
            self.logger.log(f"Session中缺少关键Cookie (如 '{cookie_name_to_check}...') (get_all_class_details)。", LogLevel.WARNING)
            return {"status": "error", "message": "Cookie未在会话中设置或无效 (get_all_class_details)", 
                    "user_info": {"uid":None, "uname":""}, "all_fetched_class_details": []}
        try:
            response = self.session.get(self.student_dashboard_url, headers=self._get_request_headers(target_host="k8n.cn"), timeout=10)
            response.raise_for_status()
            
            if "/student/login" in response.url or "用户登录" in response.text:
                self.logger.log("获取班级详情时被重定向到登录页，Cookie可能已失效。", LogLevel.WARNING)
                return {"status": "error", "message": "Cookie已失效，请重新登录 (get_all_class_details)。",
                        "user_info": {"uid":None, "uname":""}, "all_fetched_class_details": []}

            extracted_data = self._extract_user_and_class_info_from_html(response.text)
            classes_info = extracted_data.get("classes", [])
            user_info = extracted_data.get("user_info") 

            if not user_info or not user_info.get("uid"):
                 self.logger.log("从服务器页面解析后，未能获得有效的用户信息(UID缺失)。", LogLevel.WARNING)
                 self.logger.log(f"UID缺失时的HTML响应片段 (get_all_class_details):\n{response.text[:2000]}", LogLevel.DEBUG)
                 return {"status": "error", "message": "无法从服务器获取有效的用户信息 (UID 缺失)。", 
                         "user_info": user_info if user_info else {"uid":None, "uname":""}, 
                         "all_fetched_class_details": classes_info}
            
            if not classes_info:
                self.logger.log("服务器未返回任何班级信息 (get_all_class_details)。", LogLevel.DEBUG)

            self.logger.log(f"成功从服务器静默获取到 {len(classes_info)} 个班级详情和用户信息: uid='{user_info.get('uid')}', uname='{user_info.get('uname')}'。", LogLevel.DEBUG)
            return {"status": "success", "user_info": user_info, "all_fetched_class_details": classes_info}
        except requests.RequestException as e_fetch:
            self.logger.log(f"静默获取所有班级详情时网络请求出错: {e_fetch}", LogLevel.ERROR, exc_info=True)
            return {"status": "error", "message": f"网络错误 (get_all_class_details): {e_fetch}", 
                    "user_info": {"uid":None, "uname":""}, "all_fetched_class_details": []}
        except Exception as e_proc: 
            self.logger.log(f"静默获取所有班级详情时发生未知错误: {e_proc}", LogLevel.ERROR, exc_info=True)
            return {"status": "error", "message": f"处理数据时未知错误 (get_all_class_details): {e_proc}", 
                    "user_info": {"uid":None, "uname":""}, "all_fetched_class_details": []}

    def fetch_logged_in_data_and_class_ids(self) -> Dict[str, Any]:
        self.logger.log("获取登录后用户数据并处理班级选择 (如果需要)...", LogLevel.INFO)
        
        if not self.login_confirmed:
            self.logger.log("尝试获取登录数据，但 QRLoginSystem.login_confirmed 为 False。", LogLevel.ERROR)
            return {"status": "error", "message": "内部错误：登录状态未确认。"}

        class_details_result = self.get_all_class_details_from_server()
        
        if class_details_result.get("status") != "success":
            return class_details_result

        user_info = class_details_result.get("user_info")
        classes_info = class_details_result.get("all_fetched_class_details", [])
        
        if not user_info or not user_info.get("uid"): 
            self.logger.log("成功获取班级列表但用户信息(UID)仍然缺失！", LogLevel.ERROR)
            return {"status": "error", "message": "获取到班级但未能确认用户信息(UID)。", 
                    "user_info": user_info, "all_fetched_class_details": classes_info}

        if not classes_info:
            self.logger.log("未找到任何班级信息可供选择 (fetch_logged_in_data_and_class_ids)。", LogLevel.WARNING)
            return {"status": "error", "message": "未找到任何班级信息。", 
                    "user_info": user_info, "all_fetched_class_details": []}

        selected_class_ids_list: List[str] = []
        if len(classes_info) == 1:
            selected_class = classes_info[0]
            selected_class_ids_list.append(selected_class["id"])
            self.logger.log(f"自动选择唯一的班级: ID {selected_class['id']} - {selected_class.get('name', 'N/A')}", LogLevel.INFO)
            print(f"{Fore.GREEN}检测到您只有一个班级，已自动选择: {selected_class.get('name', 'N/A')} (ID: {selected_class['id']}){Style.RESET_ALL}")
        else: 
            print(f"\n{Fore.GREEN}找到多个班级信息，请选择您要操作的班级：{Style.RESET_ALL}")
            for idx, cls_info in enumerate(classes_info, start=1):
                display_name = cls_info.get('name', '未知名称')
                description = cls_info.get('description', '')
                code = cls_info.get('code', 'N/A')
                if description and description.strip() and description.strip().lower() != display_name.lower():
                     display_name += f" - {description.strip()}"
                print(f"  {idx}. {Fore.CYAN}{display_name}{Style.RESET_ALL} (ID: {cls_info['id']}, 班级码: {code})")
            
            all_option_num = len(classes_info) + 1
            print(f"  {all_option_num}. {Fore.YELLOW}全选所有列出的班级{Style.RESET_ALL}")
            
            while True: 
                choice_input_str = input(f"请输入序号 (1-{len(classes_info)}), '{all_option_num}' 全选, 或用逗号分隔多个 (或 'c' 取消): ").strip().lower()
                if not choice_input_str:
                    print(f"{Fore.RED}输入不能为空。{Style.RESET_ALL}")
                    continue
                if choice_input_str == 'c':
                    self.logger.log("用户取消班级选择。", LogLevel.INFO)
                    return {"status": "cancelled", "message": "用户取消班级选择", 
                            "user_info": user_info, "all_fetched_class_details": classes_info}
                
                temp_selected_ids_set: Set[str] = set()
                valid_input = True
                
                if choice_input_str == str(all_option_num):
                    for c_info in classes_info:
                        temp_selected_ids_set.add(c_info["id"])
                    print(f"{Fore.GREEN}已选所有 {len(temp_selected_ids_set)} 个班级。{Style.RESET_ALL}")
                else:
                    parts = choice_input_str.split(',')
                    for part_val in parts:
                        part_val = part_val.strip()
                        if not part_val.isdigit():
                            valid_input = False; break
                        try:
                            choice_idx = int(part_val) - 1
                            if not (0 <= choice_idx < len(classes_info)):
                                valid_input = False; break
                            temp_selected_ids_set.add(classes_info[choice_idx]["id"])
                        except ValueError:
                            valid_input = False; break
                
                if not valid_input or not temp_selected_ids_set:
                    print(f"{Fore.RED}输入无效或选择为空，请重试。{Style.RESET_ALL}")
                    continue
                
                selected_class_ids_list = sorted(list(temp_selected_ids_set))
                break
        
        if not selected_class_ids_list:
            return {"status": "error", "message": "未选择任何班级ID。", 
                    "user_info": user_info, "all_fetched_class_details": classes_info}
        
        final_cookie_parts = []
        for cookie in self.session.cookies:
            if "k8n.cn" in cookie.domain or not cookie.domain:
                final_cookie_parts.append(f"{cookie.name}={cookie.value}")
        
        full_cookie_str = "; ".join(final_cookie_parts)
        cookie_name_pattern_base = AppConstants.COOKIE_PATTERN.split("=",1)[0]
        if cookie_name_pattern_base not in full_cookie_str:
            self.logger.log(f"关键登录Cookie (如 '{cookie_name_pattern_base}=...') 在选择班级后未能正确序列化到Cookie字符串中!", LogLevel.CRITICAL)
            self.logger.log(f"当前Session Cookies: {self.session.cookies.get_dict()}", LogLevel.DEBUG)
            self.logger.log(f"序列化后的Cookie字符串: {full_cookie_str}", LogLevel.DEBUG)
            return {"status": "error", "message": f"关键登录Cookie '{cookie_name_pattern_base}' 在会话中丢失或未能序列化。",
                    "user_info": user_info, "all_fetched_class_details": classes_info}
        
        self.logger.log(f"成功获取并序列化Cookie，已选择班级ID(s): {selected_class_ids_list} (用户: uid='{user_info.get('uid')}', uname='{user_info.get('uname')}')", LogLevel.INFO)
        self.logger.log(f"序列化后的完整Cookie字符串 (部分显示): {full_cookie_str[:50]}...", LogLevel.DEBUG)

        return {"status": "success", 
                "cookie": full_cookie_str, 
                "user_info": user_info,
                "class_ids": selected_class_ids_list, 
                "all_fetched_class_details": classes_info}