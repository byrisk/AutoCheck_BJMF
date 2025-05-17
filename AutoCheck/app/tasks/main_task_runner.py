# autocheckf/app/tasks/main_task_runner.py
import sys
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, List, Set 
from copy import deepcopy

from colorama import Fore, Style # type: ignore

from app.logger_setup import LoggerInterface, LogLevel
from app.constants import AppConstants
from app.config.remote_manager import RemoteConfigManager
from app.services.sign_service import SignService, SignTaskDetails
from app.services.location_engine import LocationEngine, LocationError
from app.exceptions import ServiceAccessError

DataUploader = Any 


class MainTaskRunner:
    def __init__(self,
                 logger: LoggerInterface,
                 app_config: Dict[str, Any], 
                 application_run_event: threading.Event,
                 remote_config_manager: RemoteConfigManager,
                 sign_service: SignService,
                 location_engine: Optional[LocationEngine],
                 data_uploader_instance: Optional[DataUploader],
                 device_id: str
                 ):
        self.logger = logger
        self.base_config = app_config
        self.application_run_event = application_run_event
        self.remote_config_manager = remote_config_manager
        self.sign_service = sign_service
        self.location_engine = location_engine
        self.data_uploader_instance = data_uploader_instance
        self.device_id = device_id

        self.current_dynamic_coords: Dict[str, str] = {} 
        self.should_randomize: bool = False
        self._initialize_location_mode()

        self._user_requested_stop_flag = False
        self._last_wait_message_time: Optional[datetime] = None
        self.sign_cycle_count: int = 0
        self.sign_cycle_history: List[Dict[str, Any]] = [] 
        self.current_cycle_results: Optional[Dict[str, Any]] = None
        self.current_cycle_start: Optional[datetime] = None
        self.successfully_signed_class_ids_this_cycle: Set[str] = set()
        self.is_exit_pending_confirmation: bool = False
        self._runtime_exit_after_sign: Optional[bool] = None

        self.logger.log("MainTaskRunner 初始化完毕。", LogLevel.DEBUG)

    def get_runtime_exit_after_sign(self) -> bool:
        if self._runtime_exit_after_sign is None:
            return self.base_config.get("exit_after_sign", False)
        return self._runtime_exit_after_sign

    def set_runtime_exit_after_sign(self, new_mode: bool) -> None:
        self._runtime_exit_after_sign = new_mode
        self.logger.log(f"MainTaskRunner: 运行时签到后退出模式被 CommandHandler 设置为: {new_mode}", LogLevel.INFO)

    def _initialize_location_mode(self) -> None:
        self.should_randomize = (
            self.location_engine is not None and
            self.base_config.get("enable_school_based_randomization", False) and
            self.base_config.get("selected_school") is not None
        )
        if self.should_randomize:
            self.logger.log("MainTaskRunner: 运行时坐标模式: 基于选定学校进行动态随机化。", LogLevel.INFO)
            if not self._regenerate_dynamic_coordinates():
                self.logger.log("MainTaskRunner: 首次动态坐标生成失败，尝试使用配置中的固定坐标。", LogLevel.ERROR)
                self._use_fixed_coordinates()
        else:
            self.logger.log("MainTaskRunner: 运行时坐标模式: 使用配置文件中的固定坐标。", LogLevel.INFO)
            self._use_fixed_coordinates()
        
        if self.current_dynamic_coords:
            self.sign_service.set_current_coordinates(self.current_dynamic_coords)
        else:
            self.logger.log("MainTaskRunner: 无法初始化有效通用坐标，签到服务可能受影响。", LogLevel.ERROR)

    def _use_fixed_coordinates(self) -> None:
        lat = self.base_config.get("lat", "")
        lng = self.base_config.get("lng", "")
        acc = self.base_config.get("acc", str(AppConstants.DEFAULT_ACCURACY))
        if not lat or not lng :
            self.logger.log("MainTaskRunner: 配置中缺少有效的固定坐标 (lat, lng)。通用坐标设置失败。", LogLevel.ERROR)
            self.current_dynamic_coords = {} 
            return
        self.current_dynamic_coords = {"lat": str(lat), "lng": str(lng), "acc": str(acc)}
        self.logger.log(f"MainTaskRunner: 当前通用坐标已设置为固定值: {self.current_dynamic_coords}", LogLevel.DEBUG)

    def _regenerate_dynamic_coordinates(self) -> bool:
        if not self.should_randomize or not self.location_engine:
            if not self.current_dynamic_coords:
                 self.logger.log("MainTaskRunner: 不满足随机化条件且无当前坐标，尝试使用固定坐标。", LogLevel.DEBUG)
                 self._use_fixed_coordinates()
            return bool(self.current_dynamic_coords)

        selected_school = self.base_config.get("selected_school")
        if not selected_school:
            self.logger.log("MainTaskRunner: 已启用随机化但配置中缺少学校信息。无法生成动态坐标。", LogLevel.ERROR)
            self._use_fixed_coordinates()
            return False
        try:
            generated = self.location_engine.generate_location(selected_school) # type: ignore
            self.current_dynamic_coords = {"lat": generated["lat"], "lng": generated["lng"], "acc": generated["accuracy"]}
            self.logger.log(f"MainTaskRunner: 动态生成新通用周期坐标: {self.current_dynamic_coords} (来源: {generated['from_location_name']})", LogLevel.INFO)
            return True
        except (LocationError, Exception) as e:
            self.logger.log(f"MainTaskRunner: 动态生成通用坐标时出错: {e}，将回退到固定坐标。", LogLevel.ERROR, exc_info=True)
            self._use_fixed_coordinates()
            return False

    def _should_application_run(self) -> bool:
        if not self.application_run_event.is_set(): return False 
        if self._user_requested_stop_flag: return False
        try:
            if self.remote_config_manager.is_globally_disabled():
                disable_message = self.remote_config_manager.get_global_disable_message()
                self.logger.log(f"MainTaskRunner: 全局禁用已激活: '{disable_message}'.", LogLevel.CRITICAL)
                self._request_program_exit(f"全局禁用: {disable_message}", 1, is_error_exit=True)
                raise ServiceAccessError(f"全局禁用: {disable_message}") 
            
            if not self.remote_config_manager.is_device_allowed(self.device_id):
                message_template = self.remote_config_manager.get_device_block_message_template()
                block_message = message_template.format(device_id=self.device_id)
                self.logger.log(f"MainTaskRunner: 设备 {self.device_id} 被禁用: '{block_message}'.", LogLevel.CRITICAL)
                self._request_program_exit(f"设备被禁用: {block_message}", 1, is_error_exit=True)
                raise ServiceAccessError(f"设备被禁用: {block_message}")
        except ServiceAccessError as sae: 
            raise sae
        except Exception as e: 
            self.logger.log(f"MainTaskRunner: 检查远程访问控制时发生错误: {e}", LogLevel.ERROR, exc_info=True)
        return True

    def run_loop(self) -> None:
        self.logger.log("MainTaskRunner: 主任务循环已启动。", LogLevel.INFO)
        try:
            while self.application_run_event.is_set(): 
                if not self._should_application_run():
                    self.logger.log("MainTaskRunner: _should_application_run 返回 False 或应用停止事件已清除，退出主循环。", LogLevel.INFO)
                    break

                if self._is_within_time_range():
                    if not self.current_dynamic_coords: 
                        self.logger.log("MainTaskRunner: 无有效通用坐标，尝试在循环内重新初始化位置模式。", LogLevel.ERROR)
                        self._initialize_location_mode() 
                        if not self.current_dynamic_coords: 
                            self.logger.log("MainTaskRunner: 仍无有效通用坐标，跳过此签到周期。", LogLevel.ERROR)
                            self._wait_for_next_cycle()
                            continue
                    
                    self._execute_sign_cycle()
                    self._last_wait_message_time = None
                else: 
                    self._log_waiting_for_time_range()

                if not self.application_run_event.is_set(): 
                    self.logger.log("MainTaskRunner: 签到周期执行或等待后检测到退出信号。", LogLevel.INFO)
                    break
                
                self._wait_for_next_cycle()

        except ServiceAccessError as sae: 
            self.logger.log(f"MainTaskRunner: 因服务访问错误而停止: {sae}", LogLevel.CRITICAL)
            raise 
        except KeyboardInterrupt:
            self.logger.log("MainTaskRunner: 主循环检测到 KeyboardInterrupt，将停止。", LogLevel.INFO)
            self._request_program_exit("用户中断操作 (Ctrl+C)", 0)
        except Exception as e: 
            self.logger.log(f"MainTaskRunner: 主循环发生未捕获的致命错误: {e}", LogLevel.CRITICAL, exc_info=True)
            self._request_program_exit(f"主循环致命错误: {type(e).__name__}: {e}", 1, is_error_exit=True)
        finally:
            self.logger.log("MainTaskRunner: 主任务循环结束。", LogLevel.INFO)
            if self.application_run_event.is_set(): 
                 self.logger.log("MainTaskRunner: 主循环意外结束，确保应用停止事件已设置。", LogLevel.WARNING)
                 self.application_run_event.clear() 

    def _is_within_time_range(self) -> bool:
        if not self.base_config.get("enable_time_range", False):
            return True
        try:
            now_time = datetime.now().time()
            start_time_str = self.base_config.get("start_time", "00:00")
            end_time_str = self.base_config.get("end_time", "23:59")
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            end_time = datetime.strptime(end_time_str, "%H:%M").time()

            if start_time == end_time: 
                self.logger.log(f"MainTaskRunner: 时间范围开始和结束相同 ({start_time_str})，视为不在运行时间段内。", LogLevel.DEBUG)
                return False 

            if start_time <= end_time: 
                return start_time <= now_time <= end_time
            else: 
                return now_time >= start_time or now_time <= end_time
        except ValueError as e: 
            self.logger.log(f"MainTaskRunner: 时间范围配置格式错误 ('{self.base_config.get('start_time')}' or '{self.base_config.get('end_time')}'): {e}。默认允许运行。", LogLevel.WARNING)
            return True

    def _log_waiting_for_time_range(self) -> None:
        now = datetime.now()
        if self._last_wait_message_time is None or (now - self._last_wait_message_time).total_seconds() >= 600: 
            msg = (f"⏳ 当前时间 {now.strftime('%H:%M:%S')} 不在运行时间段 "
                   f"({self.base_config.get('start_time', 'N/A')}-{self.base_config.get('end_time', 'N/A')}) 内，等待中...")
            self.logger.log(msg, LogLevel.INFO) 
            if sys.stdout.isatty():
                 print(f"{Fore.YELLOW}{msg}{Style.RESET_ALL}")
            self._last_wait_message_time = now

    def _print_class_processing_summary(self, class_id: str, cycle_num: int, results: Dict[str, Any], class_details: Optional[Dict[str,str]] = None):
        found_count = len(results.get('sign_ids_found', []))
        processed_count = len(results.get('sign_ids_processed', []))
        skipped_count = len(results.get('sign_ids_skipped', []))
        error_msg = results.get('error')

        display_name = class_id
        if class_details and class_details.get('name'):
            display_name = class_details['name']
            if class_details.get('code'):
                display_name += f" (ID: {class_id}, 码: {class_details['code']})"
            else:
                 display_name += f" (ID: {class_id})"
        
        print(f"{Style.BRIGHT}{Fore.BLUE}├─📊 班级处理小结 [{display_name} | 全局周期: #{cycle_num}] {Style.RESET_ALL}")
        print(f"{Fore.BLUE}│  发现任务: {Style.BRIGHT}{Fore.CYAN}{found_count}{Style.RESET_ALL}{Fore.BLUE} 个")
        print(f"{Fore.BLUE}│  成功处理/已签: {Style.BRIGHT}{Fore.GREEN}{processed_count}{Style.RESET_ALL}{Fore.BLUE} 个")
        print(f"{Fore.BLUE}│  跳过/无效/失败: {Style.BRIGHT}{Fore.YELLOW if skipped_count > 0 else Fore.CYAN}{skipped_count}{Style.RESET_ALL}{Fore.BLUE} 个")
        if error_msg:
            console_error_msg = (error_msg[:100] + '...') if len(error_msg) > 100 else error_msg
            print(f"{Fore.RED}│  错误: {console_error_msg}{Style.RESET_ALL}")
        print(f"{Style.BRIGHT}{Fore.BLUE}└──────────────────────────────────────────────────────────────────{Style.RESET_ALL}")

    def _execute_sign_cycle(self) -> None:
        if self.should_randomize:
            if not self._regenerate_dynamic_coordinates(): 
                self.logger.log("MainTaskRunner: 签到周期开始时动态通用坐标生成失败。", LogLevel.WARNING)
                if not self.current_dynamic_coords:
                    self.logger.log("MainTaskRunner: 无法获取任何有效通用坐标（随机化失败且无回退），跳过此周期。", LogLevel.ERROR)
                    return
        elif not self.current_dynamic_coords:
             self.logger.log("MainTaskRunner: 固定通用坐标无效或未设置，尝试重新初始化。", LogLevel.ERROR)
             self._initialize_location_mode()
             if not self.current_dynamic_coords:
                 self.logger.log("MainTaskRunner: 仍无有效固定坐标，跳过此签到周期。", LogLevel.ERROR)
                 return

        if self.current_dynamic_coords:
            self.sign_service.set_current_coordinates(self.current_dynamic_coords)
        else:
            self.logger.log("MainTaskRunner: _execute_sign_cycle - 严重错误：current_dynamic_coords 在最终检查时仍未设置。", LogLevel.CRITICAL)
            return 


        self.sign_cycle_count += 1
        overall_cycle_num = self.sign_cycle_count
        self.current_cycle_start = datetime.now()
        self.successfully_signed_class_ids_this_cycle.clear()

        user_info = self.base_config.get("user_info", {})
        uname = user_info.get("uname", "N/A")
        uid = user_info.get("uid", "N/A")
        remark = self.base_config.get("remark", "N/A")
        num_classes_monitored = len(self.base_config.get("class_ids", []))
        coord_mode = '动态随机 (基于学校)' if self.should_randomize and self.base_config.get("selected_school") else '固定配置'
        
        start_header_text = f"签到周期 #{overall_cycle_num} ({self.current_cycle_start.strftime('%Y-%m-%d %H:%M:%S')}) 开始"
        self.logger.log(start_header_text, LogLevel.INFO) 

        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}{'=' * 80}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}🚀 {start_header_text.center(76)} 🚀{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Style.DIM}用户:{Style.NORMAL} {Style.BRIGHT}{uname}{Style.NORMAL} (UID: {uid}) {Style.DIM}备注:{Style.NORMAL} {Style.BRIGHT}{remark}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}│ {Style.DIM}监控班级数:{Style.NORMAL} {Style.BRIGHT}{num_classes_monitored}{Style.NORMAL}  {Style.DIM}坐标模式:{Style.NORMAL} {Style.BRIGHT}{coord_mode}{Style.RESET_ALL}")
        if self.current_dynamic_coords:
            coord_str = f"Lat: {self.current_dynamic_coords.get('lat', 'N/A')}, Lng: {self.current_dynamic_coords.get('lng', 'N/A')}, Acc: {self.current_dynamic_coords.get('acc', 'N/A')}"
            print(f"{Fore.CYAN}│ {Style.DIM}当前坐标基准:{Style.NORMAL} {Style.BRIGHT}{coord_str}{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}│ {Style.DIM}当前坐标基准:{Style.NORMAL} {Fore.RED}{Style.BRIGHT}未设置或无效{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}{'-' * 80}{Style.RESET_ALL}")
        
        if self.current_dynamic_coords :
             self.logger.log(f"本周期通用坐标基准: {self.current_dynamic_coords}", LogLevel.DEBUG)

        configured_class_ids = self.base_config.get("class_ids", [])
        all_fetched_class_details_list = self.base_config.get("all_fetched_class_details", []) or []
        details_map = {str(d.get("id")): d for d in all_fetched_class_details_list if isinstance(d, dict) and d.get("id")}

        if not configured_class_ids:
            self.logger.log("MainTaskRunner: 配置中未找到班级ID，跳过签到。", LogLevel.WARNING)
            self.current_cycle_results = {
                "cycle_num": overall_cycle_num, 
                "start_time": self.current_cycle_start.strftime("%Y-%m-%d %H:%M:%S"),
                "class_id_processed_in_sub_cycle": "N/A", "sign_ids_found": [],
                "sign_ids_processed": [], "sign_ids_skipped": [], "error": "No Class IDs configured"
            }
            self._record_cycle_result()
            print(f"{Fore.YELLOW}⚠️  配置中未找到班级ID，无法执行签到。{Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}{Style.BRIGHT}{'=' * 80}{Style.RESET_ALL}")
            return

        any_success_in_this_overall_cycle = False
        total_tasks_found_in_cycle = 0 
        successful_tasks_processed_in_cycle = 0

        for class_id_to_process in configured_class_ids:
            if not self.application_run_event.is_set(): break 
            
            class_detail_for_display = details_map.get(str(class_id_to_process))
            class_display_name = class_id_to_process 
            if class_detail_for_display and class_detail_for_display.get('name'):
                class_display_name = class_detail_for_display['name']
            
            self.logger.log(f"--- 开始处理班级: {class_display_name} (ID: {class_id_to_process}, 全局周期 #{overall_cycle_num}) ---", LogLevel.INFO)
            print(f"\n{Fore.BLUE}🔹 处理班级: {Style.BRIGHT}{class_display_name}{Style.NORMAL} (ID: {class_id_to_process}) ...{Style.RESET_ALL}")

            class_cycle_had_success = False 
            self.current_cycle_results = {
                "cycle_num": overall_cycle_num, 
                "class_id_processed_in_sub_cycle": class_id_to_process,
                "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "sign_ids_found": [], "sign_ids_processed": [], "sign_ids_skipped": [], "error": None
            }
            try:
                sign_tasks_details: Optional[List[SignTaskDetails]] = self.sign_service.fetch_sign_task_details(class_id_to_process)

                if sign_tasks_details is None:
                    raise LocationError(f"获取班级 {class_display_name} 详细签到任务列表失败 (null returned)。")
                
                current_class_tasks_found = [task['id'] for task in sign_tasks_details]
                self.current_cycle_results["sign_ids_found"] = current_class_tasks_found
                total_tasks_found_in_cycle += len(current_class_tasks_found)


                if not sign_tasks_details:
                    self.logger.log(f"班级 {class_display_name}: 🔍 未发现新的签到任务。", LogLevel.INFO)
                    print(f"{Fore.BLUE}│  🔍 {Style.NORMAL}班级 {class_display_name}: 未发现新的签到任务。{Style.RESET_ALL}")
                else:
                    self.logger.log(f"班级 {class_display_name}: 🔍 发现 {len(sign_tasks_details)} 个签到任务。", LogLevel.INFO)
                    print(f"{Fore.BLUE}│  🔍 {Style.NORMAL}班级 {class_display_name}: 发现 {len(sign_tasks_details)} 个签到任务:{Style.RESET_ALL}")
                    for idx, task_item in enumerate(sign_tasks_details):
                        type_color = Fore.CYAN 
                        parsed_type_str = str(task_item.get('type', 'unknown')).replace('_', ' ').title() # e.g. "Photo Gps"
                        card_title_str = str(task_item.get('title', 'N/A')) # Original title from card

                        if task_item['type'] == 'qr': type_color = Fore.YELLOW
                        elif task_item['type'] == 'photo_gps': type_color = Fore.MAGENTA
                        elif task_item['type'] == 'password': type_color = Fore.RED
                        
                        status_color = Fore.GREEN if task_item['status'] == '已签' else Fore.RED if task_item['status'] == '未签' else Fore.WHITE
                        
                        # Optimized display for type
                        type_display = f"{type_color}{Style.BRIGHT}{parsed_type_str}{Style.NORMAL}"
                        if card_title_str.lower() != parsed_type_str.lower() and card_title_str != "未知类型签到":
                             type_display += f"{Style.RESET_ALL}{Fore.BLUE} (卡片标题: {Style.BRIGHT}{card_title_str}{Style.NORMAL})"


                        print(f"{Fore.BLUE}│    {idx+1}. ID: {Style.BRIGHT}{task_item['id']}{Style.NORMAL}, "
                              f"类型: {type_display}{Style.RESET_ALL}{Fore.BLUE}, "
                              f"状态: {status_color}{Style.BRIGHT}{task_item['status']}{Style.NORMAL}{Style.RESET_ALL}{Fore.BLUE}, "
                              f"结束: {Style.BRIGHT}{task_item.get('end_time_text', 'N/A')}{Style.RESET_ALL}")
                        if task_item.get('photo_hint'):
                            print(f"{Fore.BLUE}│       拍照提示: {Fore.LIGHTBLACK_EX}{task_item['photo_hint']}{Style.RESET_ALL}")
                        if task_item.get('is_gps_limited_range'):
                            gps_ranges_str = str(task_item.get('gps_ranges'))
                            display_gps_ranges = (gps_ranges_str[:70] + '...') if len(gps_ranges_str) > 70 else gps_ranges_str
                            print(f"{Fore.BLUE}│       GPS范围: {Fore.LIGHTBLACK_EX}{Style.BRIGHT}受限{Style.NORMAL} (详情: {display_gps_ranges}){Style.RESET_ALL}")
                        elif task_item.get('is_gps_limited_range') is False:
                             print(f"{Fore.BLUE}│       GPS范围: {Fore.LIGHTBLACK_EX}{Style.BRIGHT}无限制{Style.RESET_ALL}")
                
                for task in sign_tasks_details:
                    sign_id_task = task['id']
                    if not self.application_run_event.is_set(): break

                    coords_for_this_attempt = self.current_dynamic_coords 
                    
                    if task['type'] in ['gps', 'photo_gps'] and task.get('is_gps_limited_range') and task.get('gps_ranges'):
                        try:
                            gps_info_list = task['gps_ranges'] 
                            if gps_info_list and isinstance(gps_info_list[0], list) and len(gps_info_list[0]) == 3:
                                target_gps_params = gps_info_list[0] 
                                base_lat_str, base_lng_str, radius_m_any = str(target_gps_params[0]), str(target_gps_params[1]), target_gps_params[2]
                                
                                base_lat_f = float(base_lat_str)
                                base_lng_f = float(base_lng_str)
                                radius_m_f = float(str(radius_m_any))

                                effective_max_offset = min(radius_m_f * 0.3, AppConstants.MAX_RANDOM_OFFSET_METERS, 30.0) 
                                effective_max_offset = max(effective_max_offset, 1.0)

                                if self.location_engine: 
                                    offset_lat, offset_lng = self.location_engine._add_random_offset(base_lat_f, base_lng_f, effective_max_offset) # type: ignore
                                    coords_for_this_attempt = {
                                        "lat": f"{offset_lat:.6f}", "lng": f"{offset_lng:.6f}",
                                        "acc": str(AppConstants.DEFAULT_ACCURACY) 
                                    }
                                    self.logger.log(f"任务ID {sign_id_task}: 使用任务提供GPS基点 ({base_lat_f:.5f}, {base_lng_f:.5f}, R={radius_m_f}m, OffsetMax={effective_max_offset:.1f}m) 生成签到坐标: {coords_for_this_attempt}", LogLevel.INFO)
                                else: 
                                    self.logger.log(f"任务ID {sign_id_task}: LocationEngine不可用，将使用原始任务GPS基点 (无偏移)。", LogLevel.WARNING)
                                    coords_for_this_attempt = {"lat": f"{base_lat_f:.6f}", "lng": f"{base_lng_f:.6f}", "acc": str(AppConstants.DEFAULT_ACCURACY)}
                            else:
                                self.logger.log(f"任务ID {sign_id_task}: GPS范围数据格式不正确: {task.get('gps_ranges')}。将使用周期默认坐标。", LogLevel.WARNING)
                        except (ValueError, TypeError, IndexError) as e_parse_gps:
                            self.logger.log(f"任务ID {sign_id_task}: 解析任务提供的GPS范围数据时出错: {e_parse_gps}。将使用周期默认坐标。", LogLevel.WARNING)
                    
                    if not coords_for_this_attempt: 
                        self.logger.log(f"任务ID {sign_id_task}: 无法确定签到坐标！之前已设置周期通用坐标: {self.current_dynamic_coords}", LogLevel.ERROR)
                        coords_for_this_attempt = self.current_dynamic_coords
                        if not coords_for_this_attempt: 
                            self.logger.log(f"任务ID {sign_id_task}: 通用周期坐标也无效，无法签到！", LogLevel.CRITICAL)
                            if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]: self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
                            self.current_cycle_results["error"] = (self.current_cycle_results.get("error") or "") + f"; Task {sign_id_task} skipped, no valid coordinates"
                            continue 
                    
                    self.sign_service.set_current_coordinates(coords_for_this_attempt)

                    if task['status'] == '已签':
                        if sign_id_task not in self.sign_service.signed_ids: self.sign_service.signed_ids.add(sign_id_task) 
                        if sign_id_task not in self.current_cycle_results["sign_ids_processed"]: self.current_cycle_results["sign_ids_processed"].append(sign_id_task)
                        any_success_in_this_overall_cycle = True; class_cycle_had_success = True
                        successful_tasks_processed_in_cycle +=1 
                        self.sign_service._print_formatted_sign_status("👍", Fore.CYAN, class_id_to_process, sign_id_task, f"状态确认：已签到过 ({task.get('title','N/A')})") # Use task.get('title')
                        continue

                    if sign_id_task in self.sign_service.invalid_sign_ids:
                        if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]: self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
                        self.sign_service._print_formatted_sign_status("🚫", Fore.MAGENTA, class_id_to_process, sign_id_task, "跳过：任务先前已标记为无效")
                        continue
                    
                    if task['type'] == 'password' and task.get('requires_password'):
                        self.logger.log(f"班级 {class_display_name}: ⏭️ 跳过密码签到任务ID: {sign_id_task}", LogLevel.WARNING)
                        self.sign_service._print_formatted_sign_status("🔑", Fore.RED, class_id_to_process, sign_id_task, "跳过：密码签到", "脚本不支持自动输入密码。")
                        self.sign_service.invalid_sign_ids.add(sign_id_task) 
                        if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]: self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
                        continue
                    
                    if task['type'] == 'roll_call' and not task.get('raw_onclick'): 
                        self.logger.log(f"班级 {class_display_name}: ℹ️ 识别为教师手动点名任务ID: {sign_id_task}，脚本无法操作。", LogLevel.INFO)
                        self.sign_service._print_formatted_sign_status("📝", Fore.CYAN, class_id_to_process, sign_id_task, "教师点名", "此类型签到需教师操作。")
                        if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]: self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
                        continue
                    
                    self.logger.log(f"班级 {class_display_name}: 尝试处理签到任务ID: {sign_id_task} (类型: {task['type']}, 标题: {task.get('title','N/A')}) 使用坐标: {coords_for_this_attempt}", LogLevel.DEBUG)
                    is_definitively_handled_by_attempt = self.sign_service.attempt_sign(sign_id_task, class_id_to_process)
                    
                    if sign_id_task in self.sign_service.signed_ids: 
                        if sign_id_task not in self.current_cycle_results["sign_ids_processed"]:
                             self.current_cycle_results["sign_ids_processed"].append(sign_id_task)
                        any_success_in_this_overall_cycle = True; class_cycle_had_success = True
                        successful_tasks_processed_in_cycle +=1 
                    elif sign_id_task in self.sign_service.invalid_sign_ids: 
                        if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]:
                             self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
                    elif not is_definitively_handled_by_attempt: 
                        if sign_id_task not in self.current_cycle_results["sign_ids_skipped"]:
                             self.current_cycle_results["sign_ids_skipped"].append(sign_id_task)
            
            except (LocationError, Exception) as e_class_proc:
                error_msg_class = f"班级 {class_display_name} 处理时发生错误: {type(e_class_proc).__name__}: {str(e_class_proc)}"
                self.logger.log(f"❌ {error_msg_class}", LogLevel.ERROR, exc_info=True)
                print(f"{Fore.RED}│  ❌ 班级 {class_display_name} 处理错误: {str(e_class_proc)[:100]}{Style.RESET_ALL}")
                if self.current_cycle_results: self.current_cycle_results["error"] = error_msg_class
            finally:
                if self.current_cycle_results: 
                    self._record_cycle_result()
                    self._print_class_processing_summary(class_id_to_process, overall_cycle_num, self.current_cycle_results, class_detail_for_display)
                
                summary_lines_for_log = [f"--- 班级ID: {class_id_to_process} 处理完毕 (全局周期 #{overall_cycle_num}) 日志小结 ---",
                           f"  子周期开始(日志): {self.current_cycle_results.get('start_time', 'N/A') if self.current_cycle_results else 'N/A'}",
                           f"  发现任务(日志): {len(self.current_cycle_results.get('sign_ids_found',[])) if self.current_cycle_results else 'N/A'} 个",
                           f"  成功签到/已签(日志): {len(self.current_cycle_results.get('sign_ids_processed',[])) if self.current_cycle_results else 'N/A'} 个",
                           f"  跳过/无效/失败(日志): {len(self.current_cycle_results.get('sign_ids_skipped',[])) if self.current_cycle_results else 'N/A'} 个"]
                if self.current_cycle_results and self.current_cycle_results.get("error"): 
                    summary_lines_for_log.append(f"  - ❌ 错误(日志): {self.current_cycle_results['error']}")
                self.logger.log("\n".join(summary_lines_for_log), LogLevel.DEBUG) 
            
            if class_cycle_had_success:
                self.successfully_signed_class_ids_this_cycle.add(class_id_to_process)
        
        overall_duration = (datetime.now() - (self.current_cycle_start or datetime.now())).total_seconds()
        
        end_header_text = f"签到周期 #{overall_cycle_num} 全部处理完毕 (耗时: {overall_duration:.2f}s)"
        self.logger.log(end_header_text, LogLevel.INFO)

        print(f"{Fore.MAGENTA}{Style.BRIGHT}{'-' * 80}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}🏁 {end_header_text.center(76)} 🏁{Style.RESET_ALL}")
        
        if total_tasks_found_in_cycle > 0:
            success_rate = (successful_tasks_processed_in_cycle / total_tasks_found_in_cycle) * 100
            print(f"{Fore.CYAN}│ {Style.DIM}本周期小结:{Style.NORMAL} 共发现 {Style.BRIGHT}{total_tasks_found_in_cycle}{Style.NORMAL} 个任务，成功处理/确认 {Style.BRIGHT}{Fore.GREEN}{successful_tasks_processed_in_cycle}{Style.NORMAL}{Fore.CYAN} 个 (成功率: {success_rate:.1f}%)。{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}│ {Style.DIM}本周期小结:{Style.NORMAL} 未发现可处理的签到任务。{Style.RESET_ALL}")
        
        total_signed_ever = self.sign_service.get_total_successful_sign_ins()
        print(f"{Fore.CYAN}│ {Style.DIM}累计成功签到 (自启动或记录):{Style.NORMAL} {Style.BRIGHT}{Fore.GREEN}{total_signed_ever}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}{'=' * 80}{Style.RESET_ALL}\n")
        
        exit_after_sign_runtime = self.get_runtime_exit_after_sign()
        if exit_after_sign_runtime:
            exit_mode_cfg = self.base_config.get("exit_after_sign_mode", AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE)
            ready_to_exit_prog = False; exit_reason = ""
            
            if exit_mode_cfg == "any" and any_success_in_this_overall_cycle:
                ready_to_exit_prog = True; exit_reason = "检测到任一班级成功签到"
            elif exit_mode_cfg == "all":
                if not configured_class_ids: 
                    ready_to_exit_prog = True; exit_reason = "未配置班级，符合“所有班级”退出条件"
                elif set(configured_class_ids).issubset(self.successfully_signed_class_ids_this_cycle):
                    ready_to_exit_prog = True; exit_reason = "检测到所有配置班级均成功签到"
            
            if ready_to_exit_prog:
                self.logger.log(f"MainTaskRunner: {exit_reason} 且配置了签到后退出。将请求程序终止。", LogLevel.INFO)
                self.is_exit_pending_confirmation = True 
                self._request_program_exit(f"{exit_reason} (模式: {exit_mode_cfg})，符合退出条件。", 0)

    def trigger_immediate_sign_cycle(self) -> bool:
        if not self._should_application_run():
            self.logger.log("MainTaskRunner: 无法触发立即签到，应用未在运行状态或访问受限。", LogLevel.WARNING)
            print(f"{Fore.RED}应用当前未运行或访问受限，无法立即签到。{Style.RESET_ALL}")
            return False
        if not self._is_within_time_range():
            self.logger.log("MainTaskRunner: 无法触发立即签到，不在运行时间段内。", LogLevel.WARNING)
            print(f"{Fore.YELLOW}当前不在设定的运行时间段内，无法执行立即签到。{Style.RESET_ALL}")
            return False

        self.logger.log("MainTaskRunner: 收到立即执行签到周期的请求...", LogLevel.INFO)
        print(f"\n{Fore.CYAN}正在尝试立即执行签到周期...{Style.RESET_ALL}")
        
        if not self.should_randomize and not self.current_dynamic_coords:
            self.logger.log("MainTaskRunner (立即签到): 固定坐标无效，尝试重新初始化。", LogLevel.ERROR)
            self._initialize_location_mode()
            if not self.current_dynamic_coords:
                print(f"{Fore.RED}错误：签到坐标无效或无法生成。{Style.RESET_ALL}")
                return False
        
        self._execute_sign_cycle() 
        self._last_wait_message_time = None 
        return True

    def _request_program_exit(self, reason: str, exit_code: int = 0, is_error_exit: bool = False):
        log_level = LogLevel.ERROR if is_error_exit and exit_code != 0 else LogLevel.INFO
        self.logger.log(f"MainTaskRunner: 请求程序退出 - 原因: {reason} (建议退出码: {exit_code})", log_level)
        self._user_requested_stop_flag = True 
        if self.application_run_event.is_set(): 
            self.application_run_event.clear()

    def _wait_for_next_cycle(self) -> None:
        interval = self.base_config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL)
        if self._is_within_time_range() and self.application_run_event.is_set() and not self._user_requested_stop_flag: 
            now = datetime.now()
            if self._last_wait_message_time is None or (now - self._last_wait_message_time).total_seconds() >= 60: 
                user_info = self.base_config.get("user_info", {})
                uname = user_info.get("uname", "N/A")
                remark = self.base_config.get("remark", "N/A")
                wait_msg = f"⏳ ({Style.BRIGHT}{uname}{Style.NORMAL} @ {Style.BRIGHT}{remark}{Style.NORMAL}) 等待下次检索 ({Style.BRIGHT}{interval}s{Style.NORMAL})..."
                self.logger.log(wait_msg.replace(Style.BRIGHT, "").replace(Style.NORMAL, ""), LogLevel.INFO)
                if sys.stdout.isatty():
                    sys.stdout.write("\r\033[K") 
                    print(f"{Fore.CYAN}{wait_msg}{Style.RESET_ALL}")
                self._last_wait_message_time = now
        
        for i in range(interval): 
            if not self.application_run_event.is_set() or self._user_requested_stop_flag : break
            time.sleep(1)

    def _record_cycle_result(self) -> None:
        if self.current_cycle_results:
            self.current_cycle_results.setdefault('sign_ids_found', [])
            self.current_cycle_results.setdefault('sign_ids_processed', [])
            self.current_cycle_results.setdefault('sign_ids_skipped', [])
            self.current_cycle_results.setdefault('error', None)
            
            self.sign_cycle_history.append(deepcopy(self.current_cycle_results))
            if len(self.sign_cycle_history) > 50: 
                self.sign_cycle_history.pop(0)

    def _get_current_runtime_data(self) -> Dict[str, Any]:
        return {
            "total_successful_sign_ins": self.sign_service.get_total_successful_sign_ins(),
            "current_coordinates": deepcopy(self.current_dynamic_coords) if self.current_dynamic_coords else {}
        }

    def _upload_data_job(self) -> None:
        if not self.application_run_event.is_set(): 
            self.logger.log("MainTaskRunner: 应用程序关闭，跳过数据上传作业。", LogLevel.DEBUG)
            return

        if self.data_uploader_instance:
            try:
                runtime_data_for_upload = self._get_current_runtime_data()
                if hasattr(self.data_uploader_instance, 'update_config_reference'):
                     self.data_uploader_instance.update_config_reference(self.base_config) # type: ignore
                
                if hasattr(self.data_uploader_instance, 'upload_data') and callable(self.data_uploader_instance.upload_data): 
                    self.data_uploader_instance.upload_data(runtime_data=runtime_data_for_upload) # type: ignore
                    self.logger.log("MainTaskRunner: 数据上传作业执行完毕。", LogLevel.DEBUG)
                else:
                    self.logger.log("MainTaskRunner: data_uploader_instance 没有 upload_data 方法。", LogLevel.ERROR)
            except Exception as e:
                self.logger.log(f"MainTaskRunner: 数据上传作业执行时发生错误: {type(e).__name__}: {e}", LogLevel.ERROR, exc_info=True)
        else:
            self.logger.log("MainTaskRunner: DataUploader 实例未配置，无法上传数据。", LogLevel.WARNING)