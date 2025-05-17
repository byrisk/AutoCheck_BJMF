# app/utils/app_utils.py
import os
import sys
import subprocess
import time
from typing import Optional 

# launch_updater_and_exit 和 write_version_file 用到了 colorama 和 AppConstants/SCRIPT_VERSION
from colorama import Fore, Style 
from app.constants import AppConstants, SCRIPT_VERSION
from app.logger_setup import LoggerInterface, LogLevel # 用于类型提示和日志记录

# launch_updater_and_exit 原本依赖全局的 application_run_event 和 forced_update_check_failed
# 理想情况下，这些应该作为参数传入。
# 作为过渡，AppOrchestrator 会在调用前尝试设置一个模块级的 forced_update_check_failed。
# application_run_event 的检查在 launch_updater_and_exit 中，如果需要，也应作为参数。
# 但原代码中，它直接使用了全局的。我们将暂时保留这个行为，假设它能访问到。
# 注意：直接访问其他模块的全局变量不是好做法。
# 这个 forced_update_check_failed 是 app_utils.py 自己的一个全局变量，会被 AppOrchestrator 尝试修改。
forced_update_check_failed = False # 默认值

def get_app_dir() -> str:
    """获取应用程序的根目录路径"""
    if getattr(sys, 'frozen', False): # 是否是打包后的 .exe 文件
        application_path = os.path.dirname(sys.executable)
    elif __file__: # 是否是作为 .py 文件运行
        application_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # app/utils -> app -> project_root
    else: # Fallback，不常见
        application_path = os.getcwd()
    return application_path

def write_version_file(logger_instance: Optional[LoggerInterface] = None) -> None:
    """将当前 SCRIPT_VERSION 写入项目根目录下的 version.txt 文件"""
    try:
        # AppConstants.VERSION_FILE 是 "version.txt"
        # get_app_dir() 返回项目根目录
        version_file_path = os.path.join(get_app_dir(), AppConstants.VERSION_FILE)
        with open(version_file_path, "w", encoding="utf-8") as f:
            f.write(SCRIPT_VERSION)
        if logger_instance:
            logger_instance.log(f"版本文件 '{AppConstants.VERSION_FILE}' 已写入版本 {SCRIPT_VERSION} 到路径 {version_file_path}", LogLevel.DEBUG)
    except Exception as e:
        # 如果 logger_instance 还没准备好，直接 print
        err_msg = f"错误：无法写入版本文件 '{AppConstants.VERSION_FILE}' 到路径: {e}"
        if logger_instance:
            logger_instance.log(f"写入版本文件失败: {e}", LogLevel.ERROR)
        else:
            print(f"{Fore.RED}{err_msg}{Style.RESET_ALL}")


def launch_updater_and_exit(logger_instance: LoggerInterface) -> None:
    """启动更新程序并退出当前应用"""
    # 注意：此函数依赖本模块顶部的全局变量 forced_update_check_failed
    # AppOrchestrator 在调用此函数前，会尝试修改这个全局变量的值。
    global forced_update_check_failed # 明确声明使用的是本模块的全局变量

    logger_instance.log("准备启动更新程序...", LogLevel.INFO)
    # AppConstants.UPDATER_EXE_NAME 是 "updater.exe"
    # get_app_dir() 返回项目根目录
    updater_path = os.path.join(get_app_dir(), AppConstants.UPDATER_EXE_NAME)

    if not os.path.exists(updater_path):
        logger_instance.log(f"错误：更新程序 '{updater_path}' 未找到！无法执行更新。", LogLevel.ERROR)
        print(f"\n{Fore.RED}错误：未找到更新程序 {AppConstants.UPDATER_EXE_NAME}。请确保它与主程序在同一目录下。\n无法继续执行更新。{Style.RESET_ALL}")
        if forced_update_check_failed: # 如果是强制更新场景下找不到更新器
            print(f"{Fore.RED}由于强制更新失败且找不到更新程序，程序将退出。{Style.RESET_ALL}")
            sys.exit(1) # 强制退出
        return # 非强制场景，找不到更新器则不执行更新，函数返回

    try:
        logger_instance.log(f"正在启动更新程序: {updater_path}", LogLevel.INFO)
        print(f"\n{Fore.CYAN}正在启动更新程序，主程序即将退出...{Style.RESET_ALL}")

        # 启动更新程序
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen([updater_path], cwd=get_app_dir(), creationflags=DETACHED_PROCESS, close_fds=True)
        else: # macOS / Linux
            subprocess.Popen([updater_path], cwd=get_app_dir(), start_new_session=True)

        logger_instance.log("主程序将在启动更新程序后退出，以便进行更新。", LogLevel.INFO)

        # 通知 AppOrchestrator 或其他主控流程来清理 application_run_event
        # 这里直接 sys.exit(0) 是因为更新器已启动，本程序使命完成。
        # 如果 AppOrchestrator 需要做更多清理，那么这里应该通过某种方式通知它。
        # 但原设计似乎是直接退出。
        # 为了安全，我们假设如果 application_run_event 能被访问到，就清除它。
        # 更好的方式是 launch_updater_and_exit 返回一个状态，由 AppOrchestrator 决定是否退出。
        # 但为了保持与原逻辑的兼容性，这里直接退出。

        # if application_run_event and application_run_event.is_set(): # 尝试访问可能存在的全局事件
        #    application_run_event.clear()

        time.sleep(1) # 给更新程序一点启动时间
        sys.exit(0) # 成功启动更新器后，主程序退出

    except Exception as e:
        logger_instance.log(f"启动更新程序时发生严重错误: {e}", LogLevel.CRITICAL, exc_info=True)
        print(f"\n{Fore.RED}启动更新程序时发生错误: {e}{Style.RESET_ALL}")
        if forced_update_check_failed: # 如果是强制更新场景下启动失败
            print(f"{Fore.RED}由于启动更新程序失败，程序将退出。{Style.RESET_ALL}")
            sys.exit(1) # 强制退出
        # 非强制场景，启动失败则不执行更新，函数隐式返回 None