# autocheckf/app/config/models.py
import re
from typing import Dict, List, Optional, Any, Tuple, TypedDict
from datetime import datetime
from pydantic import BaseModel, field_validator, ValidationError, Field

from app.constants import AppConstants

# --- Notification Config Models ---
class PushPlusConfig(BaseModel):
    enabled: bool = False
    token: str = ""

class NotificationSettings(BaseModel):
    pushplus: PushPlusConfig = Field(default_factory=PushPlusConfig)

# --- School Data TypedDicts ---
class HotSpotData(TypedDict):
    name: str
    lat: float
    lng: float
    accuracy: float 
    weight: int

class SelectedSchoolData(TypedDict):
    id: str      
    addr: str
    range: List[float] 
    hot_spots: Optional[List[HotSpotData]]

# --- User Info TypedDict ---
class UserInfo(TypedDict, total=False): # total=False as uid/uname might be optional initially
    uid: Optional[str]
    uname: Optional[str]

# --- Main Config Model ---
class ConfigModel(BaseModel):
    # Core credentials & settings
    cookie: str
    class_ids: List[str] 
    user_info: Optional[UserInfo] = None # NEW: To store uid and uname

    # Location info
    lat: str
    lng: str
    acc: str

    # Other general settings
    time: int = AppConstants.DEFAULT_SEARCH_INTERVAL
    remark: str = "自动签到配置"
    enable_time_range: bool = AppConstants.DEFAULT_RUN_TIME["enable_time_range"]
    start_time: str = AppConstants.DEFAULT_RUN_TIME["start_time"]
    end_time: str = AppConstants.DEFAULT_RUN_TIME["end_time"]
    exit_after_sign: bool = False
    exit_after_sign_mode: str = AppConstants.DEFAULT_EXIT_AFTER_SIGN_MODE
    
    # School related automation settings
    selected_school: Optional[SelectedSchoolData] = None
    enable_school_based_randomization: bool = False
    total_successful_sign_ins: int = 0 

    # Disclaimer agreed version
    disclaimer_agreed_version: Optional[str] = None

    # Notification settings
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    
    # Runtime only, not saved to JSON (Pydantic handles this with exclude=True)
    all_fetched_class_details: Optional[List[Dict[str,str]]] = Field(default_factory=list, exclude=True)


    # --- Validators ---
    @field_validator("class_ids")
    @classmethod
    def validate_class_ids(cls, v: List[str]) -> List[str]:
        if not v: raise ValueError("班级ID列表不能为空")
        for item_id in v:
            if not str(item_id).strip(): raise ValueError("班级ID列表中不能包含空ID")
            if not str(item_id).isdigit(): raise ValueError(f"班级ID '{item_id}' 必须为纯数字")
        if len(set(v)) != len(v): raise ValueError("班级ID列表中不能包含重复的ID")
        return v

    @field_validator("lat")
    @classmethod
    def validate_latitude(cls, v: str) -> str:
        if not v: raise ValueError("纬度不能为空")
        try:
            lat_float = float(v)
            if not -90 <= lat_float <= 90: raise ValueError("纬度需在 -90 到 90 之间")
        except ValueError: raise ValueError("纬度必须是有效数字") from None
        return v

    @field_validator("lng")
    @classmethod
    def validate_longitude(cls, v: str) -> str:
        if not v: raise ValueError("经度不能为空")
        try:
            lng_float = float(v)
            if not -180 <= lng_float <= 180: raise ValueError("经度需在 -180 到 180 之间")
        except ValueError: raise ValueError("经度必须是有效数字") from None
        return v

    @field_validator("acc")
    @classmethod
    def validate_accuracy(cls, v: str) -> str:
        if not v: raise ValueError("精度不能为空")
        try:
            acc_float = float(v)
            if acc_float <= 0: raise ValueError("精度必须是正数")
        except ValueError: raise ValueError("精度必须是有效数字") from None
        return v

    @field_validator("cookie")
    @classmethod
    def validate_cookie(cls, v: str) -> str:
        if not v: raise ValueError("Cookie 不能为空")
        if AppConstants.COOKIE_PATTERN and not re.search(AppConstants.COOKIE_PATTERN, v):
            raise ValueError("Cookie 格式不正确或缺少关键字段 (如 remember_student_...)")
        return v

    @field_validator("time")
    @classmethod
    def validate_search_time(cls, v: Any) -> int:
        v_int: int
        if isinstance(v, str):
            if not v.isdigit(): raise ValueError("检索间隔必须为有效的整数（字符串形式）")
            try: v_int = int(v)
            except ValueError: raise ValueError("检索间隔必须为有效的整数") from None
        elif isinstance(v, int): v_int = v
        else: raise TypeError("检索间隔类型无效，应为整数或数字字符串")
        if v_int <= 0: raise ValueError("检索间隔必须为正整数")
        return v_int

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError: raise ValueError("时间格式必须为 HH:MM") from None

    @field_validator("exit_after_sign_mode")
    @classmethod
    def validate_exit_mode(cls, v: str) -> str:
        if v not in ["any", "all"]:
            raise ValueError("签到后退出模式必须是 'any' 或 'all'")
        return v
        
    @field_validator("user_info", mode="before") # Allow None or dict
    @classmethod
    def validate_user_info(cls, v: Any) -> Optional[Dict[str, str]]:
        if v is None:
            return None
        if isinstance(v, dict):
            # You could add more specific validation for uid and uname if needed
            # For example, ensuring they are strings if present.
            # For now, just ensure it's a dict if not None.
            return v
        raise ValueError("user_info 必须是字典或None")