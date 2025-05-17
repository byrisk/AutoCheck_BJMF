# autocheckf/app/cli/setup_wizard.py
import sys
import threading
import time
from typing import Dict, Any, Optional, Callable, List
from pydantic import ValidationError # type: ignore
from copy import deepcopy
import re
import http.cookies
# import requests # Not directly used here, QRLoginSystem handles its requests

from colorama import Fore, Style

from app.constants import AppConstants, SCRIPT_VERSION
from app.logger_setup import LoggerInterface, LogLevel
from app.config.manager import ConfigManager
from app.config.models import ConfigModel, SelectedSchoolData, NotificationSettings, UserInfo # Ensure UserInfo is imported
from app.services.location_engine import LocationEngine, LocationError, ConfigError
from app.services.qr_login_service import QRLoginSystem
from datetime import datetime


class SetupWizard:
    def __init__(self, config_manager: ConfigManager, logger: LoggerInterface, location_engine: Optional[LocationEngine]):
        self.manager = config_manager
        self.logger = logger
        self.location_engine = location_engine
        self.login_system = QRLoginSystem(logger)
        self.scanned_data: Optional[Dict[str, Any]] = None

    def _parse_cookie_string_to_dict(self, cookie_string: str) -> Dict[str, str]:
        cookie_dict = {}
        if not cookie_string: return cookie_dict
        try:
            ck = http.cookies.SimpleCookie(); ck.load(cookie_string)
            for key, morsel in ck.items(): cookie_dict[key] = morsel.value
            if cookie_dict: return cookie_dict
        except Exception: self.logger.log("使用 http.cookies 解析 Cookie 失败，尝试简单分割。", LogLevel.DEBUG)
        parts = cookie_string.split(';')
        for part in parts:
            if '=' in part: name, value = part.split('=', 1); cookie_dict[name.strip()] = value.strip()
        return cookie_dict

    def _validate_cookie_for_auto_fetch(self, cookie_string: Optional[str]) -> bool:
        if not cookie_string: return False
        if AppConstants.COOKIE_PATTERN and re.search(AppConstants.COOKIE_PATTERN, cookie_string): return True
        self.logger.log(f"存储的 Cookie '{cookie_string[:30]}...' 不符合格式 ('{AppConstants.COOKIE_PATTERN}')。", LogLevel.DEBUG)
        return False

    def _validate_current_config_quietly(self, config_to_validate: Dict[str, Any]) -> bool:
        if not config_to_validate: return False
        try:
            required_fields_for_quiet = ["cookie", "class_ids", "lat", "lng", "acc", "user_info"]
            for req_field in required_fields_for_quiet:
                field_value = config_to_validate.get(req_field)
                if req_field == "class_ids":
                    if not field_value or not isinstance(field_value, list) or not field_value or not all(str(item).strip() for item in field_value): # Ensure not empty list
                        self.logger.log(f"静默验证：必需字段 '{req_field}' 列表为空或包含无效值。", LogLevel.DEBUG); return False
                elif req_field == "user_info":
                    if not field_value or not isinstance(field_value, dict) or \
                       not field_value.get("uid"): # UID is the most critical part of user_info
                        self.logger.log(f"静默验证：必需字段 '{req_field}' (uid) 缺失或无效。", LogLevel.DEBUG); return False
                elif not field_value:
                    self.logger.log(f"静默验证：必需字段 '{req_field}' 缺失或为空。", LogLevel.DEBUG); return False
            if "cookie" in config_to_validate and not self._validate_cookie_for_auto_fetch(config_to_validate.get("cookie")):
                self.logger.log(f"静默验证：Cookie 格式不正确。", LogLevel.DEBUG); return False
            config_for_pydantic = {k:v for k,v in config_to_validate.items() if k != "all_fetched_class_details"}
            ConfigModel(**config_for_pydantic)
            return True
        except ValidationError as ve: self.logger.log(f"静默验证：Pydantic模型验证失败 - {ve.errors()}", LogLevel.DEBUG); return False
        except Exception as e: self.logger.log(f"静默验证时发生意外错误: {e}", LogLevel.DEBUG, exc_info=True); return False

    def init_config(self) -> Dict[str, Any]:
        self.logger.log("初始化配置检查...", LogLevel.INFO)
        existing_config = self.manager.config # This is a dict from storage or {}
        
        # Try to use existing_config if it's fully valid for a silent start
        if existing_config and self._validate_current_config_quietly(existing_config):
            self.logger.log("检测到完整历史配置，尝试静默刷新用户信息与班级详情...", LogLevel.INFO)
            print(f"{Fore.CYAN}检测到有效历史配置，正在静默刷新信息...{Style.RESET_ALL}")
            try:
                parsed_cookies = self._parse_cookie_string_to_dict(existing_config["cookie"])
                if not parsed_cookies: raise ValueError("无法解析已存Cookie (init_config)")

                self.login_system.session.cookies.clear()
                self.login_system.session.cookies.update(parsed_cookies)
                server_data_result = self.login_system.get_all_class_details_from_server() # NO PROMPT

                if server_data_result.get("status") == "success":
                    server_user_info = server_data_result.get("user_info")
                    server_classes = server_data_result.get("all_fetched_class_details", [])
                    stored_user_info = existing_config.get("user_info") # Should exist due to _validate_current_config_quietly

                    if not server_user_info or not server_user_info.get("uid"):
                        self.logger.log("静默刷新：服务器未能返回有效的用户信息(UID)。Cookie可能已失效。", LogLevel.ERROR)
                        print(f"{Fore.RED}错误：无法验证当前登录状态，Cookie可能已过期。请重新配置。{Style.RESET_ALL}")
                        current_partial_data = deepcopy(existing_config); current_partial_data.pop("cookie",None); current_partial_data.pop("class_ids",None); current_partial_data.pop("user_info",None)
                        return self._first_run_config_wizard(partial_data=current_partial_data)

                    if stored_user_info and stored_user_info.get("uid") != server_user_info.get("uid"):
                        self.logger.log(f"Cookie对应的用户UID ({server_user_info.get('uid')}) 与配置中UID ({stored_user_info.get('uid')}) 不符！需要重新登录。", LogLevel.CRITICAL)
                        print(f"{Fore.RED}错误：当前Cookie与配置的用户信息不符，请重新登录。{Style.RESET_ALL}")
                        current_partial_data = deepcopy(existing_config); current_partial_data.pop("cookie",None); current_partial_data.pop("class_ids",None); current_partial_data.pop("user_info",None)
                        return self._first_run_config_wizard(partial_data=current_partial_data)

                    server_class_ids_set = {str(cls.get("id")) for cls in server_classes if cls.get("id")}
                    stored_class_ids = existing_config.get("class_ids", []) 
                    validated_class_ids = [cid for cid in stored_class_ids if str(cid) in server_class_ids_set]

                    if not validated_class_ids and stored_class_ids: 
                        self.logger.log(f"所有已存储班级ID ({stored_class_ids}) 不再有效。需重新选择。", LogLevel.WARNING)
                        print(f"{Fore.YELLOW}警告：您配置的班级已全部失效，请重新选择。{Style.RESET_ALL}")
                        config_for_wizard = deepcopy(existing_config); config_for_wizard["class_ids"] = [] 
                        return self._first_run_config_wizard(partial_data=config_for_wizard)
                    elif len(validated_class_ids) < len(stored_class_ids):
                        self.logger.log(f"部分已存储班级ID不再有效。原: {stored_class_ids}, 现: {validated_class_ids}。将使用剩余有效班级。", LogLevel.WARNING)
                        print(f"{Fore.YELLOW}警告：您配置的部分班级信息已更新。当前将使用有效班级。建议稍后手动检查配置。{Style.RESET_ALL}")
                    
                    final_runtime_config = deepcopy(existing_config)
                    final_runtime_config["class_ids"] = validated_class_ids 
                    final_runtime_config["all_fetched_class_details"] = server_classes 
                    final_runtime_config["user_info"] = server_user_info 
                    
                    config_to_save_to_disk = {k:v for k,v in final_runtime_config.items() if k != "all_fetched_class_details"}
                    ConfigModel(**config_to_save_to_disk) 
                    self.manager.config = ConfigModel(**config_to_save_to_disk).model_dump()
                    self.manager.save()
                    self.logger.log("配置已通过静默刷新验证/更新并保存。启动程序...", LogLevel.INFO)
                    return final_runtime_config
                
                else: # get_all_class_details_from_server failed
                    self.logger.log(f"静默刷新信息失败: {server_data_result.get('message', '未知错误')}. Cookie可能已失效。", LogLevel.WARNING)
                    print(f"{Fore.YELLOW}Cookie可能已过期或无效，需要重新配置凭证。{Style.RESET_ALL}")
                    current_partial_data = deepcopy(existing_config) if existing_config else {}
                    current_partial_data.pop("cookie", None); current_partial_data.pop("class_ids", None); current_partial_data.pop("user_info", None); current_partial_data.pop("all_fetched_class_details", None)
                    return self._first_run_config_wizard(partial_data=current_partial_data)

            except (ValueError, ValidationError, Exception) as e_silent_refresh: 
                self.logger.log(f"静默刷新配置时发生错误: {e_silent_refresh}. 转入完整配置。", LogLevel.ERROR, exc_info=True)
                current_partial_data = deepcopy(existing_config) if existing_config else {}
                current_partial_data.pop("cookie", None); current_partial_data.pop("class_ids", None); current_partial_data.pop("user_info", None); current_partial_data.pop("all_fetched_class_details", None)
                return self._first_run_config_wizard(partial_data=current_partial_data)
        
        # Fallback: If config wasn't "quietly valid" or some other path led here.
        self.logger.log("配置不满足静默启动条件或需要用户交互，进入配置向导...", LogLevel.INFO)
        return self._first_run_config_wizard(partial_data=existing_config if existing_config else None)

    def _first_run_config_wizard(self, partial_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.logger.log(f"\n{Fore.GREEN}🌟 欢迎使用 {AppConstants.APP_NAME} v{SCRIPT_VERSION} 🌟{Style.RESET_ALL}", LogLevel.INFO)
        if partial_data: print(f"{Fore.YELLOW}配置信息不完整或需更新，开始配置向导（基于部分现有数据）。{Style.RESET_ALL}")
        else: print(f"{Fore.YELLOW}首次运行，开始初始配置向导。{Style.RESET_ALL}")
        print("=" * 70)
        
        new_config_data: Dict[str, Any] = deepcopy(partial_data) if partial_data else {}
        
        disclaimer_version_to_keep = None
        if partial_data and "disclaimer_agreed_version" in partial_data: disclaimer_version_to_keep = partial_data["disclaimer_agreed_version"]
        elif self.manager.config and self.manager.config.get("disclaimer_agreed_version"): disclaimer_version_to_keep = self.manager.config["disclaimer_agreed_version"]
        if disclaimer_version_to_keep: new_config_data["disclaimer_agreed_version"] = disclaimer_version_to_keep

        try:
            self.logger.log("步骤 1/3: 设置/更新登录凭证...", LogLevel.INFO)
            self._setup_login_credentials(new_config_data) 
            if not new_config_data.get("cookie") or \
               not new_config_data.get("class_ids") or \
               not new_config_data.get("user_info") or \
               not new_config_data.get("user_info", {}).get("uid"):
                raise ConfigError("登录凭证（Cookie, 班级ID, 用户UID）设置失败或用户取消，配置中止。")

            self.logger.log("步骤 2/3: 设置位置信息...", LogLevel.INFO)
            is_location_update = bool(new_config_data.get("lat") and new_config_data.get("lng") and new_config_data.get("acc"))
            if not self._setup_location_interactive(new_config_data, is_update=is_location_update): 
                 raise ConfigError("位置信息设置失败或中止。")
            if not all(k in new_config_data and str(new_config_data.get(k,"")).strip() for k in ("lat", "lng", "acc")):
                raise ConfigError("关键位置字段 (lat, lng, acc) 丢失或为空。")

            self.logger.log("步骤 3/3: 设置其他选项...", LogLevel.INFO)
            self._setup_other_settings(new_config_data, is_update=bool(partial_data))

            current_total_success = new_config_data.get('total_successful_sign_ins', 0)
            new_config_data.setdefault('total_successful_sign_ins', current_total_success)
            
            config_for_save = {k: v for k, v in new_config_data.items() if k != "all_fetched_class_details"}
            all_details_runtime = new_config_data.get("all_fetched_class_details")

            validated_config_obj = ConfigModel(**config_for_save)
            final_config_dict_to_save = validated_config_obj.model_dump()

            self.manager.config = final_config_dict_to_save
            self.manager.save() 
            self.logger.log(f"\n{Fore.GREEN}✅ 配置完成并已成功保存！{Style.RESET_ALL}", LogLevel.INFO) 
            
            final_config_for_runtime = deepcopy(final_config_dict_to_save)
            if all_details_runtime: final_config_for_runtime["all_fetched_class_details"] = all_details_runtime
            return final_config_for_runtime
            
        except KeyboardInterrupt:
            print("\n用户在配置向导过程中中断操作。程序即将退出。")
            self.logger.log("用户中断了配置向导。", LogLevel.INFO)
            raise ConfigError("用户中断配置向导") from None
        except (ValidationError, ValueError, ConfigError, LocationError) as e: 
            self.logger.log(f"配置向导在数据验证或处理时出错: {e}", LogLevel.ERROR, exc_info=True)
            if isinstance(e, ValidationError): self._handle_pydantic_validation_error(e)
            else: print(f"{Fore.RED}配置错误: {e}{Style.RESET_ALL}")
            print(f"{Fore.RED}请检查您的输入或相关文件后重试。程序即将退出。{Style.RESET_ALL}")
            raise 
        except Exception as e_fatal: 
            self.logger.log(f"配置向导发生未知严重错误: {e_fatal}", LogLevel.CRITICAL, exc_info=True)
            print(f"{Fore.RED}配置过程中发生意外错误: {e_fatal}{Style.RESET_ALL}\n程序即将退出。")
            raise ConfigError(f"配置向导未知严重错误: {e_fatal}") from e_fatal
            
    def _setup_login_credentials(self, config_data_dict: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.CYAN}=== 登录凭证设置 ==={Style.RESET_ALL}", LogLevel.INFO)
        
        has_existing_cookie = config_data_dict.get("cookie") and self._validate_cookie_for_auto_fetch(config_data_dict.get("cookie"))
        has_existing_class_ids_and_user = has_existing_cookie and \
                                          config_data_dict.get("class_ids") and \
                                          isinstance(config_data_dict.get("class_ids"), list) and \
                                          len(config_data_dict.get("class_ids",[])) > 0 and \
                                          config_data_dict.get("user_info", {}).get("uid")


        if has_existing_cookie:
             current_cookie_short = config_data_dict['cookie'][:15] + "..." + config_data_dict['cookie'][-15:] if len(config_data_dict['cookie']) > 30 else config_data_dict['cookie']
             print(f"{Fore.CYAN}当前检测到Cookie: {current_cookie_short}{Style.RESET_ALL}")
             if has_existing_class_ids_and_user:
                uname_disp = config_data_dict.get('user_info',{}).get('uname','N/A')
                print(f"{Fore.CYAN}当前已配置用户: {uname_disp}, 班级数: {len(config_data_dict['class_ids'])}{Style.RESET_ALL}")
             else:
                print(f"{Fore.YELLOW}但班级或用户信息不完整/需确认。{Style.RESET_ALL}")

             reconfig_choice = input("是否要使用此Cookie重新获取/选择班级，或更换Cookie/重新扫码? (y=是, n=尝试使用当前Cookie [默认: n]): ").strip().lower()
             if reconfig_choice != 'y':
                 self.logger.log("用户选择尝试使用现有Cookie。", LogLevel.INFO)
                 try: 
                    self.login_system.session.cookies.clear()
                    self.login_system.session.cookies.update(self._parse_cookie_string_to_dict(config_data_dict["cookie"]))
                    login_data_result = self.login_system.fetch_logged_in_data_and_class_ids() 
                    
                    if login_data_result and login_data_result.get("status") == "success":
                        # Check if essential data is present after fetch
                        if login_data_result.get("class_ids") and login_data_result.get("user_info",{}).get("uid"):
                            config_data_dict.update(login_data_result) 
                            self.logger.log("使用现有Cookie成功刷新/选择了班级和用户信息。", LogLevel.INFO)
                            return # Successfully used existing cookie and got necessary info
                        else:
                            self.logger.log("使用现有Cookie获取信息后，班级ID或用户UID仍缺失。", LogLevel.WARNING)
                    elif login_data_result and login_data_result.get("status") == "cancelled":
                        self.logger.log("用户在使用现有Cookie选择班级时取消。", LogLevel.INFO) 
                    else: 
                        self.logger.log(f"使用现有Cookie获取班级失败: {login_data_result.get('message')}", LogLevel.WARNING)
                        print(f"{Fore.YELLOW}使用当前Cookie获取班级列表失败，请尝试重新登录或输入新Cookie。{Style.RESET_ALL}")
                 except Exception as e_use_exist:
                    self.logger.log(f"尝试使用现有Cookie时发生错误: {e_use_exist}", LogLevel.ERROR)
        
        original_disclaimer = config_data_dict.get("disclaimer_agreed_version") 
        temp_loc_data = {k: config_data_dict.get(k) for k in ["lat","lng","acc","selected_school","enable_school_based_randomization"] if k in config_data_dict}
        config_data_dict.clear() 
        if original_disclaimer: config_data_dict["disclaimer_agreed_version"] = original_disclaimer
        config_data_dict.update(temp_loc_data) # Preserve location info if it was already set

        while True:
            print("\n请选择获取/更新登录凭证的方式：")
            print(f"1. {Fore.GREEN}微信扫码登录 (推荐){Style.RESET_ALL}")
            print(f"2. {Fore.YELLOW}手动输入Cookie (将自动获取班级列表并提示选择){Style.RESET_ALL}")
            choice = input("请选择 (1/2, 回车默认1): ").strip().lower() or "1"
            
            login_method_successful = False
            if choice == "1":
                qr_success = self._perform_qr_scan_for_credentials() 
                if qr_success and self.scanned_data:
                    config_data_dict.update(self.scanned_data); login_method_successful = True
                else: print(f"{Fore.YELLOW}扫码登录未成功或被取消，请重试或选择其他方式。{Style.RESET_ALL}")
            elif choice == "2":
                self._manual_input_credentials(config_data_dict) 
                if config_data_dict.get("cookie") and config_data_dict.get("class_ids") and config_data_dict.get("user_info",{}).get("uid"):
                    login_method_successful = True
                else: 
                    print(f"{Fore.RED}通过Cookie获取凭证未能完成或被取消，请重试。{Style.RESET_ALL}")
                    config_data_dict.pop("cookie", None); config_data_dict.pop("class_ids", None); config_data_dict.pop("user_info", None); config_data_dict.pop("all_fetched_class_details", None)
            else: print(f"{Fore.RED}无效输入，请输入1或2。{Style.RESET_ALL}")

            if login_method_successful:
                if not config_data_dict.get("user_info") or not config_data_dict.get("user_info",{}).get("uid"):
                    self.logger.log("凭证设置后未能获取完整的用户信息(UID)。流程可能不完整。", LogLevel.ERROR)
                    print(f"{Fore.RED}错误：未能获取到关键用户信息(UID)，请重试凭证设置。{Style.RESET_ALL}")
                    config_data_dict.pop("cookie", None); config_data_dict.pop("class_ids", None); config_data_dict.pop("user_info", None); config_data_dict.pop("all_fetched_class_details", None)
                    login_method_successful = False; continue 
                break 

    def _perform_qr_scan_for_credentials(self) -> bool:
        self.scanned_data = None ; self.login_system.login_confirmed = False
        self.logger.log("\n🔄 准备微信扫码登录...", LogLevel.INFO)
        print(f"\n{Fore.CYAN}--- 微信扫码登录 ---{Style.RESET_ALL}")
        print("将尝试获取登录二维码，请准备使用微信扫描。")
        qr_url = self.login_system.fetch_qr_code_url()
        if not qr_url: self.logger.log("无法获取二维码URL。", LogLevel.WARNING); print(f"{Fore.RED}获取二维码失败...{Style.RESET_ALL}"); return False
        self.login_system.display_qr_code(qr_url) 
        if not self.login_system.login_confirmed:
            self.logger.log("二维码流程结束，但登录未被最终确认。", LogLevel.WARNING); return False
        self.logger.log("微信扫码登录已确认，获取登录后数据(包括班级选择)...", LogLevel.INFO)
        login_data_result = self.login_system.fetch_logged_in_data_and_class_ids() 
        if login_data_result and login_data_result.get("status") == "success":
            self.scanned_data = login_data_result 
            if not self.scanned_data.get("class_ids") or not self.scanned_data.get("user_info",{}).get("uid"): 
                self.logger.log("扫码登录并选择班级后，未获得班级ID或用户信息。", LogLevel.ERROR); print(f"{Fore.RED}错误：登录成功但班级选择或用户信息获取未完成。{Style.RESET_ALL}"); return False
            self.logger.log(f"✅ 扫码登录并选择班级成功！班级数: {len(self.scanned_data.get('class_ids',[]))}", LogLevel.INFO); print(f"{Fore.GREEN}凭证及选定班级获取成功！{Style.RESET_ALL}"); return True
        else:
            error_message = login_data_result.get("message", "未知错误") if login_data_result else "获取登录数据失败"
            self.logger.log(f"扫码登录后获取数据/选择班级失败: {error_message}", LogLevel.WARNING); print(f"{Fore.YELLOW}警告：登录后未能完成信息提取或班级选择。详情: {error_message}{Style.RESET_ALL}"); return False

    def _manual_input_credentials(self, config_data_dict: Dict[str, Any]) -> None:
        self.logger.log(f"\n{Fore.YELLOW}⚠️ 请手动输入Cookie以自动获取班级列表{Style.RESET_ALL}", LogLevel.INFO)
        print(f"\n{Fore.CYAN}--- 手动输入Cookie ---{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Cookie 通常形如: remember_student_xxxxxxxx=yyyyyyyyyyyyyy{Style.RESET_ALL}")
        user_cookie = self._get_validated_input("请输入完整的Cookie字符串", ConfigModel.validate_cookie)
        if not user_cookie: 
            print(f"{Fore.RED}Cookie 输入为空，操作取消。{Style.RESET_ALL}"); self.logger.log("用户未输入Cookie。", LogLevel.INFO); return 
        print(f"{Fore.CYAN}正在尝试使用您提供的 Cookie 获取班级列表...{Style.RESET_ALL}")
        try:
            parsed_cookies = self._parse_cookie_string_to_dict(user_cookie)
            if not parsed_cookies: raise ValueError("无法解析用户提供的Cookie字符串。")
            self.login_system.session.cookies.clear()
            self.login_system.session.cookies.update(parsed_cookies)
            login_data_result = self.login_system.fetch_logged_in_data_and_class_ids()
            if login_data_result and login_data_result.get("status") == "success":
                config_data_dict["cookie"] = login_data_result.get("cookie")
                config_data_dict["class_ids"] = login_data_result.get("class_ids", [])
                config_data_dict["user_info"] = login_data_result.get("user_info") 
                config_data_dict["all_fetched_class_details"] = login_data_result.get("all_fetched_class_details", [])
                if not config_data_dict.get("class_ids") or not config_data_dict.get("user_info",{}).get("uid"): 
                    self.logger.log("手动输入Cookie后，用户未选择任何班级ID或用户信息不完整。", LogLevel.WARNING)
                    print(f"{Fore.YELLOW}警告：您没有选择任何班级或用户信息不完整，凭证信息未完整设置。{Style.RESET_ALL}")
                    config_data_dict.pop("cookie", None); config_data_dict.pop("class_ids", None); config_data_dict.pop("user_info", None)
                else: self.logger.log(f"用户通过手动Cookie输入并成功选择班级ID(s): {config_data_dict['class_ids']}", LogLevel.INFO)
            elif login_data_result and login_data_result.get("status") == "cancelled":
                self.logger.log("用户在手动Cookie流程中取消了班级选择。", LogLevel.INFO); print(f"{Fore.YELLOW}班级选择已取消。{Style.RESET_ALL}")
            else:
                error_message = login_data_result.get("message", "获取班级列表失败") if login_data_result else "获取班级列表失败"
                self.logger.log(f"手动输入Cookie后获取班级列表失败: {error_message}", LogLevel.WARNING); print(f"{Fore.RED}错误：{error_message}{Style.RESET_ALL}")
        except (requests.exceptions.RequestException, ValueError, Exception) as e_manual_fetch: 
            self.logger.log(f"手动输入Cookie后处理时发生错误: {e_manual_fetch}", LogLevel.ERROR, exc_info=True); print(f"{Fore.RED}处理错误：{str(e_manual_fetch)[:100]}{Style.RESET_ALL}")

    def _setup_location_interactive(self, config_data_dict: Dict[str, Any], is_update: bool) -> bool:
        current_config_for_defaults = self.manager.config if is_update and self.manager.config else {}
        if not is_update and config_data_dict: current_config_for_defaults = {**current_config_for_defaults, **config_data_dict}
        mode_description = "更新" if is_update else "设置"; self.logger.log(f"\n{Fore.CYAN}=== {mode_description}位置信息 ==={Style.RESET_ALL}", LogLevel.INFO)
        can_use_school_selection = self.location_engine is not None and self.location_engine.all_schools
        auto_mode_choice_input = ''
        if can_use_school_selection:
            prompt_text = "是否尝试通过学校ID/名称自动设置位置？ (y/n"; 
            current_is_auto = config_data_dict.get("enable_school_based_randomization", current_config_for_defaults.get("enable_school_based_randomization", False))
            default_choice_char = 'y' if not is_update else ('y' if current_is_auto else 'n'); 
            prompt_suffix = f", 回车默认'{default_choice_char}'"
            if is_update or (config_data_dict and "enable_school_based_randomization" in config_data_dict): # check if key exists
                prompt_suffix += f", 当前模式: {'自动' if current_is_auto else '手动'}"
            prompt_suffix += "): "; auto_mode_choice_input = input(prompt_text + prompt_suffix).strip().lower()
            if not auto_mode_choice_input: auto_mode_choice_input = default_choice_char
        else: print(f"{Fore.YELLOW}校区数据文件未加载，仅支持手动输入坐标。{Style.RESET_ALL}"); auto_mode_choice_input = 'n'
        if auto_mode_choice_input == 'y' and self.location_engine:
            selected_school_obj_data: Optional[SelectedSchoolData] = self._select_school_interactive() 
            if selected_school_obj_data and isinstance(selected_school_obj_data, dict): 
                try:
                    generated_coords = self.location_engine.generate_location(selected_school_obj_data)
                    print(f"\n{Fore.CYAN}为学校 '{selected_school_obj_data['id']}: {selected_school_obj_data['addr']}' 生成推荐位置：{Style.RESET_ALL}")
                    print(f"  来源: {generated_coords['from_location_name']}\n  纬度: {Fore.GREEN}{generated_coords['lat']}{Style.RESET_ALL}\n  经度: {Fore.GREEN}{generated_coords['lng']}{Style.RESET_ALL}\n  精度: {Fore.GREEN}{generated_coords['accuracy']}m{Style.RESET_ALL}")
                    try: print(f"  地图: {self.location_engine.get_map_link(float(generated_coords['lat']), float(generated_coords['lng']), selected_school_obj_data['addr'])}")
                    except Exception as map_e: self.logger.log(f"生成地图链接出错: {map_e}", LogLevel.WARNING)
                    if self._confirm_generated_coordinates(generated_coords, selected_school_obj_data, config_data_dict): return True
                    else: print(f"{Fore.YELLOW}好的，将切换到手动输入位置信息。{Style.RESET_ALL}")
                except (LocationError, Exception) as e: self.logger.log(f"从学校生成坐标出错: {e}", LogLevel.ERROR, exc_info=True); print(f"{Fore.RED}自动生成坐标失败: {e}。请手动输入。{Style.RESET_ALL}")
        print(f"\n{Fore.YELLOW}--- 手动位置信息设置 ---{Style.RESET_ALL}")
        lat_val = config_data_dict.get('lat', current_config_for_defaults.get('lat', ''))
        lng_val = config_data_dict.get('lng', current_config_for_defaults.get('lng', ''))
        acc_val = config_data_dict.get('acc', current_config_for_defaults.get('acc', AppConstants.DEFAULT_ACCURACY))
        config_data_dict["lat"] = self._get_validated_input("纬度", ConfigModel.validate_latitude, current_value_for_update=str(lat_val))
        config_data_dict["lng"] = self._get_validated_input("经度", ConfigModel.validate_longitude, current_value_for_update=str(lng_val))
        config_data_dict["acc"] = self._get_validated_input("精度 (建议 1-100)", ConfigModel.validate_accuracy, current_value_for_update=str(acc_val))
        config_data_dict["selected_school"] = None ; config_data_dict["enable_school_based_randomization"] = False
        self.logger.log("用户设置了手动精确坐标。", LogLevel.INFO); return True

    def _confirm_generated_coordinates(self, generated_coords: Dict[str, Any], school_data: SelectedSchoolData, config_data_dict: Dict[str, Any]) -> bool:
        while True:
            confirm = input("是否使用此推荐位置？ (y/n, 或输入 'a' 手动调整此位置, [默认: y]): ").strip().lower() or 'y'
            if confirm == 'y':
                config_data_dict.update({"lat":str(generated_coords['lat']), "lng":str(generated_coords['lng']), "acc":str(generated_coords['accuracy'])}) 
                config_data_dict["selected_school"] = school_data 
                rand_choice = input("是否希望基于学校范围在运行时随机化坐标? (y/n, [默认: y]): ").lower().strip() or 'y'
                config_data_dict["enable_school_based_randomization"] = (rand_choice == 'y')
                self.logger.log(f"用户接受自动生成坐标。运行时随机化: {config_data_dict['enable_school_based_randomization']}", LogLevel.INFO); return True
            elif confirm == 'a':
                print(f"{Fore.YELLOW}请输入调整后的坐标信息（基于当前推荐值）：{Style.RESET_ALL}")
                adj_lat = self._get_validated_input("纬度", ConfigModel.validate_latitude, current_value_for_update=str(generated_coords['lat']))
                adj_lng = self._get_validated_input("经度", ConfigModel.validate_longitude, current_value_for_update=str(generated_coords['lng']))
                adj_acc = self._get_validated_input("精度", ConfigModel.validate_accuracy, current_value_for_update=str(generated_coords['accuracy']))
                config_data_dict.update({"lat": adj_lat, "lng": adj_lng, "acc": adj_acc, "selected_school": school_data})
                rand_choice_adj = input("调整坐标后，是否仍希望运行时随机化? (y/n, [默认: y]): ").lower().strip() or 'y'
                config_data_dict["enable_school_based_randomization"] = (rand_choice_adj == 'y')
                self.logger.log(f"用户调整并接受坐标。运行时随机化: {config_data_dict['enable_school_based_randomization']}", LogLevel.INFO); return True
            elif confirm == 'n': self.logger.log("用户拒绝自动生成的坐标。", LogLevel.INFO); return False
            else: print(f"{Fore.RED}无效输入，请输入 'y', 'n', 或 'a'。{Style.RESET_ALL}")
        return False

    def _select_school_interactive(self) -> Optional[SelectedSchoolData]:
        if not self.location_engine or not self.location_engine.all_schools: print(f"{Fore.YELLOW}学校数据未加载。{Style.RESET_ALL}"); return None
        while True:
            user_input = input(f"请输入学校ID或名称/关键词 (或 'm'手动, 'q'退出位置设置): ").strip()
            if user_input.lower() == 'q': self.logger.log("用户退出学校选择。", LogLevel.INFO); raise ConfigError("用户退出学校选择")
            if user_input.lower() == 'm': print("已选择手动输入坐标模式。"); return None 
            if not user_input: print(f"{Fore.YELLOW}输入不能为空。{Style.RESET_ALL}"); continue
            matches: List[SelectedSchoolData] = self.location_engine.search_schools(user_input) 
            if not matches: print(f"{Fore.YELLOW}未找到 '{user_input}' 匹配的学校。{Style.RESET_ALL}"); continue
            
            if len(matches) == 1 and (matches[0]['id'] == user_input.lower() or len(user_input) > 3) : 
                selected_school_obj = matches[0]
                print(f"找到唯一匹配: {Fore.GREEN}[ID: {selected_school_obj['id']}] {selected_school_obj['addr']}{Style.RESET_ALL}")
                if (input("选择此学校？ (y/n, [默认: y]): ").strip().lower() or 'y') == 'y': return selected_school_obj
                else: print("好的，重新搜索。"); continue
            else: 
                print(f"找到 {len(matches)} 个匹配项:"); max_display = 10
                for i, school_item_data in enumerate(matches[:max_display]): 
                    print(f"  {i + 1}. {Fore.CYAN}[ID: {school_item_data['id']}]{Style.RESET_ALL} {school_item_data['addr']}")
                if len(matches) > max_display: print(f"  ... (还有 {len(matches) - max_display} 个未显示)")
                while True:
                    choice_str = input(f"请输入序号(1-{min(len(matches),max_display)})或完整ID (或 's'重新搜索): ").strip()
                    if choice_str.lower() == 's': break
                    chosen_one_data: Optional[SelectedSchoolData] = self.location_engine.get_school_by_id(choice_str.lower()) 
                    if chosen_one_data and chosen_one_data in matches: 
                        print(f"您选择了: {Fore.GREEN}[ID: {chosen_one_data['id']}] {chosen_one_data['addr']}{Style.RESET_ALL}"); return chosen_one_data
                    else:
                        try:
                            choice_idx = int(choice_str) - 1
                            if 0 <= choice_idx < min(len(matches), max_display): 
                                chosen_one_data = matches[choice_idx]
                                print(f"您选择了: {Fore.GREEN}[ID: {chosen_one_data['id']}] {chosen_one_data['addr']}{Style.RESET_ALL}"); return chosen_one_data
                        except ValueError: pass 
                    print(f"{Fore.RED}无效输入。{Style.RESET_ALL}")
        return None

    def _get_validated_input(self, prompt: str, validator: Callable[[Any], Any], default_value: Optional[str] = None, current_value_for_update: Optional[str] = None) -> str:
        effective_default = current_value_for_update if current_value_for_update is not None else default_value
        prompt_suffix = ": "
        # Ensure effective_default is treated as a string for display and validation
        effective_default_str = str(effective_default) if effective_default is not None else ""

        if effective_default_str.strip() != "": 
            display_val = effective_default_str
            if "cookie" in prompt.lower() and len(display_val) > 30: display_val = f"{display_val[:15]}...{display_val[-15:]}"
            prompt_suffix = f" (当前/默认: {display_val}, 回车保持/使用): "
        elif default_value is not None and str(default_value).strip() != "": # Default_value is just a suggestion
            prompt_suffix = f" (建议: {default_value}, 或回车不填): " # Changed to "回车不填" if no current val
        
        while True:
            try:
                user_input = input(prompt + prompt_suffix).strip()
                if not user_input: # User pressed Enter
                    if effective_default_str.strip() != "": # Use effective_default if it's non-empty
                        return str(validator(effective_default_str)) 
                    else: # No effective default, or it's empty, let validator handle empty string
                        return str(validator("")) # Validator should raise error if empty is not allowed
                else: # User provided input
                    return str(validator(user_input))
            except ValueError as e: # Raised by validator for invalid input
                print(f"{Fore.RED}输入错误: {e}{Style.RESET_ALL}")
            except Exception as e_unknown: # Other unexpected errors during input or validation
                print(f"{Fore.RED}未知输入处理错误: {e_unknown}{Style.RESET_ALL}")
        return "" # Should not be reached

    def _setup_other_settings(self, config_data_dict: Dict[str, Any], is_update: bool = False) -> None:
        def get_current_or_default_setting(key: str, app_default_val: Any, sub_dict_path: Optional[List[str]] = None):
            target_dict = config_data_dict
            if sub_dict_path:
                for p_key in sub_dict_path:
                    target_dict = target_dict.get(p_key, {})
                    if not isinstance(target_dict, dict): return app_default_val
            if key in target_dict and target_dict[key] is not None : return target_dict[key]
            manager_config_val = None
            if is_update and self.manager.config: # Check if manager.config exists
                m_target_dict = self.manager.config
                if sub_dict_path:
                    for p_key in sub_dict_path:
                        m_target_dict = m_target_dict.get(p_key, {})
                        if not isinstance(m_target_dict, dict): break 
                    else: manager_config_val = m_target_dict.get(key)
                elif key in self.manager.config: manager_config_val = self.manager.config.get(key) # Use .get for safety
            return manager_config_val if manager_config_val is not None else app_default_val

        self.logger.log(f"\n{Fore.CYAN}=== {'更新' if is_update else '设置'}其他选项 ==={Style.RESET_ALL}", LogLevel.INFO)
        
        time_curr = str(get_current_or_default_setting("time", AppConstants.DEFAULT_SEARCH_INTERVAL))
        time_str = self._get_validated_input("检查间隔 (秒)", ConfigModel.validate_search_time, current_value_for_update=time_curr, default_value=str(AppConstants.DEFAULT_SEARCH_INTERVAL))
        config_data_dict["time"] = int(time_str)

        exit_after_sign_curr = get_current_or_default_setting("exit_after_sign", False)
        default_exit_char = 'n' # Default for new setup is False
        prompt_text_exit = f"成功签到后自动退出? (y/n"
        if is_update: prompt_text_exit += f" [当前: {'是' if exit_after_sign_curr else '否'}, 回车保持]"
        else: prompt_text_exit += f" [默认: 否, 回车选否]"
        prompt_text_exit += "): "
        exit_input = input(prompt_text_exit).strip().lower()

        if is_update and not exit_input: config_data_dict["exit_after_sign"] = exit_after_sign_curr
        elif not is_update and not exit_input: config_data_dict["exit_after_sign"] = (default_exit_char == 'y')
        else: config_data_dict["exit_after_sign"] = (exit_input == "y")

        if config_data_dict["exit_after_sign"]:
            configured_class_ids = config_data_dict.get("class_ids", []) 
            if isinstance(configured_class_ids, list) and len(configured_class_ids) > 1:
                current_exit_mode = get_current_or_default_setting("exit_after_sign_mode", AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE)
                mode_prompt_text = (f"签到后退出模式 ('any': 任一成功即退, 'all': 所有班级均成功才退)"
                                    f"{' [当前: '+current_exit_mode+', 回车保持]' if is_update else ' [默认: '+AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE+', 回车选默认]'}: ")
                mode_input = input(mode_prompt_text).strip().lower(); chosen_mode = ""
                if is_update and not mode_input: chosen_mode = current_exit_mode
                elif not is_update and not mode_input: chosen_mode = AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE
                else: chosen_mode = mode_input if mode_input in ["any", "all"] else AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE
                try: config_data_dict["exit_after_sign_mode"] = ConfigModel.validate_exit_mode(chosen_mode)
                except ValueError: 
                    self.logger.log(f"无效的退出模式 '{chosen_mode}', 用默认 '{AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE}'.", LogLevel.WARNING)
                    print(f"{Fore.YELLOW}无效退出模式，自动设为 '{AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE}'。{Style.RESET_ALL}")
                    config_data_dict["exit_after_sign_mode"] = AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE
            else: 
                config_data_dict["exit_after_sign_mode"] = get_current_or_default_setting("exit_after_sign_mode", AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE)
                if isinstance(configured_class_ids, list) and len(configured_class_ids) == 1:
                     self.logger.log("只有一个班级ID，退出模式行为相同。", LogLevel.INFO); print(f"{Fore.CYAN}提示: 单班级配置，退出模式行为相同。{Style.RESET_ALL}")
        else: 
            config_data_dict["exit_after_sign_mode"] = get_current_or_default_setting("exit_after_sign_mode", AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE)
        
        self.logger.log(f"\n{Fore.CYAN}--- PushPlus 通知设置 ---{Style.RESET_ALL}", LogLevel.INFO)
        current_pushplus_enabled = get_current_or_default_setting("enabled", False, sub_dict_path=["notifications", "pushplus"])
        current_pushplus_token = get_current_or_default_setting("token", "", sub_dict_path=["notifications", "pushplus"])
        enable_pushplus_prompt = f"是否启用 PushPlus 通知? (y/n"; 
        if is_update: enable_pushplus_prompt += f" [当前: {'是' if current_pushplus_enabled else '否'}, 回车保持]"
        else: enable_pushplus_prompt += f" [默认: 否, 回车选否]"
        enable_pushplus_prompt += "): "; enable_input = input(enable_pushplus_prompt).strip().lower()
        pushplus_enabled_final = current_pushplus_enabled if (is_update and not enable_input) else (enable_input == 'y')
        new_pushplus_token_val = current_pushplus_token
        if pushplus_enabled_final:
            new_pushplus_token_val = self._get_validated_input("请输入 PushPlus Token (留空表示不更改或使用空)", lambda v_token: v_token, current_value_for_update=current_pushplus_token, default_value="" )
            if not new_pushplus_token_val and not current_pushplus_token : 
                self.logger.log("PushPlus 已启用但 Token 未设置或被清空。", LogLevel.WARNING)
                print(f"{Fore.YELLOW}警告: PushPlus 已启用但 Token 为空，通知功能将无法使用。{Style.RESET_ALL}")
        
        notifications_node = config_data_dict.setdefault("notifications", {})
        if not isinstance(notifications_node, dict) : notifications_node = {}; config_data_dict["notifications"] = notifications_node
        pushplus_node = notifications_node.setdefault("pushplus", {})
        if not isinstance(pushplus_node, dict) : pushplus_node = {}; notifications_node["pushplus"] = pushplus_node
        pushplus_node["enabled"] = pushplus_enabled_final
        pushplus_node["token"] = new_pushplus_token_val
        self.logger.log(f"PushPlus 配置: enabled={pushplus_enabled_final}, token={'已设' if new_pushplus_token_val else '未设'}", LogLevel.DEBUG)
        
        remark_app_default = AppConstants.APP_NAME 
        remark_curr = get_current_or_default_setting("remark", remark_app_default)
        remark_input_val = self._get_validated_input("备注信息", lambda v_remark: v_remark, current_value_for_update=remark_curr, default_value=remark_app_default)
        config_data_dict["remark"] = remark_input_val.strip() if remark_input_val.strip() else remark_app_default
        
        self._setup_time_range_config(config_data_dict, is_update)

    def _setup_time_range_config(self, config_data_dict: Dict[str, Any], is_update: bool = False) -> None:
        def get_current_or_default_tr_setting(key: str, app_default_val: Any): 
            if key in config_data_dict and config_data_dict[key] is not None: return config_data_dict[key]
            if is_update and self.manager.config and key in self.manager.config and self.manager.config[key] is not None: 
                return self.manager.config[key]
            return app_default_val
        current_enabled_tr = get_current_or_default_tr_setting("enable_time_range", AppConstants.DEFAULT_RUN_TIME["enable_time_range"])
        default_enable_tr_char = 'y' if AppConstants.DEFAULT_RUN_TIME["enable_time_range"] else 'n'
        enable_prompt = f"是否启用按时间段运行控制? (y/n"
        enable_prompt += f" [当前: {'是' if current_enabled_tr else '否'}, 回车保持]" if is_update else f" [默认: {'是' if default_enable_tr_char == 'y' else '否'}, 回车选默认]"
        enable_prompt += "): "
        enable_input = input(enable_prompt).strip().lower()
        if is_update and not enable_input: config_data_dict["enable_time_range"] = current_enabled_tr
        elif not is_update and not enable_input: config_data_dict["enable_time_range"] = AppConstants.DEFAULT_RUN_TIME["enable_time_range"]
        else: config_data_dict["enable_time_range"] = (enable_input == 'y')
        start_default = AppConstants.DEFAULT_RUN_TIME['start_time']; end_default = AppConstants.DEFAULT_RUN_TIME['end_time']
        current_start = str(get_current_or_default_tr_setting("start_time", start_default)); current_end = str(get_current_or_default_tr_setting("end_time", end_default))
        if config_data_dict["enable_time_range"]:
            self.logger.log("请设置程序运行的时间段 (24小时制，格式 HH:MM)。", LogLevel.INFO)
            while True:
                try:
                    start_time_input = self._get_validated_input("开始时间 (HH:MM)", ConfigModel.validate_time_format, current_value_for_update=current_start, default_value=start_default)
                    end_time_input = self._get_validated_input("结束时间 (HH:MM)", ConfigModel.validate_time_format, current_value_for_update=current_end, default_value=end_default)
                    start_obj = datetime.strptime(start_time_input, "%H:%M").time(); end_obj = datetime.strptime(end_time_input, "%H:%M").time()
                    if start_obj == end_obj:
                        print(f"{Fore.YELLOW}警告: 开始 ({start_time_input}) 和结束 ({end_time_input}) 时间相同。{Style.RESET_ALL}")
                        if (input(f"仍要使用此设置吗？ (y/n, [默认: n]): ").strip().lower() or 'n') != 'y':
                            current_start, current_end = start_time_input, end_time_input ; continue
                    config_data_dict["start_time"], config_data_dict["end_time"] = start_time_input, end_time_input; break
                except ValueError as e_time: print(f"{Fore.RED}时间设置错误: {e_time}{Style.RESET_ALL}")
        else: 
            config_data_dict["start_time"] = current_start
            config_data_dict["end_time"] = current_end

    def _handle_pydantic_validation_error(self, error: Optional[ValidationError], custom_message: Optional[str] = None) -> None:
        if error:
            errors = [f"  - {'.'.join(map(str, err['loc'])) if err['loc'] else '配置项'}: {err['msg']}" for err in error.errors()]
            log_msg = "配置数据Pydantic验证失败:\n" + "\n".join(errors)
            print(f"{Fore.RED}配置错误，请修正以下问题:\n" + "\n".join(errors) + Style.RESET_ALL)
        elif custom_message: log_msg = f"配置错误: {custom_message}"; print(f"{Fore.RED}{log_msg}{Style.RESET_ALL}")
        else: log_msg = "发生未知配置验证错误。"; print(f"{Fore.RED}{log_msg}{Style.RESET_ALL}")
        self.logger.log(log_msg, LogLevel.ERROR)