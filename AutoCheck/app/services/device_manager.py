# app/services/device_manager.py
import os
import uuid  # DeviceManager 使用了 uuid
from typing import Optional # 只是为了保持和其他文件一致，如果没用到可以省略

# 从 app.constants 导入 AppConstants (DeviceManager 使用了 AppConstants.DEVICE_ID_FILE)
from app.constants import AppConstants
# 从 app.logger_setup 导入 LoggerInterface 和 LogLevel (为了类型提示和日志记录)
from app.logger_setup import LoggerInterface, LogLevel

class DeviceManager:
    def __init__(
        self, logger: LoggerInterface, device_id_file: str = AppConstants.DEVICE_ID_FILE
    ):
        self.logger = logger
        self.device_id_file = device_id_file
        self.device_id: str = self._load_or_create_device_id()

    def _load_or_create_device_id(self) -> str:
        try:
            if os.path.exists(self.device_id_file):
                with open(self.device_id_file, "r") as f:
                    device_id = f.read().strip()
                if device_id:
                    self.logger.log(f"设备ID加载成功: {device_id}", LogLevel.DEBUG)
                    return device_id
        except IOError as e:
            self.logger.log(f"读取设备ID文件失败: {e}", LogLevel.WARNING)

        device_id = str(uuid.uuid4())
        try:
            with open(self.device_id_file, "w") as f:
                f.write(device_id)
            self.logger.log(f"新设备ID已创建并保存: {device_id}", LogLevel.INFO)
        except IOError as e:
            self.logger.log(
                f"保存新设备ID失败: {e}. 将在内存中使用: {device_id}", LogLevel.ERROR
            )
        return device_id

    def get_id(self) -> str:
        return self.device_id

