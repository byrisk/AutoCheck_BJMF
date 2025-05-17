# app/config/manager.py
from typing import Dict, Any, Optional # Optional 用于类型提示
from pydantic import ValidationError

# 从本包的 models 模块导入 ConfigModel
from .models import ConfigModel
# 从本包的 storage 模块导入 ConfigStorageInterface
from .storage import ConfigStorageInterface
# 从 app.constants 导入 AppConstants (用于默认值和 REQUIRED_FIELDS)
from app.constants import AppConstants
# 从 app.logger_setup 导入 LoggerInterface 和 LogLevel (为了类型提示和日志记录)
from app.logger_setup import LoggerInterface, LogLevel
class ConfigManager:
    def __init__(self, storage: ConfigStorageInterface, logger: LoggerInterface):
        self.storage = storage
        self.logger = logger
        self._config = self._load_config()

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        self._config = value

    def _load_config(self) -> Dict[str, Any]:
        try:
            raw_config = self.storage.load()
            defaults = {
                "time": AppConstants.DEFAULT_SEARCH_INTERVAL,
                "remark": "自动签到配置",
                "enable_time_range": AppConstants.DEFAULT_RUN_TIME["enable_time_range"],
                "start_time": AppConstants.DEFAULT_RUN_TIME["start_time"],
                "end_time": AppConstants.DEFAULT_RUN_TIME["end_time"],
                "pushplus": "",
            }

            # Ensure all required fields exist before validation, even if empty
            for req_field in AppConstants.REQUIRED_FIELDS:
                if req_field not in raw_config:
                    raw_config[req_field] = (
                        "" # Provide empty string for missing required fields to allow Pydantic to catch it
                    )

            config_with_defaults = {**defaults, **raw_config}

            # Validate required fields are not empty after defaults
            missing_fields = [
                field
                for field in AppConstants.REQUIRED_FIELDS
                if not config_with_defaults.get(field)
            ]

            if missing_fields:
                # This case is for when file exists but fields are empty.
                # If file doesn't exist, FileNotFoundError is caught below.
                self.logger.log(
                    f"配置文件缺少必填字段: {', '.join(missing_fields)}. 请运行配置向导。",
                    LogLevel.ERROR,
                )
                return {} # Signal to run config wizard

            return ConfigModel(**config_with_defaults).model_dump()
        except FileNotFoundError:
            self.logger.log(
                f"配置文件 {self.storage.config_path if hasattr(self.storage, 'config_path') else 'data.json'} 未找到。将创建默认配置并提示用户。",
                LogLevel.WARNING,
            )
            # Don't save defaults here, let ConfigUpdater handle first run
            return {} # Return empty to trigger wizard
        except (
            ValueError,
            ValidationError,
        ) as e: # Catch Pydantic validation errors too
            self._handle_validation_error(
                e if isinstance(e, ValidationError) else None, str(e)
            )
            return {} # Return empty to trigger wizard

    def _handle_validation_error(
        self, error: Optional[ValidationError], message: Optional[str] = None
    ) -> None:
        if error:
            error_messages = [
                f"{err['loc'][0]}: {err['msg']}" for err in error.errors()
            ]
            self.logger.log(
                "本地配置验证失败:\n" + "\n".join(error_messages), LogLevel.ERROR
            )
        elif message:
            self.logger.log(f"本地配置加载错误: {message}", LogLevel.ERROR)

    def save(self) -> None:
        try:
            # Re-validate before saving
            ConfigModel(**self._config)
            self.storage.save(self._config)
            self.logger.log("本地配置保存成功。", LogLevel.INFO)
        except (ValueError, ValidationError) as e:
            self._handle_validation_error(
                e if isinstance(e, ValidationError) else None, str(e)
            )
            self.logger.log(f"保存配置时验证失败，未保存。", LogLevel.ERROR)

