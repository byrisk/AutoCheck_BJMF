# app/constants.py
import os
from typing import Dict, List, Set, Optional, Callable, Any, Tuple # AppConstants 类定义中用到了这些类型提示

# === Application Version ===
SCRIPT_VERSION = "1.0.0"  # Used for forced update checks

# === Constants Definition ===
class AppConstants:
    REQUIRED_FIELDS: Tuple[str, ...] = ("cookie", "class_ids", "lat", "lng", "acc")
    COOKIE_PATTERN: str = (
        r"remember_student_59ba36addc2b2f9401580f014c7f58ea4e30989d=[^;]+"
    )
    LOG_DIR: str = "logs" # 日志目录，相对于项目根目录
    CONFIG_FILE: str = "data.json" # 主配置文件名，相对于项目根目录
    DEVICE_ID_FILE: str = "device_id.txt"  # Stores unique device ID, 相对于项目根目录
    DEFAULT_SEARCH_INTERVAL: int = 60
    USER_AGENT_TEMPLATE: str = (
        "Mozilla/5.0 (Linux; Android {android_version}; {device} Build/{build_number}; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_version} Mobile Safari/537.36 "
        "MicroMessenger/{wechat_version} NetType/{net_type} Language/zh_CN"
    )
    DEFAULT_RUN_TIME = {
        "enable_time_range": False,
        "start_time": "08:00",
        "end_time": "22:00",
    }

    # Remote Configuration Gist URLs
    PRIMARY_REMOTE_CONFIG_URL: Optional[str] = (
        "https://raw.githubusercontent.com/byrisk/AutoCheck_BJMF/refs/heads/main/master/remote_config.json"
    )
    SECONDARY_REMOTE_CONFIG_URL: Optional[str] = (
        "https://gitee.com/byrisk/AutoCheck_BJMF/raw/main/master/remote_config.json"
    )
    DEFAULT_EXIT_AFTER_SIGN_MODE: str = "any" # "any" or "all"
    EXIT_PROMPT_TIMEOUT_SECONDS: int = 10
    GRACEFUL_ERROR_EXIT_DELAY_SECONDS: int = 3
    UPDATER_EXE_NAME: str = "updater.exe" # 更新程序名，期望在项目根目录
    VERSION_FILE: str = "version.txt" # 版本文件，相对于项目根目录
    APP_NAME: str = "AutoCheck_BJMF"

    # === 应用基本信息、免责声明版本、分段内容及确认短语 ===
    APP_AUTHOR_NAME: str = "byrisk"
    APP_PROJECT_LINK: str = "https://github.com/byrisk/AutoCheck_BJMF"
    # SCRIPT_VERSION 已在外部定义

    APP_LICENSE_TYPE: str = "MIT 许可证"
    APP_LICENSE_INFO_FOR_DISPLAY: str = f"本项目基于 {APP_LICENSE_TYPE} 开源。详细信息请查阅项目根目录下的 LICENSE 文件。"
    DISCLAIMER_TEXT_VERSION: str = "1.1"
    APP_DISCLAIMER_SEGMENTS: List[Tuple[str, str]] = [
        (
            "【重要声明与免责条款 - 引言】",
            f"请您在使用本软件（\"{APP_NAME}\"，以下简称“本软件”）前，仔细阅读并充分理解以下免责声明的全部内容。\n"
            f"一旦您开始使用本软件，即表示您已完全理解并接受本声明的各项条款。"
        ),
        (
            "1. 软件按“现状”提供",
            f"本软件按“现状”及“现有功能”提供，不附带任何形式的明示或暗示的保证或条件，\n"
            f"包括但不限于对适销性、特定用途适用性、非侵权性、准确性、完整性、持续可用性\n"
            f"或无错误的保证。作者不对软件功能的及时性、安全性、可靠性作任何承诺。"
        ),
        (
            "2. 责任限制",
            f"在任何适用法律允许的最大范围内，本软件的作者或版权持有人在任何情况下均不对任何\n"
            f"直接的、间接的、特殊的、偶然的、惩罚性的或后果性的损害承担责任，包括但不限于\n"
            f"利润损失、数据丢失、商誉损失、业务中断或其他商业损害或损失，无论这些损害是如何\n"
            f"引起的，基于何种责任理论（无论是合同、严格责任、侵权行为（包括疏忽）或其他原因），\n"
            f"即便作者已被告知此类损害发生的可能性。这种责任限制适用于与本软件、其内容、\n"
            f"用户行为或第三方行为相关的任何事项。"
        ),
        (
            "3. 用户责任与风险承担",
            f"您理解并同意，使用本软件的全部风险由您自行承担。您有责任：\n"
            f"    a. 确保您的使用行为完全符合您所在国家/地区的所有适用法律法规、政策规定以及您所\n"
            f"       使用的任何第三方平台（例如，学校的教务系统、微信平台等）的服务条款和用户协议。\n"
            f"    b. 妥善保管您的账户信息、配置文件（如 `data.json`）、Cookie、Token 等敏感数据。\n"
            f"       本软件通常将此类信息存储在您的本地设备上。因您自身保管不当、配置错误或设备\n"
            f"       安全问题导致的数据泄露、账户被盗用或任何其他损失，作者不承担任何责任。\n"
            f"    c. 理解本软件自动化操作的潜在影响。例如，不当的自动化操作可能导致账户异常或\n"
            f"       违反平台规则。您应对此类操作的后果负全部责任。"
        ),
        (
            "4. 软件用途与滥用",
            f"本软件主要设计用于个人学习、技术研究以及在授权和合规前提下的个人任务自动化。\n"
            f"严禁将本软件用于任何非法活动、侵犯他人合法权益（包括隐私）、恶意攻击、批量注册、\n"
            f"牟取不正当利益或任何可能对第三方平台造成不良影响或构成不正当竞争的行为。\n"
            f"任何因上述禁止行为或任何其他形式的滥用所导致的一切法律责任和损失，均由用户\n"
            f"自行承担，与本软件作者无关。"
        ),
        (
            "5. 第三方服务依赖与变更",
            f"本软件的功能可能依赖于第三方服务（如目标网站的 API 接口、微信接口等）。\n"
            f"本软件并非由这些第三方服务官方提供、授权或认可，与它们之间不存在任何关联、\n"
            f"合作或背书关系。第三方服务的更新、变更或其自身的不稳定性，均可能导致\n"
            f"本软件部分或全部功能失效、数据获取错误或产生非预期的行为。作者对此不作任何保证，\n"
            f"也不承担任何责任，并且没有义务确保本软件与第三方服务的持续兼容性。"
        ),
        (
            "6. 软件稳定性、更新与支持",
            f"本软件作为开源项目，可能存在未被发现的缺陷（BUG）、错误或安全漏洞。\n"
            f"作者不保证本软件的持续可用性、功能的完整性、错误会被修正，也不承诺提供\n"
            f"任何特定频率的更新、维护或技术支持服务。任何更新或支持（如果提供）均由\n"
            f"作者自行决定。"
        ),
        (
            "7. 不保证成功",
            f"本软件旨在尝试自动化特定流程，但并不保证任何自动化操作（例如，自动签到、\n"
            f"数据抓取等）总能成功执行、完全符合您的预期，或总能避免被目标系统检测。\n"
            f"操作的成功率受多种因素影响。"
        ),
        (
            "8. 最终建议与确认提示",
            f"在将本软件用于任何可能产生重要影响或涉及关键数据的任务之前，强烈建议您\n"
            f"充分了解其工作原理，仔细评估潜在风险，并在必要时咨询独立的法律或技术专业人士的意见。\n\n"
            f"如果您不同意本声明中的任何条款，请立即停止使用本软件并将其从您的设备中删除。\n"
            f"继续阅读并完成后续确认，将被视为您对本声明全部内容的认可。"
        )
    ]
    USER_CONFIRMATION_PHRASE: str = "我已完整阅读、清楚理解并同意上述免责声明的全部内容"

    # Data Upload Gist Configuration
    DATA_UPLOAD_GIST_ID: str = "7b7918b478ca5d39bb9afa0a76c5685f"
    DATA_UPLOAD_FILENAME: str = "device_activity_log.jsonl"
    GITHUB_PAT: str = "      " # 提醒：PAT应安全存储

    GITEE_DATA_UPLOAD_GIST_ID: Optional[str] = "31ngiqphm7frobyj965wv24"
    GITEE_PAT: Optional[str] = "          " # 提醒：PAT应安全存储
    GITEE_DATA_UPLOAD_FILENAME: str = "device_activity_log.jsonl"

    # Intervals for Background Tasks
    REMOTE_CONFIG_CACHE_TTL_SECONDS: int = 300  # 5 minutes
    DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS: int = 900  # 15 minutes
    DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS: int = 3600  # 1 hour

    # SCHOOL_DATA_FILE 路径相对于项目根目录下的 resources 文件夹
    SCHOOL_DATA_FILE: str = os.path.join("resources", "school_zones.yaml")
    MAX_RANDOM_OFFSET_METERS: float = 50.0 # 最大随机偏移距离（米）
    DEFAULT_ACCURACY: str = "20.0" # 默认精度（米）
    EARTH_RADIUS_METERS: float = 6371000.0 # 地球半径（米），用于偏移计算

    # Default Remote Configuration
    DEFAULT_REMOTE_CONFIG: Dict[str, Any] = {
        "script_version_control": {"forced_update_below_version": "0.0.0"},
        "latest_stable_version": "0.0.0",
        "access_control": {
            "global_disable": False,
            "device_blacklist": [],
            "device_whitelist": [],
        },
        "announcement": {"id": "", "message": "", "enabled": False, "title": ""}, # 添加了 title
        "settings": {
            "config_refresh_interval_seconds": DEFAULT_REMOTE_CONFIG_REFRESH_INTERVAL_SECONDS,
            "data_upload_interval_seconds": DEFAULT_DATA_UPLOAD_INTERVAL_SECONDS,
            # 可以在此为 User-Agent 池添加默认值，但原脚本似乎没有在这里定义，而是在RemoteConfigManager中处理
             "user_agent_pool": {
                "enabled": False, # 默认不启用远程UA池
                "android_versions": [],
                "devices": [],
                "build_numbers": [],
                "chrome_versions": [],
                "wechat_versions": [],
                "net_types": []
            }
        },
    }