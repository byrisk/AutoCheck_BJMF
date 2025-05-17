# app/exceptions.py

class ConfigError(Exception):
    """自定义配置错误异常"""
    pass

class LocationError(Exception):
    """自定义位置服务相关错误异常"""
    pass

class ServiceAccessError(Exception):  # <--- 确保这个类存在且名称完全匹配
    """用于远程服务访问控制相关的错误，例如全局禁用或设备禁用"""
    pass

class UpdateRequiredError(Exception): # <--- AppOrchestrator 也导入了这个
    """用于强制更新相关的错误"""
    def __init__(self, message, required_version=None, current_version=None, reason=None):
        super().__init__(message)
        self.required_version = required_version
        self.current_version = current_version
        self.reason = reason