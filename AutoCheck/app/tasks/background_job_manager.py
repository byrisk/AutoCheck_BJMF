# app/tasks/background_job_manager.py
import threading
import time
import random # 可以用于给后台任务一个小的初始随机延迟
from typing import List, Callable, Tuple, Any # Any 可能不需要

from app.logger_setup import LoggerInterface, LogLevel

class BackgroundJobManager:
    def __init__(self, logger: LoggerInterface, application_run_event: threading.Event): # <--- 确认这里有 application_run_event
        self.logger = logger
        self.application_run_event = application_run_event # 保存事件引用
        self.jobs: List[Tuple[Callable[[], None], int, str]] = []
        self.threads: List[threading.Thread] = []

    def add_job(self, task: Callable[[], None], interval_seconds: int, job_name: str):
        """添加一个后台任务到任务列表。"""
        if interval_seconds <= 0:
            self.logger.log(f"后台任务 '{job_name}' 的间隔时间必须为正数，无法添加。", LogLevel.WARNING)
            return
        self.jobs.append((task, interval_seconds, job_name))
        self.logger.log(f"后台任务 '{job_name}' 已添加到队列 (间隔: {interval_seconds}s)。", LogLevel.DEBUG)


    def _run_job(self, task: Callable[[], None], interval_seconds: int, job_name: str):
        """单个后台任务的执行循环，由单独的线程运行。"""
        self.logger.log(
            f"后台任务 '{job_name}' (间隔: {interval_seconds}s) 线程已启动。",
            LogLevel.DEBUG,
        )
        
        # 可以选择添加一个小的随机初始延迟，避免所有后台任务同时启动
        # time.sleep(random.uniform(0.5, 3.0))

        while self.application_run_event.is_set(): # 使用 self.application_run_event
            try:
                # 在执行任务前再次检查事件状态
                if not self.application_run_event.is_set():
                    self.logger.log(f"后台任务 '{job_name}' 检测到应用停止信号（任务执行前），即将退出。", LogLevel.DEBUG)
                    break
                
                self.logger.log(f"后台任务 '{job_name}': 准备执行...", LogLevel.DEBUG)
                task() # 执行实际任务
                self.logger.log(f"后台任务 '{job_name}': 本轮执行完毕。", LogLevel.DEBUG)

            except Exception as e:
                self.logger.log(f"后台任务 '{job_name}' 在执行时发生错误: {e}", LogLevel.ERROR, exc_info=True)

            # 等待下一个执行周期
            # self.logger.log(f"后台任务 '{job_name}' 将在 {interval_seconds} 秒后再次执行。", LogLevel.DEBUG) # 这条日志可能过于频繁
            for i in range(interval_seconds):
                if not self.application_run_event.is_set(): # 在等待的每一秒都检查事件
                    self.logger.log(f"后台任务 '{job_name}' 在等待期间检测到应用停止信号，即将退出。", LogLevel.DEBUG)
                    break # 跳出等待循环
                time.sleep(1)
            
            if not self.application_run_event.is_set(): # 再次检查，确保能跳出主 while 循环
                 break

        self.logger.log(
            f"后台任务 '{job_name}' 线程已停止。", LogLevel.INFO # 线程停止是INFO级别
        )

    def start_jobs(self):
        """启动所有已添加的后台任务，每个任务在自己的线程中运行。"""
        if not self.jobs:
            self.logger.log("没有已配置的后台任务需要启动。", LogLevel.INFO)
            return
        
        if not self.application_run_event.is_set():
            self.logger.log("应用程序未处于运行状态，无法启动后台任务。", LogLevel.WARNING)
            return

        self.threads = [] # 清空旧的线程列表（如果允许重复调用start_jobs的话）
        for task, interval, name in self.jobs:
            thread = threading.Thread(
                target=self._run_job, args=(task, interval, name), daemon=True
            )
            self.threads.append(thread)
            try:
                thread.start()
            except RuntimeError as e: # 例如，如果线程已启动
                self.logger.log(f"启动后台任务线程 '{name}' 失败: {e}", LogLevel.ERROR)

        if self.threads:
             self.logger.log(f"{len(self.threads)} 个后台任务线程已成功启动。", LogLevel.INFO)
        else:
             self.logger.log("没有后台任务线程被成功启动。", LogLevel.WARNING)


    def stop_jobs(self):
        """
        请求停止所有后台任务。
        主要是通过清除 application_run_event 来实现。
        由于线程是daemon，它们会随主程序退出。
        这个方法主要用于显式地记录停止意图和清理。
        """
        self.logger.log("AppOrchestrator 请求停止所有后台任务...", LogLevel.INFO)
        if self.application_run_event.is_set():
            self.application_run_event.clear() # 这是主要的停止机制
        
        # daemon线程不需要显式join来让主程序退出，但如果想确保它们完成当前循环（如果它们不检查event那么频繁）
        # 或者想记录它们确实退出了，可以join一下。
        # for thread in self.threads:
        #     if thread.is_alive():
        #         self.logger.log(f"等待后台线程 {thread.name} 结束...", LogLevel.DEBUG)
        #         thread.join(timeout=2.0) # 给2秒钟结束
        #         if thread.is_alive():
        #             self.logger.log(f"后台线程 {thread.name} 在超时后仍未结束。", LogLevel.WARNING)
        
        self.logger.log("所有后台任务已被通知停止。", LogLevel.INFO)
        self.jobs = [] # 可以选择清空任务列表
        self.threads = [] # 清空线程引用