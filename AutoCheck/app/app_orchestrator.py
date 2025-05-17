# app/app_orchestrator.py
import sys
import os
import threading
import time
import traceback 
from typing import Dict, Any, Optional

from app.constants import AppConstants, SCRIPT_VERSION
from app.logger_setup import LoggerInterface, FileLogger, LogLevel
from app.exceptions import ServiceAccessError, UpdateRequiredError, ConfigError

from app.config.storage import JsonConfigStorage
from app.config.manager import ConfigManager
from app.config.remote_manager import RemoteConfigManager
from app.config.models import NotificationSettings, ConfigModel # NotificationSettings for type hint, ConfigModel for ensuring app_config structure

from app.utils.app_utils import write_version_file, launch_updater_and_exit, get_app_dir
from app.utils.display_utils import tampilkan_info_aplikasi_dasar, tampilkan_免责声明_并获取用户同意

from app.services.device_manager import DeviceManager
from app.services.location_engine import LocationEngine
from app.services.data_uploader import DataUploader
from app.services.sign_service import SignService
from app.services.notification import NotificationManager 

from app.cli.setup_wizard import SetupWizard
from app.cli.command_handler import CommandHandler

from app.tasks.background_job_manager import BackgroundJobManager
from app.tasks.main_task_runner import MainTaskRunner

from packaging.version import parse as parse_version
from colorama import Fore, Style


class AppOrchestrator:
    def __init__(self):
        self.application_run_event = threading.Event()
        self.application_run_event.set() 

        self._exit_code: int = 0
        self._exit_reason: str = "应用启动流程未完成" 
        self._main_task_exception: Optional[Exception] = None
        self._app_must_exit_due_to_initial_check: bool = False
        self.is_update_failure_fatal: bool = False 

        self.logger: Optional[LoggerInterface] = None
        self.local_config_manager: Optional[ConfigManager] = None
        self.remote_config_manager_instance: Optional[RemoteConfigManager] = None
        self.current_device_id: Optional[str] = None
        self.app_config: Optional[ConfigModel] = None # 将使用ConfigModel类型
        self.location_engine_instance: Optional[LocationEngine] = None
        
        self.notification_manager: Optional[NotificationManager] = None 
        self.data_uploader_instance: Optional[DataUploader] = None
        self.sign_service: Optional[SignService] = None
        self.main_task_runner: Optional[MainTaskRunner] = None
        self.command_handler: Optional[CommandHandler] = None
        self.bg_job_manager: Optional[BackgroundJobManager] = None

    # 在 AppOrchestrator 类的 _initialize_logger 方法中
    def _initialize_logger(self):
        if "--debug-console" in sys.argv: 
            console_log_level = LogLevel.DEBUG
        else: 
            console_log_level = LogLevel.INFO # <--- 改回 INFO，这样INFO和DEBUG(如果用了--debug-console)日志都会在控制台显示

        log_file_name = f"{AppConstants.APP_NAME}.log"
        self.logger = FileLogger(log_file=log_file_name, console_level=console_log_level)
        self.logger.log(f"--- {AppConstants.APP_NAME} v{SCRIPT_VERSION} 应用编排器开始初始化 ---", LogLevel.INFO)
        self.logger.log(f"控制台日志级别已设置为: {console_log_level.name} (文件日志始终为DEBUG及以上)", LogLevel.INFO)
   
   
    def _perform_initial_setup_and_checks(self) -> bool:
        if not self.logger:
            # This should ideally not happen if _initialize_logger is called first in run()
            print("CRITICAL: Logger未在执行初始设置前初始化!") # Fallback print
            self._app_must_exit_due_to_initial_check = True
            self._exit_reason = "Logger初始化失败"
            self._exit_code = 1
            return False

        try:
            tampilkan_info_aplikasi_dasar(self.logger)
            config_storage = JsonConfigStorage(config_path=AppConstants.CONFIG_FILE)
            self.local_config_manager = ConfigManager(storage=config_storage, logger=self.logger)

            if not tampilkan_免责声明_并获取用户同意(self.logger, self.local_config_manager):
                # tampilkan_免责声明_并获取用户同意 内部已打印和记录日志
                raise ConfigError("用户未同意免责声明，应用终止。")

            write_version_file(self.logger) # logger is now guaranteed to exist
            device_manager = DeviceManager(self.logger, device_id_file=AppConstants.DEVICE_ID_FILE)
            self.current_device_id = device_manager.get_id()
            self.logger.log(f"当前设备ID: {self.current_device_id}", LogLevel.INFO)

            self.remote_config_manager_instance = RemoteConfigManager(
                self.logger,
                AppConstants.PRIMARY_REMOTE_CONFIG_URL,
                AppConstants.SECONDARY_REMOTE_CONFIG_URL,
                self.application_run_event # Pass the event
            )
            if not self.remote_config_manager_instance._last_successful_fetch_time: # Accessing private for check
                self.logger.log("警告: 初始远程配置获取失败，将使用默认远程配置。", LogLevel.WARNING)
            else:
                self.logger.log("初始远程配置已加载。", LogLevel.INFO)
            
            announcement = self.remote_config_manager_instance.get_announcement()
            if announcement and announcement.get("enabled"):
                ann_title = announcement.get("title", "公告")
                ann_msg = announcement.get("message")
                # Log and print for visibility
                self.logger.log(f"{Fore.MAGENTA}📢 [{ann_title}] {ann_msg}{Style.RESET_ALL}", LogLevel.INFO)

            self.logger.log("执行启动时更新检查...", LogLevel.INFO)
            if self.remote_config_manager_instance.is_forced_updates_enabled():
                forced_version_str = self.remote_config_manager_instance.get_forced_update_below_version()
                if forced_version_str and forced_version_str != "0.0.0":
                    if parse_version(SCRIPT_VERSION) < parse_version(forced_version_str):
                        reason = self.remote_config_manager_instance.get_forced_update_reason()
                        update_msg = (f"检测到强制更新！当前版本 {SCRIPT_VERSION} < 最低要求 {forced_version_str}。"
                                      f"{f' 原因: {reason}' if reason else ''}")
                        self.logger.log(update_msg, LogLevel.CRITICAL)
                        print(f"\n{Fore.RED}*** 强制更新通知 ***\n{update_msg}\n将尝试启动更新程序...{Style.RESET_ALL}")
                        self.is_update_failure_fatal = True 
                        self._trigger_update_process_internal() # This calls launch_updater_and_exit
                        # If launch_updater_and_exit doesn't sys.exit(), it means updater failed to start
                        self.logger.log("强制更新：无法启动更新程序或更新程序未找到。程序必须退出。", LogLevel.CRITICAL)
                        raise UpdateRequiredError(update_msg, forced_version_str, SCRIPT_VERSION, reason)
            
            self.is_update_failure_fatal = False # Reset for optional updates

            latest_stable_str = self.remote_config_manager_instance.get_config_value(["latest_stable_version"], "0.0.0")
            if latest_stable_str and latest_stable_str != "0.0.0":
                if parse_version(SCRIPT_VERSION) < parse_version(latest_stable_str):
                    opt_msg_template = self.remote_config_manager_instance.get_optional_update_message_template()
                    opt_msg = (opt_msg_template.format(latest_stable_version=latest_stable_str, current_version=SCRIPT_VERSION)
                               if opt_msg_template
                               else f"发现新版本 {latest_stable_str} 可用！(当前: {SCRIPT_VERSION})\n建议稍后在程序内输入 'update' 命令更新。")
                    self.logger.log(f"检测到可选更新: {latest_stable_str}", LogLevel.INFO)
                    print(f"\n{Fore.GREEN}💡 可选更新提示 💡\n{opt_msg}{Style.RESET_ALL}\n")

            self.logger.log("执行启动时访问控制检查...", LogLevel.DEBUG)
            if self.remote_config_manager_instance.is_globally_disabled():
                msg = self.remote_config_manager_instance.get_global_disable_message()
                self.logger.log(f"远程配置: 全局禁用已激活。消息: '{msg}'. 程序将退出。", LogLevel.CRITICAL)
                print(f"\n{Fore.RED}🚫 服务通知 🚫\n{msg}{Style.RESET_ALL}")
                raise ServiceAccessError(f"全局禁用: {msg}")

            if not self.remote_config_manager_instance.is_device_allowed(self.current_device_id): # type: ignore
                msg_template = self.remote_config_manager_instance.get_device_block_message_template()
                msg = msg_template.format(device_id=self.current_device_id)
                self.logger.log(f"远程配置: 设备 {self.current_device_id} 被禁止。消息: '{msg}'. 程序将退出。", LogLevel.CRITICAL)
                print(f"\n{Fore.RED}🚫 访问限制 🚫\n{msg}{Style.RESET_ALL}")
                raise ServiceAccessError(f"设备被禁用: {msg}")

            self.logger.log("初始设置和检查通过。", LogLevel.INFO)
            return True

        except (ConfigError, UpdateRequiredError, ServiceAccessError) as e_init_check:
            self.logger.log(f"初始设置检查失败，要求应用终止: {e_init_check}", LogLevel.CRITICAL)
            self._main_task_exception = e_init_check
            self._exit_reason = str(e_init_check.args[0] if e_init_check.args else type(e_init_check).__name__)
            self._exit_code = 1
            self._app_must_exit_due_to_initial_check = True
            self.application_run_event.clear() # Prevent further operations
            return False
        except Exception as e_unexpected: # Catch any other unexpected error during this phase
            self.logger.log(f"初始设置和检查过程中发生意外错误: {e_unexpected}", LogLevel.CRITICAL, exc_info=True)
            self._main_task_exception = e_unexpected
            self._exit_reason = f"初始设置意外失败: {type(e_unexpected).__name__}"
            self._exit_code = 1
            self._app_must_exit_due_to_initial_check = True
            self.application_run_event.clear()
            return False

    def _initialize_core_components(self):
        if not (self.logger and self.local_config_manager and self.current_device_id and self.remote_config_manager_instance):
            # This check ensures that _perform_initial_setup_and_checks ran successfully enough
            # for these to be initialized.
            log_msg = "基础组件未在核心组件初始化前完全准备好，终止。"
            if self.logger: self.logger.log(log_msg, LogLevel.CRITICAL)
            else: print(f"CRITICAL_ERROR: {log_msg}")
            raise RuntimeError("核心组件初始化失败：基础依赖缺失。")

        try:
            self.location_engine_instance = LocationEngine(self.logger, AppConstants.SCHOOL_DATA_FILE)
        except ConfigError as e_loc_conf: # LocationEngine.__init__ can raise ConfigError if YAML parsing fails
            self.logger.log(f"LocationEngine 初始化配置错误: {e_loc_conf}。学校选择功能可能受限。", LogLevel.ERROR)
        except Exception as e_loc_init: # Catch any other unexpected error during LocationEngine init
            self.logger.log(f"LocationEngine 初始化时发生未知严重错误: {e_loc_init}。学校选择功能可能受限。", LogLevel.CRITICAL, exc_info=True)
        
        config_updater = SetupWizard(
            config_manager=self.local_config_manager,
            logger=self.logger,
            location_engine=self.location_engine_instance
        )
        self.logger.log("准备加载或初始化用户应用配置...", LogLevel.DEBUG)
        raw_app_config_dict = config_updater.init_config() # This returns a dict and can raise ConfigError
        
        if not raw_app_config_dict or not self.application_run_event.is_set(): 
            # init_config might clear application_run_event if user cancels via KeyboardInterrupt within it.
            self.logger.log("本地应用配置未成功加载或用户中止了配置。程序将退出。", LogLevel.CRITICAL)
            raise ConfigError("应用配置失败或被用户中止")
        
        # Validate and structure the config using ConfigModel
        try:
            self.app_config = ConfigModel(**raw_app_config_dict)
            # Persist all_fetched_class_details if it was part of raw_app_config_dict
            if "all_fetched_class_details" in raw_app_config_dict:
                 self.app_config.all_fetched_class_details = raw_app_config_dict["all_fetched_class_details"] # type: ignore
        except ValidationError as e_val_conf:
            self.logger.log(f"从配置向导加载的配置数据验证失败: {e_val_conf}", LogLevel.CRITICAL)
            # Delegate Pydantic error display to SetupWizard's handler for consistency
            config_updater._handle_pydantic_validation_error(e_val_conf) # type: ignore
            raise ConfigError(f"最终应用配置验证失败: {e_val_conf}")

        self.logger.log("本地应用配置加载/创建并验证成功。", LogLevel.INFO)

        # Initialize NotificationManager using the 'notifications' part of app_config
        # app_config.notifications is already a NotificationSettings object due to ConfigModel default_factory
        self.notification_manager = NotificationManager(
            notification_settings=self.app_config.notifications, 
            logger=self.logger, 
            app_name=AppConstants.APP_NAME
        )

        self.data_uploader_instance = DataUploader(
            logger=self.logger, device_id=self.current_device_id,
            github_gist_id=AppConstants.DATA_UPLOAD_GIST_ID,
            github_filename=AppConstants.DATA_UPLOAD_FILENAME,
            github_pat=AppConstants.GITHUB_PAT,
            gitee_gist_id=AppConstants.GITEE_DATA_UPLOAD_GIST_ID,
            gitee_filename=AppConstants.GITEE_DATA_UPLOAD_FILENAME,
            gitee_pat=AppConstants.GITEE_PAT,
            initial_config=self.app_config.model_dump() # Pass the dict form
        )

        self.sign_service = SignService(
            logger=self.logger,
            app_config=self.app_config.model_dump(), # Pass the dict form
            remote_config_manager=self.remote_config_manager_instance,
            notification_manager=self.notification_manager # Pass the manager instance
        )

        self.main_task_runner = MainTaskRunner(
            logger=self.logger,
            app_config=self.app_config.model_dump(), # Pass the dict form
            application_run_event=self.application_run_event,
            remote_config_manager=self.remote_config_manager_instance,
            sign_service=self.sign_service,
            location_engine=self.location_engine_instance,
            data_uploader_instance=self.data_uploader_instance,
            device_id=self.current_device_id
        )

        self.command_handler = CommandHandler(
            logger=self.logger,
            application_run_event=self.application_run_event,
            app_orchestrator_ref=self, 
            sign_service_ref=self.sign_service,
            main_task_runner_ref=self.main_task_runner
        )

        self.bg_job_manager = BackgroundJobManager(self.logger, self.application_run_event)

        config_refresh_interval = self.remote_config_manager_instance.get_setting(
            "config_refresh_interval_seconds", AppConstants.DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS
        )
        if config_refresh_interval > 0:
            self.bg_job_manager.add_job(
                self.remote_config_manager_instance.fetch_config,
                config_refresh_interval,
                "RemoteConfigRefresh"
            )

        data_upload_interval = self.remote_config_manager_instance.get_setting(
            "data_upload_interval_seconds", AppConstants.DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS
        )
        
        # --- Diagnostic logs for MainTaskRunner attributes (kept less verbose) ---
        if self.main_task_runner: 
            self.logger.log(f"DIAGNOSTIC: type of self.main_task_runner is {type(self.main_task_runner)}", LogLevel.DEBUG)
            if hasattr(self.main_task_runner, '_upload_data_job'):
                self.logger.log("DIAGNOSTIC: MainTaskRunner has '_upload_data_job'.", LogLevel.DEBUG)
            else:
                self.logger.log("DIAGNOSTIC: MainTaskRunner MISSING '_upload_data_job'!", LogLevel.ERROR)
        # --- End diagnostic logs ---

        if data_upload_interval > 0 and self.data_uploader_instance and self.main_task_runner:
            if hasattr(self.main_task_runner, '_upload_data_job'):
                self.bg_job_manager.add_job( 
                    self.main_task_runner._upload_data_job, 
                    data_upload_interval,
                    "DataUpload"
                )
            else: 
                self.logger.log("CRITICAL_ERROR: MainTaskRunner instance does not have _upload_data_job attribute when adding job.", LogLevel.CRITICAL)
                raise AttributeError("'MainTaskRunner' object (checked by AppOrchestrator) has no attribute '_upload_data_job'")

        self.logger.log("核心组件初始化完毕。", LogLevel.INFO)

    def run(self) -> int:
        try:
            self._initialize_logger()
            
            if not self._perform_initial_setup_and_checks():
                # _perform_initial_setup_and_checks already set exit reason/code and cleared event
                self._app_must_exit_due_to_initial_check = True 
            
            if self.application_run_event.is_set() and not self._app_must_exit_due_to_initial_check:
                self._initialize_core_components() 

                if not self.application_run_event.is_set(): 
                     # Core components init might have cleared the event (e.g., ConfigError)
                     self.logger.log("核心组件初始化失败或被中止，应用无法启动。", LogLevel.CRITICAL) # type: ignore
                     self._exit_reason = self._exit_reason or "核心组件初始化失败" 
                     self._exit_code = self._exit_code or 1 # Preserve earlier error code if set
                else:
                    self.logger.log("所有组件初始化完成，准备启动主任务和后台服务...", LogLevel.INFO) # type: ignore
                    if self.bg_job_manager: self.bg_job_manager.start_jobs()
                    if self.command_handler: self.command_handler.start_command_monitoring()
                    
                    # Set default exit reason for normal completion, if not overridden by an error
                    self._exit_reason = "应用正常结束主循环" 
                    self._exit_code = 0
                    if self.main_task_runner: self.main_task_runner.run_loop() # This is blocking
            
            # If we reach here because _app_must_exit_due_to_initial_check was true
            elif self._app_must_exit_due_to_initial_check and self.logger : # Ensure logger exists
                 self.logger.log(f"由于初始检查失败或被中止 (原因: {self._exit_reason})，应用将不启动核心组件。", LogLevel.WARNING)

        # --- Exception Handling for main execution phases ---
        except UpdateRequiredError as ure:
            self._handle_specific_exit_exception(ure, f"强制更新失败 (需 {ure.required_version}, 当前 {ure.current_version})" + (f" 原因: {ure.reason}" if ure.reason else ""))
        except ServiceAccessError as sae:
            self._handle_specific_exit_exception(sae, str(sae.args[0] if sae.args else type(sae).__name__))
        except ConfigError as ce:
            self._handle_specific_exit_exception(ce, f"配置流程错误: {ce.args[0] if ce.args else type(ce).__name__}")
        except AttributeError as ae: 
            if self.logger: self.logger.log(f"AppOrchestrator: 捕获到 AttributeError: {ae}", LogLevel.CRITICAL, exc_info=True)
            else: print(f"CRITICAL AttributeError (Logger N/A): {ae}"); traceback.print_exc() 
            self._main_task_exception = ae; self._exit_reason = f"发生 AttributeError: {ae}"; self._exit_code = 1
        except KeyboardInterrupt:
            if self.logger: self.logger.log("AppOrchestrator: 检测到用户中断 (Ctrl+C)。", LogLevel.INFO)
            self._main_task_exception = KeyboardInterrupt("用户中断操作"); self._exit_reason = "用户通过 Ctrl+C 中断操作"; self._exit_code = 0 
        except SystemExit as se: 
            if self.logger: self.logger.log(f"AppOrchestrator: 程序通过 SystemExit 请求退出 (代码: {se.code})。", LogLevel.INFO)
            self._main_task_exception = se; self._exit_reason = f"程序请求SystemExit (代码: {se.code if se.code is not None else 'N/A'})"; self._exit_code = se.code if se.code is not None else 0 
        except Exception as e:
            if self.logger:
                self.logger.log(f"AppOrchestrator: 发生未捕获的致命错误: {e}", LogLevel.CRITICAL, exc_info=True)
            else: # Fallback if logger itself failed
                print(f"CRITICAL ERROR (Logger not available): {e}"); traceback.print_exc() 
            self._main_task_exception = e; self._exit_reason = f"发生未处理的致命错误: {type(e).__name__}"; self._exit_code = 1
        finally:
            self._perform_shutdown() # Ensures cleanup and consistent exit logging
            
        return self._exit_code

    def _handle_specific_exit_exception(self, exc: Exception, reason_prefix: str):
        if self.logger: self.logger.log(f"AppOrchestrator: {reason_prefix}，应用终止。", LogLevel.CRITICAL)
        else: print(f"CRITICAL ERROR (Logger N/A): {reason_prefix}")
        self._main_task_exception = exc; self._exit_reason = reason_prefix; self._exit_code = 1
        if self.application_run_event.is_set():
            self.application_run_event.clear()

    def _perform_shutdown(self):
        # ... (此方法与之前提供的版本一致，主要负责日志、保存成功次数、打印最终退出消息) ...
        # Ensure logger exists or try to create an emergency one
        if not self.logger:
            try:
                print("Logger未初始化，尝试创建紧急日志记录器...")
                log_dir = os.path.join(get_app_dir() or ".", AppConstants.LOG_DIR if hasattr(AppConstants, "LOG_DIR") else "logs")
                if not os.path.exists(log_dir): os.makedirs(log_dir, exist_ok=True)
                emergency_log_file = os.path.join(log_dir, f"{getattr(AppConstants, 'APP_NAME', 'App')}_emergency_shutdown.log")
                def emergency_logger_func(msg, level: LogLevel = LogLevel.INFO, exc_info_val=False): # Match expected signature
                    level_str = level.name if isinstance(level, LogLevel) else str(level)
                    print(f"[{datetime.now()}] [{level_str}] {msg}")
                    if exc_info_val: traceback.print_exc() 
                self.logger = type('EmergencyLogger', (), {'log': staticmethod(emergency_logger_func)})() # type: ignore
                self.logger.log("--- 应用进入紧急关闭流程 (主Logger可能未初始化) ---", LogLevel.WARNING) # type: ignore
            except Exception as e_emergency_log: # noqa
                print(f"CRITICAL: 紧急Logger创建失败: {e_emergency_log}")
                print(f"CRITICAL: 退出原因: {self._exit_reason}, 退出码: {self._exit_code}")
                time.sleep(AppConstants.GRACEFUL_ERROR_EXIT_DELAY_SECONDS if hasattr(AppConstants, 'GRACEFUL_ERROR_EXIT_DELAY_SECONDS') else 3)
                return

        self.logger.log("AppOrchestrator: 开始执行关闭流程...", LogLevel.INFO) 
        if self.application_run_event.is_set():
            self.logger.log("AppOrchestrator: 清理 application_run_event。", LogLevel.DEBUG) 
            self.application_run_event.clear()

        if self.command_handler and hasattr(self.command_handler, 'stop_command_monitoring'):
            self.command_handler.stop_command_monitoring()
        
        if self.bg_job_manager and hasattr(self.bg_job_manager, 'threads') and self.bg_job_manager.threads:
            self.logger.log("AppOrchestrator: 等待后台任务线程（daemon）随主程序结束...", LogLevel.DEBUG) 

        if self.sign_service and self.local_config_manager and hasattr(self.local_config_manager, 'config') and self.local_config_manager.config:
            try:
                # app_config 应该是 ConfigModel 实例，从中获取 total_successful_sign_ins
                # 或者让 SignService 直接管理这个值的更新，并在结束时从 SignService 获取
                # 这里假设 SignService 内部有 get_total_successful_sign_ins 方法
                final_total_success = self.sign_service.get_total_successful_sign_ins()
                
                # manager.config 是字典形式
                current_config_dict = self.local_config_manager.config
                current_saved_total = current_config_dict.get('total_successful_sign_ins', 0)

                if final_total_success > current_saved_total or 'total_successful_sign_ins' not in current_config_dict :
                    self.logger.log(f"AppOrchestrator: 准备保存最终总成功签到次数: {final_total_success}", LogLevel.INFO) 
                    current_config_dict['total_successful_sign_ins'] = final_total_success
                    self.local_config_manager.save() # ConfigManager.save() 期望一个字典
                    self.logger.log("AppOrchestrator: 总成功签到次数已保存。", LogLevel.INFO) 
            except Exception as save_e:
                self.logger.log(f"AppOrchestrator: 退出时保存总成功签到次数失败: {save_e}", LogLevel.ERROR, exc_info=True) 
        elif self.logger: 
            self.logger.log("AppOrchestrator: SignService或ConfigManager未完全初始化，无法保存总成功签到次数。", LogLevel.WARNING)

        if self._app_must_exit_due_to_initial_check and not self._main_task_exception :
             pass 
        elif self._main_task_exception is None and self._exit_code == 0 and self._exit_reason == "应用启动流程未完成":
            self._exit_reason = "应用正常关闭"
        
        is_error_exit = self._exit_code != 0 and not isinstance(self._main_task_exception, KeyboardInterrupt)
        final_log_level = LogLevel.ERROR if is_error_exit else LogLevel.INFO
        self.logger.log(f"--- {AppConstants.APP_NAME} v{SCRIPT_VERSION} {self._exit_reason} (最终退出码: {self._exit_code}) ---", final_log_level) 
        
        if is_error_exit:
            print(f"{Fore.RED}程序因错误退出。详情请查看日志文件。{Style.RESET_ALL}")
            delay_seconds = getattr(AppConstants, 'GRACEFUL_ERROR_EXIT_DELAY_SECONDS', 3)
            self.logger.log(f"由于发生错误，程序将在 {delay_seconds} 秒后完全关闭...", LogLevel.DEBUG) 
            time.sleep(delay_seconds)
        elif self._exit_code == 0 and not isinstance(self._main_task_exception, KeyboardInterrupt):
            self.logger.log(f"程序正常关闭。将在短暂延时后退出...", LogLevel.DEBUG) 
            time.sleep(1)
            
        print(Style.RESET_ALL)

    def request_shutdown(self, reason: str, exit_code: int = 0):
        if not self.logger: print(f"SHUTDOWN REQUEST (Logger N/A): {reason}, code: {exit_code}")
        else: self.logger.log(f"AppOrchestrator: 收到关闭请求，原因: {reason}, 建议退出码: {exit_code}", LogLevel.INFO) 
        self._exit_reason = reason; self._exit_code = exit_code
        if self.application_run_event.is_set(): self.application_run_event.clear()

    def _trigger_update_process_internal(self):
        if not self.logger: print(f"{Fore.RED}错误：Logger未初始化，无法启动更新。{Style.RESET_ALL}"); return
        
        self.logger.log("AppOrchestrator: 准备启动更新程序...", LogLevel.INFO) 
        
        try:
            import app.utils.app_utils as app_utils_module
            original_global_flag_val = app_utils_module.forced_update_check_failed
            app_utils_module.forced_update_check_failed = self.is_update_failure_fatal
            self.logger.log(f"AppOrchestrator: 临时设置 app_utils.forced_update_check_failed = {self.is_update_failure_fatal}", LogLevel.DEBUG) 
            
            launch_updater_and_exit(self.logger) # 成功则退出，失败则继续
            
            app_utils_module.forced_update_check_failed = original_global_flag_val # 恢复
            self.logger.log(f"AppOrchestrator: 恢复 app_utils.forced_update_check_failed = {original_global_flag_val}", LogLevel.DEBUG) 

        except ImportError:  # pragma: no cover
            self.logger.log("AppOrchestrator: 无法导入 app.utils.app_utils 来修改全局变量，直接调用更新器。", LogLevel.WARNING) 
            launch_updater_and_exit(self.logger)
        except Exception as e_glob: # pragma: no cover
            self.logger.log(f"AppOrchestrator: 修改或恢复 app_utils 全局变量时出错: {e_glob}，直接调用更新器。", LogLevel.ERROR) 
            launch_updater_and_exit(self.logger)

        # 如果执行到这里，说明launch_updater_and_exit没有导致程序退出
        self.logger.log("AppOrchestrator: launch_updater_and_exit 执行完毕但程序未退出，表示更新器可能未成功启动。", LogLevel.WARNING) 

    def trigger_update_process(self):
        self.is_update_failure_fatal = False # 用户手动触发，更新器找不到不应是致命错误
        self._trigger_update_process_internal()
        if self.logger:
             self.logger.log("AppOrchestrator: 手动更新：更新程序未能成功启动或未找到。", LogLevel.WARNING)
        print(f"{Fore.YELLOW}更新程序未能启动。请检查 {AppConstants.UPDATER_EXE_NAME} 是否存在于应用根目录。{Style.RESET_ALL}")

    def signal_shutdown_due_to_interrupt(self):
        if self.application_run_event.is_set():
            if self.logger: self.logger.log("AppOrchestrator: 收到来自CommandHandler的KeyboardInterrupt信号。", LogLevel.INFO)
            self._main_task_exception = KeyboardInterrupt("用户通过命令界面中断")
            self._exit_reason = "用户通过命令界面中断操作 (来自命令处理器)"
            self._exit_code = 0
            self.application_run_event.clear()