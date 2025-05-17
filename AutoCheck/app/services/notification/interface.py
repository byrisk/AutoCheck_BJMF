# app/services/notification/interface.py
from abc import ABC, abstractmethod
from typing import Any, Dict # Optional 和 Any 通常一起使用，这里 Any 也可以

class NotifierInterface(ABC):  # <--- 确保类名和继承完全如此
    """通知器接口，所有具体的通知实现都应继承此类。"""

    @abstractmethod
    def send(self, title: str, content: str, **kwargs: Any) -> bool:
        """
        发送通知的核心方法。

        参数:
            title (str): 通知的标题。
            content (str): 通知的主体内容。
            **kwargs (Any): 其他特定于通知器的参数 (例如，邮件的收件人列表，
                            PushPlus 的特定模板参数等)。

        返回:
            bool: True 表示发送尝试成功（不一定代表用户已收到），False 表示发送失败。
        """
        pass