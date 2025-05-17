📦 班级魔方自动签到系统 (AutoCheck_BJMF)
<p align="center"> <img src="https://img.shields.io/badge/Python-3.8+-blue?logo=python"/> <img src="https://img.shields.io/badge/Selenium-Automation-important?logo=selenium"/> <img src="https://img.shields.io/badge/Status-Stable-brightgreen"/> <img src="https://img.shields.io/github/license/byrisk/AutoCheck_BJMF"/> <img src="https://img.shields.io/github/stars/byrisk/AutoCheck_BJMF?style=social"/> </p>
✨ 核心功能
功能	描述	状态
📍 GPS定位签到	支持自定义经纬度，自动偏移模拟真实定位	✅
🔍 二维码识别	自动解析二维码内容完成签到	✅
📷 拍照签到	支持调用摄像头或上传本地照片	✅
⏰ 定时任务	全天候自动监控签到任务	✅
🍪 Cookie持久化	免登录自动签到	✅
📊 日志记录	详细记录每次签到结果	✅
🚀 快速开始
环境准备
安装 Python 3.8+

安装 Chrome 浏览器

安装步骤
bash
# 克隆项目
git clone https://github.com/byrisk/AutoCheck_BJMF.git
cd AutoCheck_BJMF

# 安装依赖
pip install -r requirements.txt
首次配置
修改 config.py 填写你的账号信息

运行获取 Cookie:

bash
python get_cookie.py
设置 GPS 坐标:

bash
python gps.py
🛠️ 使用说明
常规运行
bash
python main.py
定时运行
bash
python schedule.py
高级配置
settings.py: 启用/禁用特定功能

config.py: 修改签到参数和通知设置

📌 注意事项
首次使用需手动登录获取 Cookie

GPS 签到请确保坐标准确

拍照签到需准备替代图片或启用摄像头

建议使用虚拟环境运行

❓ 常见问题
Q: 找不到我的学校怎么办？
A: 请自行修改 config.py 中的学校名单

Q: 签到失败如何处理？
A: 检查日志文件，确认:

任务是否过期

坐标是否有效

网络连接是否正常

Q: 如何开启通知功能？
A: 在 config.py 中配置通知相关参数

🤝 参与贡献
欢迎提交 Issue 或 Pull Request

📄 开源协议
本项目采用 MIT License

<p align="center"> 💖 如果这个项目帮到了你，请点个 ⭐ Star！<br> ☕ 解放双手，每天多睡 10 分钟！ </p>
