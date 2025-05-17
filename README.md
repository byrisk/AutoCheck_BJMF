<h1 align="center">📦 班级魔方 (AutoCheck_BJMF)</h1>

<p align="center">🎯 自动完成【班级魔方系统】定位签到和二维码签到</p>
<p align="center">📍 全天运行 ｜无人值守 ｜高可定制 ｜支持 GPS / 拍照 / 二维码签到</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue"/>
  <img src="https://img.shields.io/badge/Selenium-Automation-important"/>
  <img src="https://img.shields.io/badge/Status-Stable-brightgreen"/>
  <img src="https://img.shields.io/github/license/byrisk/AutoCheck_BJMF"/>
</p>

---

## 💡 软件介绍

**班级魔方自动签到系统（AutoCheck_BJMF）**是基于大中小学使用的「班级魔方」平台开发的自动签到工具。它模拟真实用户的登录行为，可实现高效、稳定、无人值守的签到功能，支持以下全部签到模式：

- ✅ 普通扫码签到
- ✅ GPS 定位签到
- ✅ GPS + 拍照签到（模拟拍照并上传）
- ✅ 全自动签到任务监控与执行
- ✅ 定时执行或任务触发
- ✅ 自动记录任务状态与结果
- ✅ Cookie 持久化签到（免登录）

---

## 🧩 项目亮点 / 特性

| 功能 | 描述 |
|------|------|
| ✅ 定位签到 | 自定义签到位置（经纬度） + 每次签到自动偏移，模拟真实定位 |
| ✅ 二维码签到 | 扫描识别 QRCode 内容并自动完成任务 |
| ✅ 拍照签到 | 模拟调用摄像头，或直接上传本地照片完成签到任务 |
| ✅ data.json 存储 | 自动保存扫码数据，重复签到只需设定定时任务即可 |
| ✅ 全自动运行 | 全流程无需人工，支持 `schedule.py` 设定签到时间段 |
| ✅ Headless 模式 | 支持无界面运行适合服务器部署，低资源运行 |
| ✅ 多模式自适应 | 自动判断当前待签到任务类型（通过页面内容识别） |

---

## 📁 文件结构
AutoCheck_BJMF/ 
├── core.py # 核心签到控制逻辑 (派发任务/提交表单/模拟操作)
├── get_cookie.py # 抓取 Cookie（首登、手动操作辅助） 
├── gps.py # 自定义定位功能、偏移算法、坐标读取与保存
├── photo.py # 拍照模拟，上传逻辑，拍照占位图/摄像头调用
├── qrcode.py # 二维码识别与任务标识提取 
├── schedule.py # 定时签到入口（结合时间段或 cron 调用） 
├── config.py # 自定义用户信息和参数配置（接口、拍照路径等）
├── settings.py # 高级配置开关控制模块（是否启用二维码、拍照等）
├── data.json # 本地缓存识别后的签到任务信息 
├── logs/ # 签到记录/日志输出保存路径
├── requirements.txt # 依赖列表（selenium, pillow 等） 
└── README.md # 中文项目说明

## ⚙️ 环境要求

- ✅ Python 3.8+
- ✅ Windows 10/11

---

## 🛠️ 安装教程

### 1. 克隆项目

bash
git clone https://github.com/byrisk/AutoCheck_BJMF.git
cd AutoCheck_BJMF

###2. 安装依赖
pip install -r requirements.txt


🚀 运行方式
✅ 常规运行
python main.py

✅ 获取 Cookie（首次运行）

✅ 查看并设置 GPS 坐标

✅ 定时运行脚本
✅ 通知设置

💬 常见问题 FAQ
问题	解答
Q: 内置学校中没有自己的学校？自行修改学校名单。
Q: 签到失败？	请检查是否配置真实坐标，并确保任务尚未过期或重复提交
Q: 没有通知功能？请自行配置通知相关配置
Q: 内部通知如何开启？ 请尝试修改信息类别

📄 License
班级魔方 AutoCheck_BJMF 遵循 MIT License 开源协议，自由使用和修改。

🧑‍💻 作者作者
由 @byrisk 倾情制作
欢迎提 Issues、Fork 进行二次开发，点赞收藏 🔥
<p align="center"> ☕ 解放双手，每天多睡 10 分钟！<br/> 💖 如果这个项目帮到了你，请点个 ⭐ Star！ </p> 
