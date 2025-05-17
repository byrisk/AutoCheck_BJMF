# main.py
import sys
import os

# --- 确保 app 包可以被正确导入 ---
# 如果 main.py 和 app/ 文件夹在同一个根目录下，
# Python 通常能自动找到 app 包。
# 但为了更稳健，尤其是在不同环境或打包时，可以显式地将项目根目录添加到 sys.path。
# 获取 main.py 文件所在的目录的绝对路径，即项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# ------------------------------------

from app.app_orchestrator import AppOrchestrator

def run_application():
    """
    创建并运行应用编排器。
    """
    orchestrator = AppOrchestrator()
    exit_code = orchestrator.run() # AppOrchestrator.run() 方法应返回最终的退出码
    sys.exit(exit_code)

if __name__ == "__main__":
    # 在这里可以添加任何在 AppOrchestrator 初始化前就需要执行的、非常底层的设置，
    # 但目前我们的 AppOrchestrator 已经处理了大部分初始化。

    # 例如，如果 colorama 需要在非常早期初始化 (尽管我们的 logger_setup 中有做)
    # import colorama
    # colorama.init(autoreset=True)

    run_application()