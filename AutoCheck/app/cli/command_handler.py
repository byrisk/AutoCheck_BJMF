# app/cli/command_handler.py
import sys
import threading
import time
import os # _timed_input_for_exit (原始版本) 和 FileHistory (如果手动实现) 可能需要
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Callable 

from colorama import Fore, Style # type: ignore

from app.logger_setup import LoggerInterface, LogLevel
from app.constants import AppConstants # _timed_input_for_exit 会用到超时常量
from app.utils.app_utils import launch_updater_and_exit, get_app_dir # 之前 CommandHandler 也用 get_app_dir

# 类型占位符
AppOrchestrator = Any 
SignService = Any
MainTaskRunner = Any


class CommandHandler:
    def __init__(self,
                 logger: LoggerInterface,
                 application_run_event: threading.Event, 
                 app_orchestrator_ref: AppOrchestrator,
                 sign_service_ref: SignService,
                 main_task_runner_ref: MainTaskRunner
                 ):
        self.logger = logger
        self.application_run_event = application_run_event
        self.app_orchestrator = app_orchestrator_ref
        self.sign_service = sign_service_ref
        self.main_task_runner = main_task_runner_ref

        self._user_requested_stop_monitor = False 
        self._control_thread: Optional[threading.Thread] = None
        self.command_history_list: List[Tuple[datetime, str]] = [] # 用于我们自己的历史记录功能

        self.command_handlers: Dict[str, Callable[[], bool]] = {}
        self.command_descriptions: Dict[str, str] = {}
        self._setup_command_system()

    def _setup_command_system(self):
        self.command_handlers = {
            'q': self._handle_quit_command,
            's': self._handle_sign_now_command,
            'c': self._handle_status_command,
            'exit-mode': self._handle_exit_mode_command,
            'conf': self._handle_config_command,
            'h': self._handle_help_command,
            'history': self._handle_history_command,
            'stats': self._handle_stats_command,
            'update': self._handle_update_command
        }
        self.command_descriptions = {
            'q': "退出程序",
            's': "立即执行签到检查",
            'c': "查看当前状态",
            'exit-mode': "切换签到后退出模式 (仅当前会话)",
            'conf': "修改配置(通常需要重启应用以应用)",
            'h': "显示帮助信息",
            'history': "显示命令历史记录 (最近内部记录的10条)",
            'stats': "显示签到统计信息",
            'update': "检查并执行应用程序更新"
        }
        self.logger.log("CommandHandler: 命令系统已设置。", LogLevel.DEBUG)

    def start_command_monitoring(self):
        if not self._control_thread or not self._control_thread.is_alive():
            self._user_requested_stop_monitor = False
            self._control_thread = threading.Thread(target=self._monitor_commands_loop, daemon=True)
            self._control_thread.start()
            self.logger.log("CommandHandler: 命令监控线程已启动。", LogLevel.INFO)

    def stop_command_monitoring(self):
        self._user_requested_stop_monitor = True
        if self._control_thread and self._control_thread.is_alive():
            self.logger.log("CommandHandler: 正在等待命令监控线程结束...", LogLevel.DEBUG)
            # 对于阻塞的 input() 或 readline()，需要通过其他方式（如关闭stdin或发送信号）来使其解除阻塞
            # 但由于线程是daemon，通常会随主程序结束。join只是尝试等待一下。
            self._control_thread.join(timeout=1.5) 
        if self._control_thread and self._control_thread.is_alive(): # pragma: no cover
            self.logger.log("CommandHandler: 命令监控线程未能干净地结束。", LogLevel.WARNING)
        else:
            self.logger.log("CommandHandler: 命令监控线程已停止。", LogLevel.DEBUG)
        self._control_thread = None

    def _monitor_commands_loop(self):
        """使用 Python 内置 input() 监控用户命令"""
        self.logger.log("CommandHandler: 命令监控已启动。输入 'h' 获取帮助。", LogLevel.INFO)
        if sys.stdin.isatty():
             print(f"{Fore.CYAN}命令处理器已就绪。输入 'h' 获取可用命令列表。{Style.RESET_ALL}")

        while self.application_run_event.is_set() and not self._user_requested_stop_monitor:
            try:
                prompt_message = f"{Fore.BLUE}(输入命令):{Style.RESET_ALL} "
                
                # 在 input() 之前，尝试清理当前行，这对于多线程日志输出环境是个挑战
                # 如果 FileLogger 的控制台输出是INFO及以上，DEBUG日志不会干扰
                # 如果有其他线程恰好在 sys.stdout.write 和 input() 之间打印，提示符可能还是会被推开
                if sys.stdout.isatty():
                    sys.stdout.write("\r\033[K") # 清除当前行
                    sys.stdout.flush()          # 确保清行生效

                cmd_input = input(prompt_message).strip().lower()

                if not self.application_run_event.is_set() or self._user_requested_stop_monitor:
                    self.logger.log("CommandHandler: 收到退出信号，停止命令监控。", LogLevel.DEBUG)
                    break

                if cmd_input:
                    if cmd_input in self.command_handlers:
                        self.command_history_list.append((datetime.now(), cmd_input))
                        if len(self.command_history_list) > 50: self.command_history_list.pop(0)
                        
                        handler = self.command_handlers[cmd_input]
                        success = False
                        try:
                            success = handler()
                        except Exception as handler_e: # pragma: no cover
                            self.logger.log(f"CommandHandler: 命令 '{cmd_input}' 执行出错: {handler_e}", LogLevel.ERROR, exc_info=True)
                            print(f"{Fore.RED}命令 '{cmd_input}' 执行失败: {handler_e}{Style.RESET_ALL}")
                        
                        if cmd_input != 'q' or not success : 
                           if success : 
                               print(f"{Fore.GREEN}✓ 命令 '{self.command_descriptions.get(cmd_input, cmd_input)}' 执行完毕。{Style.RESET_ALL}")
                    else: 
                        suggestions = [c for c in self.command_handlers if c.startswith(cmd_input[:1])]
                        msg = f"{Fore.YELLOW}未知命令 '{cmd_input}'"
                        if suggestions:
                            msg += f", 您是否想输入: {', '.join(suggestions)}?"
                        print(msg + Style.RESET_ALL)
            
            except KeyboardInterrupt: # pragma: no cover
                self.logger.log("CommandHandler: 命令监控线程检测到中断信号 (Ctrl+C)。", LogLevel.INFO)
                self._user_requested_stop_monitor = True 
                if self.app_orchestrator and hasattr(self.app_orchestrator, 'signal_shutdown_due_to_interrupt'):
                    self.app_orchestrator.signal_shutdown_due_to_interrupt()
                break 
            except EOFError: # pragma: no cover
                self.logger.log("CommandHandler: 检测到输入流结束 (EOF)，停止命令监控。", LogLevel.INFO)
                self._user_requested_stop_monitor = True
                # 可以选择在这里也触发退出流程
                if self.app_orchestrator and hasattr(self.app_orchestrator, 'request_shutdown'):
                     self.app_orchestrator.request_shutdown("EOF输入导致退出")
                break 
            except RuntimeError as e_runtime: # 例如，在非交互式环境中调用 input()
                if "input(): lost sys.stdin" in str(e_runtime) or not sys.stdin.isatty(): # pragma: no cover
                    self.logger.log("CommandHandler: 在非TTY环境或stdin丢失时无法读取命令，停止命令监控。", LogLevel.WARNING)
                    self._user_requested_stop_monitor = True
                    break
                else: # pragma: no cover
                    self.logger.log(f"CommandHandler: 命令监控线程发生运行时错误: {e_runtime}", LogLevel.ERROR, exc_info=True)
                    time.sleep(1)
            except Exception as e: # pragma: no cover
                self.logger.log(f"CommandHandler: 命令监控线程发生未知错误: {e}", LogLevel.ERROR, exc_info=True)
                time.sleep(1) 

        self.logger.log("CommandHandler: 命令监控循环结束。", LogLevel.DEBUG)

    def _timed_input_for_exit(self, prompt_message: str, default_choice: str, timeout_seconds: int) -> str:
        """
        带超时的输入确认，使用 sys.stdin.readline() 和线程。
        这是恢复到类似原始脚本中的超时逻辑。
        """
        if not sys.stdin.isatty(): # 非交互模式直接返回默认值
            self.logger.log(f"CommandHandler: 非交互模式，为 '{prompt_message}' 自动选择 '{default_choice}'", LogLevel.DEBUG)
            return default_choice

        # 清理当前行，然后打印提示
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        print(f"{Fore.YELLOW}{prompt_message}{Style.RESET_ALL} (输入 'c' 取消, {timeout_seconds}秒后自动选择 '{default_choice}'): ", end="", flush=True)
        
        container = [default_choice] # 使用列表使内部函数可以修改外部变量的值
        event = threading.Event()

        def get_input_thread_func():
            try:
                # sys.stdin.readline() 会读取包括换行符在内的整行
                val = sys.stdin.readline().strip().lower()
                if val == 'c':
                    container[0] = 'c'
                elif val == 'y' or val == 'n': # 接受明确的 y 或 n
                    container[0] = val
                elif not val: # 用户直接回车
                    container[0] = default_choice # 按默认处理
                # 其他无效输入，container[0] 保持为 default_choice
            except Exception as e_input_thread: # pragma: no cover
                self.logger.log(f"CommandHandler: _timed_input_for_exit 的输入线程出错: {e_input_thread}", LogLevel.WARNING)
                # 出错时，container[0] 保持为 default_choice
            finally:
                event.set() # 通知主线程输入已完成或出错

        input_thread = threading.Thread(target=get_input_thread_func, daemon=True)
        input_thread.start()
        
        event.wait(timeout=float(timeout_seconds)) # 等待事件或超时

        # 超时后，input_thread 仍然是 daemon，会在程序退出时结束
        # 但它可能已经读取了一行输入，只是我们不再关心它的结果
        # 我们需要确保控制台光标回到下一行，并且清除可能残留的输入
        sys.stdout.write("\r\033[K") # 清除用户可能已输入但未提交的内容
        sys.stdout.flush()

        if not event.is_set(): # 超时了
            print(f"{Fore.YELLOW}输入超时，自动选择 '{default_choice}'。{Style.RESET_ALL}")
            # container[0] 已经是 default_choice
        else: # 用户有输入 (或者线程出错)
            if container[0] == 'c':
                print(f"{Fore.GREEN}操作已取消。{Style.RESET_ALL}")
            elif container[0] == default_choice : # 包括用户输入了默认值或直接回车的情况
                print(f"{Fore.CYAN}操作确认 (选择: '{container[0]}')。{Style.RESET_ALL}")
            elif container[0] in ['y', 'n']: # 用户输入了明确的y/n，且不同于默认值
                 print(f"{Fore.CYAN}操作确认 (选择: '{container[0]}')。{Style.RESET_ALL}")
            else: # 其他情况（例如线程内出错，或无效输入但没被上面捕获）
                print(f"{Fore.YELLOW}输入无效或线程错误，按默认 '{default_choice}' 处理。{Style.RESET_ALL}")
                container[0] = default_choice # 确保返回的是有效选项

        return container[0]


    def _handle_quit_command(self) -> bool:
        self.logger.log("CommandHandler: 用户请求退出 ('q'命令)...", LogLevel.INFO)
        user_choice = self._timed_input_for_exit(
            prompt_message="您确定要退出程序吗?", 
            default_choice="y", 
            timeout_seconds=AppConstants.EXIT_PROMPT_TIMEOUT_SECONDS
        )
        if user_choice == 'y':
            self.logger.log("CommandHandler: 用户确认退出。", LogLevel.INFO)
            if self.app_orchestrator and hasattr(self.app_orchestrator, 'request_shutdown'):
                self.app_orchestrator.request_shutdown("用户通过 'q' 命令请求退出")
                return True 
            else: self.logger.log("CommandHandler: AppOrchestrator 未配置。", LogLevel.ERROR); return False # pragma: no cover
        else: # 'n' 或 'c' (取消)
            self.logger.log("CommandHandler: 用户取消了退出操作。", LogLevel.INFO); return False 

    def _handle_sign_now_command(self) -> bool:
        self.logger.log("CommandHandler: 用户请求立即执行签到检查...", LogLevel.INFO)
        if not self.main_task_runner or not hasattr(self.main_task_runner, 'trigger_immediate_sign_cycle'): # pragma: no cover
            self.logger.log("CommandHandler: MainTaskRunner 未配置。", LogLevel.ERROR)
            print(f"{Fore.RED}错误：无法触发立即签到，内部组件未正确初始化。{Style.RESET_ALL}")
            return False
        if self.main_task_runner.trigger_immediate_sign_cycle():
            return True
        return False
        
    def _show_status(self) -> None:
        print(f"\n{Fore.CYAN}{Style.BRIGHT}=== 当前运行状态 ==={Style.RESET_ALL}")
        print("-" * 40)
        if not self.main_task_runner or \
           not self.sign_service or \
           not hasattr(self.main_task_runner, 'base_config') or \
           not self.main_task_runner.base_config: # pragma: no cover
            print(f"{Fore.RED}错误：无法获取完整状态，核心组件未完全初始化或配置未加载。{Style.RESET_ALL}"); return
        print(f"程序运行状态: {'运行中' if self.application_run_event.is_set() and not self._user_requested_stop_monitor else '已停止/正在停止'}")
        print(f"总检索次数: {getattr(self.main_task_runner, 'sign_cycle_count', 'N/A')}")
        print(f"总成功签到 (自启动): {self.sign_service.get_total_successful_sign_ins() if hasattr(self.sign_service, 'get_total_successful_sign_ins') else 'N/A'}")
        cfg = self.main_task_runner.base_config
        class_ids_cfg = cfg.get("class_ids", [])
        print(f"监控的班级ID(s): {', '.join(class_ids_cfg) if class_ids_cfg else f'{Fore.RED}未配置{Style.RESET_ALL}'}")
        config_remark = cfg.get("remark", f"{Fore.YELLOW}未设置备注{Style.RESET_ALL}")
        print(f"配置备注: {Fore.CYAN}{config_remark}{Style.RESET_ALL}")
        print(f"当前坐标模式: {'动态随机 (基于学校)' if getattr(self.main_task_runner, 'should_randomize', False) else '固定配置'}")
        current_coords = getattr(self.main_task_runner, 'current_dynamic_coords', {})
        if current_coords:
            print(f"  当前使用坐标: Lat={current_coords.get('lat', 'N/A')}, Lng={current_coords.get('lng', 'N/A')}, Acc={current_coords.get('acc', 'N/A')}")
            if getattr(self.main_task_runner, 'should_randomize', False) and cfg.get("selected_school"):
                school_info = cfg.get("selected_school", {}) 
                print(f"  基于学校: [ID: {school_info.get('id', 'N/A')}] {school_info.get('addr', 'N/A')}")
        runtime_exit_mode_val = self.main_task_runner.get_runtime_exit_after_sign() if hasattr(self.main_task_runner, 'get_runtime_exit_after_sign') else cfg.get('exit_after_sign', False)
        print(f"签到后退出 (当前会话): {'启用' if runtime_exit_mode_val else '禁用'}")
        if cfg.get("enable_time_range"):
            print(f"时间段控制: 已启用 (运行于 {cfg.get('start_time','N/A')} - {cfg.get('end_time','N/A')})")
            if hasattr(self.main_task_runner, '_is_within_time_range') and not self.main_task_runner._is_within_time_range(): # pragma: no cover
                print(f"  {Fore.YELLOW}注意: 当前不在运行时间段内。{Style.RESET_ALL}")
        else: print("时间段控制: 已禁用")
        print(f"\n{Fore.CYAN}--- 本会话已成功处理/确认的签到任务 (按班级) ---{Style.RESET_ALL}")
        all_fetched_class_details = cfg.get("all_fetched_class_details", []) 
        signed_tasks_by_class: Dict[str, Set[str]] = {}
        if hasattr(self.main_task_runner, 'sign_cycle_history') and self.main_task_runner.sign_cycle_history:
            for cycle_entry in self.main_task_runner.sign_cycle_history:
                class_id = cycle_entry.get("class_id_processed_in_sub_cycle")
                processed_ids = cycle_entry.get("sign_ids_processed", [])
                if class_id and class_id != "N/A" and processed_ids:
                    if class_id not in signed_tasks_by_class: signed_tasks_by_class[class_id] = set()
                    for sid in processed_ids: signed_tasks_by_class[class_id].add(str(sid))
        if signed_tasks_by_class:
            for class_id_key, sign_ids_set in signed_tasks_by_class.items():
                class_name_display = class_id_key
                if all_fetched_class_details:
                    for detail in all_fetched_class_details:
                        if str(detail.get("id")) == str(class_id_key): class_name_display = f"{detail.get('name', class_id_key)} (ID: {class_id_key})"; break
                if sign_ids_set: print(f"  班级 {Fore.GREEN}{class_name_display}{Style.RESET_ALL}: {Fore.GREEN}{', '.join(sorted(list(sign_ids_set)))}{Style.RESET_ALL}")
        else:
            overall_signed_ids = self.sign_service.signed_ids if hasattr(self.sign_service, 'signed_ids') else set()
            if overall_signed_ids: print(f"  {Fore.YELLOW}本会话累计已签到任务ID (无班级详情): {', '.join(sorted(list(str(sid) for sid in overall_signed_ids))[:10])}{'...' if len(overall_signed_ids) > 10 else ''}{Style.RESET_ALL}")
            else: print(f"  {Fore.YELLOW}本会话尚未记录到成功的签到任务。{Style.RESET_ALL}")
        invalid_ids_set = self.sign_service.invalid_sign_ids if hasattr(self.sign_service, 'invalid_sign_ids') else set()
        if invalid_ids_set:
            print(f"\n{Fore.CYAN}--- 本会话标记为永久无效的任务ID ---{Style.RESET_ALL}")
            print(f"  {Fore.RED}{', '.join(sorted(list(str(sid) for sid in invalid_ids_set))[:10])}{'...' if len(invalid_ids_set) > 10 else ''}{Style.RESET_ALL}")
        print("-" * 40)

    def _handle_status_command(self) -> bool:
        self._show_status(); return True

    def _handle_exit_mode_command(self) -> bool:
        if not self.main_task_runner or not hasattr(self.main_task_runner, 'get_runtime_exit_after_sign') or not hasattr(self.main_task_runner, 'set_runtime_exit_after_sign'): 
            self.logger.log("CommandHandler: MainTaskRunner 未正确配置以切换退出模式。", LogLevel.ERROR); print(f"{Fore.RED}错误：无法切换退出模式。{Style.RESET_ALL}"); return False
        current_mode = self.main_task_runner.get_runtime_exit_after_sign(); new_mode = not current_mode
        self.main_task_runner.set_runtime_exit_after_sign(new_mode); status = "启用" if new_mode else "禁用"
        self.logger.log(f"CommandHandler: 签到后退出模式已{status} (仅当前会话)", LogLevel.INFO)
        print(f"{Fore.GREEN}签到后退出模式已{status} (仅当前会话)。此设置不会保存到配置文件。{Style.RESET_ALL}"); return True

    def _handle_config_command(self) -> bool:
        self.logger.log("CommandHandler: 用户请求修改配置...", LogLevel.INFO)
        print(f"{Fore.YELLOW}配置修改将在程序下次启动时通过配置向导进行。{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}您现在可以输入 'q' 退出程序，然后重新运行以进入配置。{Style.RESET_ALL}"); return True

    def _handle_help_command(self) -> bool:
        print(f"\n{Fore.CYAN}=== 可用命令 ==={Style.RESET_ALL}"); print("-" * 40)
        for cmd, desc in sorted(self.command_descriptions.items()): print(f"{Fore.GREEN}{cmd.ljust(10)}{Style.RESET_ALL}: {desc}")
        print("-" * 40); return True

    def _handle_history_command(self) -> bool:
        if not self.command_history_list: print(f"{Fore.YELLOW}暂无内部命令历史记录{Style.RESET_ALL}"); return True 
        print(f"\n{Fore.CYAN}=== 命令历史记录 (最近10条) ==={Style.RESET_ALL}"); print("-" * 40)
        for idx, (timestamp, cmd) in enumerate(self.command_history_list[-10:], 1):
            time_str = timestamp.strftime("%H:%M:%S"); print(f"{idx}. [{time_str}] {cmd}: {self.command_descriptions.get(cmd, '未知命令')}")
        print("-" * 40); return True

    def _handle_stats_command(self) -> bool:
        if not self.main_task_runner or not self.sign_service or \
           not hasattr(self.main_task_runner, 'sign_cycle_history') or \
           not hasattr(self.sign_service, 'get_total_successful_sign_ins'): 
            print(f"{Fore.YELLOW}暂无签到统计信息 (组件未初始化或无周期记录){Style.RESET_ALL}"); return False
        cycle_history = self.main_task_runner.sign_cycle_history
        if not cycle_history: print(f"{Fore.YELLOW}暂无签到统计信息 (尚未完成一个检索周期){Style.RESET_ALL}"); return True 
        print(f"\n{Fore.CYAN}=== 签到统计 ==={Style.RESET_ALL}"); print("-" * 40)
        print(f"🔄 总检索次数: {getattr(self.main_task_runner, 'sign_cycle_count', 'N/A')}")
        print(f"📈 总成功签到 (自启动): {self.sign_service.get_total_successful_sign_ins()}")
        last_class_processed_info = cycle_history[-1] 
        print(f"\n--- 最近处理班级信息 (周期 #{last_class_processed_info.get('cycle_num', 'N/A')} 内) ---")
        print(f"  处理班级ID: {last_class_processed_info.get('class_id_processed_in_sub_cycle', 'N/A')}")
        found_ids = last_class_processed_info.get('sign_ids_found', []); processed_ids = last_class_processed_info.get('sign_ids_processed', []); skipped_ids = last_class_processed_info.get('sign_ids_skipped', [])
        print(f"🔍 找到任务: {len(found_ids)} 个 ({', '.join(map(str,found_ids)) if found_ids else '无'})")
        print(f"✅ 成功签到/已签: {len(processed_ids)} 个 ({', '.join(map(str,processed_ids)) if processed_ids else '无'})")
        print(f"⏭️ 跳过/无效/失败: {len(skipped_ids)} 个 ({', '.join(map(str,skipped_ids)) if skipped_ids else '无'})")
        if last_class_processed_info.get('error'): print(f"❌ 错误: {last_class_processed_info['error']}")
        total_tasks_found_in_session = sum(len(c.get('sign_ids_found', [])) for c in cycle_history)
        total_tasks_processed_in_session = sum(len(c.get('sign_ids_processed', [])) for c in cycle_history)
        if total_tasks_found_in_session > 0:
            session_success_rate = (total_tasks_processed_in_session / total_tasks_found_in_session) * 100
            print(f"\n📊 本次会话签到任务成功率 (基于已发现任务): {session_success_rate:.2f}%")
        else: print(f"\n📊 本次会话尚未发现可处理的签到任务。")
        print("-" * 40); return True

    def _handle_update_command(self) -> bool:
        self.logger.log("CommandHandler: 用户请求执行更新程序...", LogLevel.INFO)
        if self.app_orchestrator and hasattr(self.app_orchestrator, 'trigger_update_process'):
            self.app_orchestrator.trigger_update_process(); return True 
        else: self.logger.log("CommandHandler: AppOrchestrator 未配置。", LogLevel.ERROR); print(f"{Fore.RED}错误：无法执行更新。{Style.RESET_ALL}"); return False