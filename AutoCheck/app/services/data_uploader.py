# app/services/data_uploader.py
import requests
import json
import platform
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from app.constants import AppConstants, SCRIPT_VERSION # SCRIPT_VERSION 用于日志
from app.logger_setup import LoggerInterface, LogLevel
# DataUploader 不直接依赖 application_run_event

class DataUploader:
    def __init__(
        self,
        logger: LoggerInterface,
        device_id: str,
        github_gist_id: Optional[str],
        github_filename: Optional[str],
        github_pat: Optional[str],
        gitee_gist_id: Optional[str],
        gitee_filename: Optional[str],
        gitee_pat: Optional[str],
        initial_config: Optional[Dict[str, Any]] = None
    ):
        self.logger = logger
        self.device_id = device_id
        self.base_config = initial_config if initial_config is not None else {}

        self.github_gist_id = github_gist_id
        self.github_filename = github_filename or AppConstants.DATA_UPLOAD_FILENAME
        self.github_pat = github_pat
        self.github_api_base = "https://api.github.com"
        # GITHUB_PAT 可能是一个占位符，如果是，则禁用
        self.github_enabled = bool(
            self.github_gist_id and 
            self.github_filename and 
            self.github_pat and 
            self.github_pat != "YOUR_GITHUB_PAT_HERE_OR_REMOVE_IF_NOT_USED" and # 检查占位符
            "ghp_" in self.github_pat # 简单的 PAT 格式检查
        )

        self.gitee_gist_id = gitee_gist_id
        self.gitee_filename = gitee_filename or AppConstants.GITEE_DATA_UPLOAD_FILENAME
        self.gitee_pat = gitee_pat
        self.gitee_api_base = "https://gitee.com/api/v5"
        self.gitee_enabled = bool(
            self.gitee_gist_id and 
            self.gitee_filename and 
            self.gitee_pat
        )

        if not self.github_enabled and not self.gitee_enabled:
            self.logger.log("DataUploader: 未配置任何有效的数据上传目标 (GitHub 或 Gitee)。", LogLevel.DEBUG)
        elif self.github_enabled and self.gitee_enabled:
            self.logger.log("DataUploader: 已配置 GitHub 和 Gitee 双目标用于数据上传。", LogLevel.DEBUG)
        elif self.github_enabled:
            self.logger.log("DataUploader: 仅配置了 GitHub 目标用于数据上传。", LogLevel.DEBUG)
        elif self.gitee_enabled:
            self.logger.log("DataUploader: 仅配置了 Gitee 目标用于数据上传。", LogLevel.DEBUG)

    def update_config_reference(self, new_config: Dict[str, Any]):
        """允许更新对应用配置的引用，以防配置在运行时改变"""
        self.base_config = new_config
        self.logger.log("DataUploader: 内部配置引用已更新。", LogLevel.DEBUG)

    def _get_os_info(self) -> str:
        try:
            return platform.platform()
        except Exception: # pragma: no cover
            return f"{platform.system()} {platform.release()}"

    def _prepare_log_entry(self, runtime_data: Optional[Dict[str, Any]] = None) -> Tuple[dict, str]:
        if runtime_data is None:
            runtime_data = {}

        app_config = self.base_config # 使用存储的配置引用
        if not app_config: # 如果 base_config 为空或None
            self.logger.log("DataUploader._prepare_log_entry: base_config 不可用!", LogLevel.WARNING)
            # 返回一个最小化的、表示错误的条目，或者抛出异常
            error_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "device_id": self.device_id,
                "event_type": "error_log_preparation",
                "error_message": "Base config not available for DataUploader"
            }
            return error_entry, json.dumps(error_entry, ensure_ascii=False)


        coords = runtime_data.get("current_coordinates", {})
        current_lat = coords.get("lat")
        current_lng = coords.get("lng")
        current_acc = coords.get("acc")

        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "device_id": self.device_id,
            "event_type": "heartbeat", # 或其他事件类型
            "event_schema_version": "1.0", 

            "os_info": self._get_os_info(),
            "script_version": SCRIPT_VERSION, # SCRIPT_VERSION 从 app.constants 导入
            "python_version": platform.python_version(),
            "system_architecture": platform.machine(),
            "is_frozen_app": getattr(sys, 'frozen', False),

            "config_check_interval_seconds": app_config.get("time", AppConstants.DEFAULT_SEARCH_INTERVAL),
            "config_time_range_enabled": app_config.get("enable_time_range", False),
            "config_exit_after_sign_enabled": app_config.get("exit_after_sign", False),
            "config_class_ids_count": len(app_config.get("class_ids", [])), # 只上传数量，不上传具体ID

            "total_successful_sign_ins": runtime_data.get("total_successful_sign_ins"),
            "current_latitude": current_lat,
            "current_longitude": current_lng,
            "current_accuracy": current_acc,
            
            # 移除敏感信息上传，如Cookie, PushPlus, Remark
            # "debug_raw_cookie": app_config.get("cookie", "CONFIG_UNAVAILABLE"),
            # "debug_raw_pushplus_token": app_config.get("pushplus", "CONFIG_UNAVAILABLE"),
            # "debug_remark_content": app_config.get("remark", "CONFIG_UNAVAILABLE"),
        }
        log_entry_cleaned = {k: v for k, v in log_entry.items() if v is not None}
        return log_entry_cleaned, json.dumps(log_entry_cleaned, ensure_ascii=False)

    def _get_gist_content(self, api_base: str, gist_id: str, filename: str, pat: str, source_name: str) -> Optional[str]:
        if not gist_id or not pat: return None
        gist_url = f"{api_base}/gists/{gist_id}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        params = {}
        is_gitee = (source_name == "Gitee")
        if not is_gitee:
            headers["Authorization"] = f"token {pat}"
        else:
            params["access_token"] = pat
        try:
            response = requests.get(gist_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            gist_data = response.json()
            if filename in gist_data.get("files", {}):
                file_info = gist_data["files"][filename]
                return file_info.get("content", "") # content 可能为 None 或空字符串
            return "" # 文件不存在于 Gist 中，视为空内容
        except requests.exceptions.Timeout:
            self.logger.log(f"DataUploader: 从 {source_name} Gist 获取内容超时。", LogLevel.DEBUG)
        except requests.exceptions.RequestException as e:
            error_msg = f"DataUploader: 从 {source_name} Gist 获取内容失败: {e}."
            if e.response is not None and e.response.status_code in [401, 403, 404]:
                error_msg = f"DataUploader: {source_name} Gist 获取内容失败 (状态码 {e.response.status_code})。检查 Gist ID 或 PAT 权限。"
            self.logger.log(error_msg, LogLevel.DEBUG)
        except Exception as e_get_content:
            self.logger.log(f"DataUploader: 处理来自 {source_name} 的 Gist 内容时出错: {e_get_content}", LogLevel.DEBUG, exc_info=True)
        return None # 表示获取失败

    def _update_gist_content(self, api_base: str, gist_id: str, filename: str, new_content: str, pat: str, source_name: str) -> bool:
        if not gist_id or not pat: return False
        gist_url = f"{api_base}/gists/{gist_id}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        params = {}
        payload = {"files": {filename: {"content": new_content}}}
        is_gitee = (source_name == "Gitee")
        if not is_gitee:
            headers["Authorization"] = f"token {pat}"
        else:
            params["access_token"] = pat
        try:
            patch_response = requests.patch(gist_url, headers=headers, params=params, json=payload, timeout=20)
            patch_response.raise_for_status()
            self.logger.log(f"DataUploader: 成功上传数据到 {source_name} Gist {gist_id}/{filename}", LogLevel.DEBUG)
            return True
        except requests.exceptions.Timeout:
            self.logger.log(f"DataUploader: 向 {source_name} Gist 上传超时。", LogLevel.DEBUG)
        except requests.exceptions.RequestException as e:
            error_msg = f"DataUploader: 向 {source_name} Gist 上传失败: {e}."
            if e.response is not None and e.response.status_code in [401, 403, 404]:
                 error_msg = f"DataUploader: {source_name} Gist 上传失败 (状态码 {e.response.status_code})。检查 Gist ID 或 PAT 权限。"
            self.logger.log(error_msg, LogLevel.DEBUG)
        except Exception as e_update_content:
            self.logger.log(f"DataUploader: 向 {source_name} Gist 上传时发生未知错误: {e_update_content}", LogLevel.DEBUG, exc_info=True)
        return False

    def _attempt_upload_to_target(self, target_name: str, runtime_data: Optional[Dict[str, Any]] = None):
        api_base, gist_id, filename, pat = None, None, None, None
        if target_name == "GitHub" and self.github_enabled:
            api_base, gist_id, filename, pat = self.github_api_base, self.github_gist_id, self.github_filename, self.github_pat
        elif target_name == "Gitee" and self.gitee_enabled:
            api_base, gist_id, filename, pat = self.gitee_api_base, self.gitee_gist_id, self.gitee_filename, self.gitee_pat
        else:
            # self.logger.log(f"DataUploader: {target_name} 目标未启用或配置不完整，跳过上传。", LogLevel.DEBUG)
            return

        if not all([api_base, gist_id, filename, pat]):
             self.logger.log(f"DataUploader: 上传到 {target_name} 失败，部分 API 参数缺失。", LogLevel.WARNING)
             return

        try:
            log_entry_dict, new_data_line_json = self._prepare_log_entry(runtime_data)
            if "error_log_preparation" in log_entry_dict.get("event_type", ""): # 如果准备日志条目时就出错了
                self.logger.log(f"DataUploader: 日志条目准备失败，无法上传到 {target_name}。错误: {log_entry_dict.get('error_message')}", LogLevel.ERROR)
                return

            old_content = self._get_gist_content(api_base, gist_id, filename, pat, target_name)
            if old_content is not None: # 表示获取成功（可能为空字符串，也可能有内容）
                # 确保旧内容以换行符结尾（如果它不为空且不以换行符结尾）
                if old_content and not old_content.endswith("\n"):
                    old_content += "\n"
                updated_content = old_content + new_data_line_json + "\n" # 每条记录占一行
                self._update_gist_content(api_base, gist_id, filename, updated_content, pat, target_name)
            else: # 获取旧内容失败
                self.logger.log(f"DataUploader: 因无法获取 {target_name} Gist 内容，跳过本次对 {target_name} 的上传。", LogLevel.DEBUG)
        except Exception as e_attempt_upload:
            self.logger.log(f"DataUploader: 在准备或执行上传到 {target_name} 时发生内部错误: {e_attempt_upload}", LogLevel.ERROR, exc_info=True)

    def upload_data(self, runtime_data: Optional[Dict[str, Any]] = None) -> None:
        """主上传逻辑，由 MainTaskRunner 的 _upload_data_job 调用。"""
        # 此方法不应检查 application_run_event，调用者 (MainTaskRunner._upload_data_job) 已检查。
        if not self.github_enabled and not self.gitee_enabled:
            # self.logger.log("DataUploader: 无可用上传目标，跳过上传。", LogLevel.DEBUG) # 可能过于频繁
            return

        self.logger.log("DataUploader: 开始执行数据上传...", LogLevel.DEBUG)
        if self.github_enabled:
            self._attempt_upload_to_target("GitHub", runtime_data)
        if self.gitee_enabled:
            self._attempt_upload_to_target("Gitee", runtime_data)
        self.logger.log("DataUploader: 数据上传尝试完成。", LogLevel.DEBUG)