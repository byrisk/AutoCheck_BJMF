# app/utils/display_utils.py
import sys # tampilkan_免责声明_并获取用户同意 中用到了 sys
from typing import TYPE_CHECKING # 用于类型提示 ConfigManager，避免循环导入
from colorama import Fore, Style

# 从 app.constants 导入 AppConstants 和 SCRIPT_VERSION
from app.constants import AppConstants, SCRIPT_VERSION
# 从 app.logger_setup 导入 LoggerInterface 和 LogLevel (为了类型提示和日志记录)
from app.logger_setup import LoggerInterface, LogLevel

# 为了避免 display_utils 和 config.manager 之间的直接循环导入
# 我们在这里使用 TYPE_CHECKING 来进行类型提示
if TYPE_CHECKING:
    from app.config.manager import ConfigManager


def tampilkan_info_aplikasi_dasar(logger_instance: LoggerInterface) -> None:
    """仅显示应用的基本信息：名称、版本、作者、项目链接、许可证摘要。"""
    separator_atas = f"{Fore.CYAN}{'=' * 70}{Style.RESET_ALL}"
    separator_bawah = f"{Fore.CYAN}{'-' * 70}{Style.RESET_ALL}"
    info_header = f"{Fore.CYAN}欢迎使用 {AppConstants.APP_NAME} v{SCRIPT_VERSION}{Style.RESET_ALL}"
    author_info = f" {Fore.GREEN}作者: {AppConstants.APP_AUTHOR_NAME}{Style.RESET_ALL}"
    project_link_info = f" {Fore.GREEN}项目地址: {AppConstants.APP_PROJECT_LINK}{Style.RESET_ALL}"
    license_info = f" {Fore.GREEN}开源许可: {AppConstants.APP_LICENSE_INFO_FOR_DISPLAY}{Style.RESET_ALL}"

    pesan_konsol = [
        "\n" + separator_atas,
        info_header,
        author_info,
        project_link_info,
        license_info,
        separator_bawah + "\n",
    ]
    # 使用 logger_instance 来打印到控制台（如果 FileLogger 的 console_level 合适）
    # 或者直接 print
    # 为了保持与原行为一致，这里我们直接 print
    for line in pesan_konsol:
        print(line)

    # 日志记录基本信息
    log_msg = (
        f"应用信息: {AppConstants.APP_NAME} v{SCRIPT_VERSION}, "
        f"作者: {AppConstants.APP_AUTHOR_NAME}, "
        f"项目: {AppConstants.APP_PROJECT_LINK}, "
        f"许可: {AppConstants.APP_LICENSE_TYPE}"
    )
    logger_instance.log(log_msg, LogLevel.INFO)


def tampilkan_免责声明_并获取用户同意(logger_instance: LoggerInterface, config_manager: 'ConfigManager') -> bool:
    """
    分段显示免责声明，并要求用户通过复述特定文字来确认同意。
    如果用户已同意过当前版本的免责声明，则跳过此过程。

    参数:
        logger_instance: 日志记录器实例。
        config_manager: 配置管理器实例，用于读取和保存同意状态。
                        注意：这里使用了前向引用 'ConfigManager' 来避免循环导入。

    返回:
        bool: True 如果用户同意或已同意过，False 如果用户不同意或选择退出。
    """
    current_agreed_version = ""
    if config_manager.config and "disclaimer_agreed_version" in config_manager.config:
        current_agreed_version = config_manager.config.get("disclaimer_agreed_version")

    if current_agreed_version == AppConstants.DISCLAIMER_TEXT_VERSION:
        logger_instance.log(f"用户已同意过版本 {AppConstants.DISCLAIMER_TEXT_VERSION} 的免责声明，跳过显示。", LogLevel.DEBUG)
        return True

    logger_instance.log(f"首次运行或免责声明版本已更新 (当前版本: {AppConstants.DISCLAIMER_TEXT_VERSION}, 已同意版本: {current_agreed_version or '无'})。开始显示免责声明并获取用户同意流程。", LogLevel.INFO)
    print(f"\n{Fore.YELLOW}重要提示：在使用本软件前，您必须仔细阅读并同意以下全部免责声明条款：{Style.RESET_ALL}")

    total_segments = len(AppConstants.APP_DISCLAIMER_SEGMENTS)
    for i, (judul_segmen, isi_segmen) in enumerate(AppConstants.APP_DISCLAIMER_SEGMENTS):
        print(f"\n{Fore.CYAN}{'-' * 70}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}{judul_segmen} (第 {i + 1}/{total_segments} 部分){Style.RESET_ALL}")
        print(f"{Fore.WHITE}{isi_segmen}{Style.RESET_ALL}")

        if i < total_segments - 1:
            try:
                user_input = input(f"\n{Fore.GREEN}请按 Enter键 继续阅读下一部分，或输入 'q'/'quit' 退出并表示不同意：{Style.RESET_ALL}").strip().lower()
                if user_input in ['q', 'quit']:
                    print(f"\n{Fore.RED}您已选择退出。由于未同意免责声明的全部内容，程序无法继续运行。{Style.RESET_ALL}")
                    logger_instance.log("用户在阅读免责声明过程中选择退出。", LogLevel.WARNING)
                    return False
            except KeyboardInterrupt:
                print(f"\n{Fore.RED}操作被用户中断。由于未同意免责声明的全部内容，程序无法继续运行。{Style.RESET_ALL}")
                logger_instance.log("用户通过 Ctrl+C 中断了免责声明阅读过程。", LogLevel.WARNING)
                return False
        else:
            print(f"\n{Fore.CYAN}{'-' * 70}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}您已阅读完所有免责声明条款。{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}为确认您已仔细阅读、完全理解并同意上述所有条款，{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}请输入以下【方括号中】的短语（需完全一致，程序会自动忽略首尾空格和大小写差异）:{Style.RESET_ALL}")
    print(f"{Fore.CYAN}>>> 【{AppConstants.USER_CONFIRMATION_PHRASE}】 <<<")

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            confirmation_input = input(f"{Fore.GREEN}请输入确认短语 (尝试 {attempt + 1}/{max_attempts}): {Style.RESET_ALL}").strip()
            if confirmation_input.lower() == AppConstants.USER_CONFIRMATION_PHRASE.lower():
                if not config_manager.config: # 如果因首次运行等原因 config 为空
                    config_manager.config = {} # 初始化为空字典
                config_manager.config["disclaimer_agreed_version"] = AppConstants.DISCLAIMER_TEXT_VERSION
                try:
                    config_manager.save()
                    logger_instance.log(f"用户已同意免责声明 (版本: {AppConstants.DISCLAIMER_TEXT_VERSION})，同意状态已成功保存至配置文件。", LogLevel.INFO)
                    print(f"{Fore.GREEN}感谢您的确认！您现在可以继续使用本软件。{Style.RESET_ALL}\n")
                    return True
                except Exception as e:
                    logger_instance.log(f"关键错误：保存免责声明同意状态至配置文件时失败: {e}", LogLevel.CRITICAL, exc_info=True)
                    print(f"{Fore.RED}严重错误：无法保存您的同意状态。为确保合规，程序无法继续。请检查配置文件路径及权限。{Style.RESET_ALL}\n")
                    return False
            else:
                if attempt < max_attempts - 1:
                    print(f"{Fore.RED}输入不匹配。请确保输入与【方括号中】提示的短语完全一致。{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}输入多次错误。{Style.RESET_ALL}")
        except KeyboardInterrupt:
            print(f"\n{Fore.RED}操作被用户中断。由于未同意免责声明，程序无法继续运行。{Style.RESET_ALL}")
            logger_instance.log("用户在输入确认短语时通过 Ctrl+C 中断操作。", LogLevel.WARNING)
            return False

    print(f"\n{Fore.RED}由于未能确认同意免责声明的全部内容，程序即将退出。{Style.RESET_ALL}")
    logger_instance.log("用户未能成功输入确认短语以同意免责声明，程序终止。", LogLevel.ERROR)
    return False