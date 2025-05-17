# app/services/notification/__init__.py
from .interface import NotifierInterface
from .pushplus_notifier import PushPlusNotifier
# +++ 导入 K8nInternalMessageNotifier +++
from .k8n_internal_notifier import K8nInternalMessageNotifier
from .manager import NotificationManager

__all__ = [
    "NotifierInterface",
    "PushPlusNotifier",
    # +++ 添加 K8nInternalMessageNotifier 到 __all__ +++
    "K8nInternalMessageNotifier",
    "NotificationManager",
]