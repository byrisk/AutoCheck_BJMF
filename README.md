<h1 align="center">📦 班级魔方 (AutoCheck_BJMF)</h1>

<p align="center">
    一款基于 Selenium 的自动化签到工具，支持北京“班级魔方”平台的 <br>
    ✅ GPS签到 ✅ 二维码签到 ✅ 拍照签到 ✅ 持续签到 ✅ 定时任务 ✅ 自动缓存
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue.svg">
  <img src="https://img.shields.io/badge/Status-Stable-brightgreen">
  <img src="https://img.shields.io/badge/License-MIT-lightgrey">
</p>

---

## 📚 目录 Contents

- [📌 项目介绍](#项目介绍)
- [✨ 支持的功能](#支持的功能)
- [🏁 快速使用](#快速使用)
- [🧩 项目结构](#项目结构)
- [⚙️ 配置说明](#配置说明)
- [🕒 定时执行方式](#定时执行方式)
- [📂 历史签到信息记录](#历史签到信息记录)
- [📋 常见问题](#常见问题)
- [📄 License](#license)
- [👨‍💻 作者](#作者)

---

## 📌 项目介绍

**AutoCheck_BJMF**（项目名：班级魔方）是一个针对「班级魔方」校园签到系统开发的自动签到工具，支持扫码 / 定位 / 拍照等签到形式。

> 自动完成签到，支持无人值守、定时任务、签到模式识别、缓存签到信息记录等高级功能，解放双手！

---

## ✨ 支持的功能

|
 功能类型     
|
 描述 
|
|
--------------
|
------
|
|
 ✅ GPS定位签到         
|
 支持自定义经纬度，内置随机偏移算法 
|
|
 ✅ 二维码任务签到      
|
 可识别二维码抓取到的任务并执行签到 
|
|
 ✅ 拍照签到            
|
 提供摄像头拍照 / 本地照片模拟上传 
|
|
 ✅ 自动导入签到配置    
|
 支持读取 
`data.json`
 自动识别签到数据 
|
|
 ✅ 自动缓存签到数据    
|
 签到任务会自动保存，以便续签无需扫码 
|
|
 ✅ 持续签到任务        
|
 可设置循环签到，无需重新获取 Cookie 
|
|
 ✅ 定时签到            
|
 可通过 Python 脚本设定每天启动时间签到 
|
|
 ✅ 24小时无人值守       
|
 可全天后台静默运行，适配服务器、树莓派部署 
|

> ▪ 所有签到模式经过 **实际验证通过 ✅**<br>
> ▪ 支持 Headless ⛺ 后台运行模式

---

## 🏁 快速使用

### 1️⃣ 安装依赖

```bash
pip install -r requirements.txt.
```

### 2️⃣ 首次扫码或收到手动输入cookie（必须）

会保存到 data.json，自动识别获取的二维码


✅ 可选：使用定时任务签到（支持循环）

设置签到间隔等参数后，定时循环进行签到操作。

### 🧩 项目结构
AutoCheck_BJMF/
├── core.py         # 🌟 主程序入口，签到控制中心
├── get_cookie.py   # 用于首次扫码抓取任务信息
├── gps.py          # 经纬度管理和偏移处理
├── photo.py        # 拍照或照片模拟上传
├── schedule.py     # 自动定时签到逻辑
├── qrcode.py       # 二维码读取分析任务
├── config.py       # 用户信息/签到配置
├── settings.py     # 签到功能开关配置
├── data.json       # 缓存抓包信息，支持续签
├── logs/           # 每次签到的日志记录
└── requirements.txt
## ⚙️ 配置说明（settings.py）
参数	示例值	描述
ENABLE_QRCODE	True	是否启用二维码签到模式
ENABLE_GPS	True	是否启用定位签到
ENABLE_PHOTO	True	是否启用拍照上传
HEADLESS	True	是否后台静默运行（无浏览器界面）

## 🕒 定时执行方式（推荐）
▶ Windows 用户
可使用系统内置「任务计划程序」


📂 历史签到信息记录
签到任务信息将保存在：

data.json   # 二维码或GPS信息缓存
logs/       # 每次签到日志保存

## 📋 常见问题 (FAQ)
问题	解决方案
ChromeDriver 报错	检查浏览器版本是否与 chromedriver 对应
签到没生效	检查是否已过签到时间／是否重复提交
拍照节点报错	可更换 PHOTO_PATH 为本地任意图片
data.json 丢失？	可重新运行 get_cookie.py
## 📄 License
本项目基于开源协议 MIT License
所有代码可自由使用、修改与发布（保留原作者署名信息）

## 👨‍💻 作者
开发者：byrisk
开源仓库：https://github.com/byrisk/AutoCheck_BJMF

<p align="center"> 📌 如果你觉得这个项目有用，请点个 ⭐ Star 支持一下！ </p> ```
