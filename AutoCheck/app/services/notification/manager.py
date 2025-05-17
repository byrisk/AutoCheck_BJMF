# app/services/notification/manager.py
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.logger_setup import LoggerInterface, LogLevel
# K8nInternalMessageConfig 现在只包含 enabled
from app.config.models import NotificationSettings
from .interface import NotifierInterface
from .pushplus_notifier import PushPlusNotifier
from .k8n_internal_notifier import K8nInternalMessageNotifier

class NotificationManager:
    def __init__(self, app_config_dict: Dict[str, Any], logger: LoggerInterface, app_name: str = "AutoCheckApp"):
        self.logger = logger
        self.notifiers: List[NotifierInterface] = []
        self.app_name = app_name
        self.app_config_dict = app_config_dict
        self.notification_settings_obj: NotificationSettings
        try:
            self.notification_settings_obj = NotificationSettings(**app_config_dict.get("notifications", {}))
        except Exception as e_parse_notif_settings:
            self.logger.log(f"NotificationManager: 解析通知配置时出错: {e_parse_notif_settings}。将使用默认空设置。", LogLevel.ERROR)
            self.notification_settings_obj = NotificationSettings()

        # PushPlus 初始化 (保持不变)
        if self.notification_settings_obj.pushplus and self.notification_settings_obj.pushplus.enabled:
            if self.notification_settings_obj.pushplus.token:
                try:
                    pushplus_notifier = PushPlusNotifier(
                        token=self.notification_settings_obj.pushplus.token,
                        logger=self.logger,
                        app_name=self.app_name
                    )
                    self.notifiers.append(pushplus_notifier)
                    self.logger.log("NotificationManager: PushPlus 通知器已启用并初始化。", LogLevel.INFO)
                except Exception as e_pushplus_init:
                    self.logger.log(f"NotificationManager: 初始化 PushPlusNotifier 失败: {e_pushplus_init}", LogLevel.ERROR, exc_info=True)
            else:
                self.logger.log("NotificationManager: PushPlus 已启用但 Token 未配置，未初始化。", LogLevel.WARNING)
        else:
            self.logger.log("NotificationManager: PushPlus 通知未启用或配置块不存在。", LogLevel.DEBUG)

        # K8N 内部消息通知器 初始化 (保持不变)
        # K8nInternalMessageConfig 现在只控制 enabled
        k8n_config = self.notification_settings_obj.k8n_internal
        if k8n_config and k8n_config.enabled:
            student_uid = self.app_config_dict.get("student_uid")
            student_name = self.app_config_dict.get("student_name")
            cookie = self.app_config_dict.get("cookie")
            if student_uid and cookie:
                try:
                    k8n_notifier = K8nInternalMessageNotifier(
                        student_uid=student_uid,
                        student_name=student_name,
                        cookie=cookie,
                        logger=self.logger,
                        app_name=self.app_name
                    )
                    self.notifiers.append(k8n_notifier)
                    self.logger.log("NotificationManager: K8N内部消息通知器已启用并初始化。", LogLevel.INFO)
                except Exception as e_k8n_init:
                    self.logger.log(f"NotificationManager: 初始化 K8nInternalMessageNotifier 失败: {e_k8n_init}", LogLevel.ERROR, exc_info=True)
            else:
                missing_reason = ""
                if not student_uid: missing_reason += "student_uid 未配置"
                if not cookie: missing_reason += ("; " if missing_reason else "") + "cookie 未配置"
                self.logger.log(f"NotificationManager: K8N内部消息通知已启用但依赖项缺失 ({missing_reason})，无法初始化。", LogLevel.WARNING)
        else:
            self.logger.log("NotificationManager: K8N内部消息通知未启用或配置块不存在。", LogLevel.DEBUG)

        if not self.notifiers:
            self.logger.log("NotificationManager: 没有启用任何通知器。", LogLevel.INFO)
        else:
            self.logger.log(f"NotificationManager: 共初始化了 {len(self.notifiers)} 个通知器。", LogLevel.INFO)

    def dispatch(self, title: str, content: str, event_type: str = "general", **kwargs: Any) -> None:
        if not self.notifiers:
            return

        self.logger.log(f"NotificationManager: 准备分发 '{event_type}' 类型通知 (通用标题: {title[:30]}...)", LogLevel.DEBUG)
        dispatch_successful_count = 0
        for notifier in self.notifiers:
            try:
                if isinstance(notifier, K8nInternalMessageNotifier):
                    # +++ 直接在此处定义固定的模板字符串 +++
                    # 您可以根据需要调整这些固定的模板
                    # 根据您成功测试脚本的 payload，k8n.cn 可能期望 title 和 content 为 "1"
                    # 如果您希望发送 "1"，则设置：
                    # FIXED_K8N_TITLE_TEMPLATE = "1"
                    # FIXED_K8N_CONTENT_TEMPLATE = "1"
                    # 或者，一个更友好的固定模板：
                    FIXED_K8N_TITLE_TEMPLATE = "【{app_name}】签到: {status_message}"
                    FIXED_K8N_CONTENT_TEMPLATE = (
                        "课程: {course_name} (ID: {course_id})\n"
                        "任务: {sign_id}\n"
                        "时间: {timestamp}\n"
                        "状态: {status_message}\n"
                        "设备: {remark}\n"
                        "原始消息: {raw_response_excerpt}"
                    )
                    # +++ 模板定义结束 +++
                    
                    template_data = {
                        "app_name": self.app_name,
                        "remark": self.app_config_dict.get("remark", "N/A"),
                        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "status_message": kwargs.get("status_message_k8n", "状态未知"),
                        "course_name": kwargs.get("course_name", "未知课程"),
                        "course_id": kwargs.get("course_id", "N/A"),
                        "sign_id": kwargs.get("sign_id", "N/A"),
                        # "original_title": title, # 如果模板中需要，可以取消注释
                        "raw_response_excerpt": kwargs.get("raw_response_excerpt_k8n", "无详细响应")
                    }

                    final_k8n_title = FIXED_K8N_TITLE_TEMPLATE # 默认使用模板原文
                    final_k8n_content = FIXED_K8N_CONTENT_TEMPLATE # 默认使用模板原文
                    try:
                        final_k8n_title = FIXED_K8N_TITLE_TEMPLATE.format(**template_data)
                        final_k8n_content = FIXED_K8N_CONTENT_TEMPLATE.format(**template_data)
                    except KeyError as e_fmt:
                        self.logger.log(f"NotificationManager: 格式化 K8N 固定通知模板时键错误: {e_fmt}。将使用原始固定模板或通用标题/内容。", LogLevel.WARNING)
                        # 回退逻辑：如果固定模板的占位符有问题，可以发送简化的消息
                        final_k8n_title = f"【{self.app_name}】通知"
                        final_k8n_content = f"状态: {template_data['status_message']}, 课程: {template_data['course_name']}"
                    except Exception as e_template:
                        self.logger.log(f"NotificationManager: 处理 K8N 固定通知模板时出错: {e_template}。将使用原始固定模板或通用标题/内容。", LogLevel.ERROR)
                        final_k8n_title = f"【{self.app_name}】通知"
                        final_k8n_content = f"状态: {template_data['status_message']}, 课程: {template_data['course_name']}"
                    
                    # 将格式化后的 title 和 content 传递给 notifier
                    # K8nInternalMessageNotifier 的 payload 中 title 和 content 参数会使用这里的值
                    if notifier.send(final_k8n_title, final_k8n_content, **kwargs):
                        dispatch_successful_count +=1
                
                else: # 其他通知器 (例如 PushPlus)
                    # 对于 PushPlus 等，仍然使用传递给 dispatch 的原始 title 和 content
                    if notifier.send(title, content, event_type=event_type, **kwargs):
                        dispatch_successful_count +=1
            except Exception as e_dispatch:
                notifier_name = notifier.__class__.__name__
                self.logger.log(f"NotificationManager: 调用 {notifier_name}.send() 时发生错误: {e_dispatch}", LogLevel.ERROR, exc_info=True)

        if dispatch_successful_count > 0:
             self.logger.log(f"NotificationManager: 通知已成功尝试分发给 {dispatch_successful_count}/{len(self.notifiers)} 个通知器。", LogLevel.INFO)
        elif self.notifiers:
             self.logger.log(f"NotificationManager: 通知未能成功尝试分发给任何启用的通知器。", LogLevel.WARNING)

    def has_active_notifiers(self) -> bool:
        return bool(self.notifiers)