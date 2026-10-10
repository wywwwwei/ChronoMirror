<div align="center">

# 🪞 溯镜 · ChronoMirror
### AI 驱动的量化自我与认知复盘外脑 (Quantified Self & Cognitive Retro)

> *“溯源时空，鉴己之镜。”*

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Telegram Bot](https://img.shields.io/badge/Telegram_Bot-@ChronoMirrorBot-2CA5E0.svg?logo=telegram&logoColor=white)](https://t.me/ChronoMirrorBot)
[![Google Gemini](https://img.shields.io/badge/LLM-Gemini_2.5-4E75F6.svg?logo=google&logoColor=white)](https://ai.google.dev/)
[![OpenAI Compatible](https://img.shields.io/badge/LLM-OpenAI_Compatible-412991.svg?logo=openai&logoColor=white)](https://platform.openai.com/)
[![Obsidian Ready](https://img.shields.io/badge/Storage-Obsidian_Vault-7C3AED.svg?logo=obsidian&logoColor=white)](https://obsidian.md/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<br/>

**[English](README_EN.md)** | **[简体中文](README.md)**

</div>

---

## 📖 项目愿景

很多人尝试过写日记或做个人复盘，但通常死于两个痛点：
1. **记录摩擦力太大**：每天面对空白文档，格式繁琐，坚持不了两周。
2. **复盘变成自我欺骗**：人天生倾向于美化自己，逃避认知失调，难以跳出自我防御机制。

**ChronoMirror (溯镜)** 的核心使命是：**以极低摩擦捕获你的全天真实生活流，并让 AI 作为一面冷峻、客观的镜像，代替你进行认知诊断、盲点解构与中长期复盘。**

---

## ⚡ 极速上手：免部署方案 (Zero-Setup)

> **💡 不想自行搭建服务器或配置本地代码？**  
> 你可以直接使用已经部署就绪的官方机器人服务：

1. **进入对话**：在 Telegram 搜索并私聊 [**@ChronoMirrorBot**](https://t.me/ChronoMirrorBot)
2. **激活会话**：发送 `/start` 查看功能指引
3. **绑定个人密钥**：发送你的 API Key（**二选一**）：
   - 绑定 Gemini：`/setkey gemini 你的GeminiKey`
   - 绑定 OpenAI / DeepSeek：`/setkey openai 你的Key [可选BaseURL]`
4. **即刻开始使用**：随时发语音、文字或生活照片，每晚 23:00 系统将自动为你定向推送深度日复盘！

> *注：系统已内置多用户物理隔离，每位用户的数据完全独立保密；发送包含密钥的消息会被机器人自动删除销毁，确保隐私无虞。*

---

## ✨ 主要特性

- **全平台随时采集**：通过 Telegram Bot 发送语音、拍照、文字，无网络穿透负担，开机即用。
- **双大模型引擎自由切换**：
  - 原生支持 **Google Gemini API**（Gemini 2.5 Flash / 2.0，多模态性价比首选）。
  - 原生支持 **OpenAI 兼容接口**（可自由接入 DeepSeek、GPT-4o、硅基流动、OneAPI 等）。
- **长期个人画像动态进化 (L3 Memory)**：
  - AI 持续在 `vault/memory/user_profile.md` 中记录并迭代关于你的身体规律、认知偏差与高 ROI 行为习惯。
- **本地优先与隐私保护**：
  - 核心记录均保存在本地 Markdown 文件中，可用 **Obsidian** 直接打开查看与关系图谱分析。
  - `.gitignore` 默认屏蔽个人日记与多媒体，开源上传时无需担心隐私外泄。
- **定时自动推送**：
  - 每晚 23:00 自动分析今日日志，生成深度日复盘并回推到手机。
  - 每周日 22:00 自动汇总过去 7 天，生成宏观周度战略分析报告。

---

## 📂 存储目录规范 (`vault/`)

```
vault/
├── logs/                   # L0: 每日原始时间流流水账 (YYYY-MM-DD.md)
├── attachments/            # 多媒体原始文件 (语音 .ogg / 照片 .jpg)
├── reviews/
│   ├── daily/              # L1: 每日深度复盘 (YYYY-MM-DD.md)
│   └── weekly/             # L2: 周度战略复盘 (YYYY-Www.md)
└── memory/
    └── user_profile.md     # L3: 个人动态画像与思维模型 (长期记忆)
```

---

## 🚀 快速上手

### 1. 克隆项目与安装环境

```bash
git clone https://github.com/wywwwwei/ChronoMirror.git
cd ChronoMirror

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制配置文件模版：
```bash
cp .env.example .env
```

打开 `.env` 文件并填入你的参数：
```ini
# 1. Telegram Bot Token (在 Telegram 搜索 @BotFather 发送 /newbot 获取)
TELEGRAM_BOT_TOKEN="your_bot_token"

# 2. 如果在大陆网络且需要本地代理 (如 Clash 默认 7890 端口):
# TELEGRAM_PROXY="http://127.0.0.1:7890"

# 3. 大模型配置 (默认推荐 Gemini)
DEFAULT_LLM_PROVIDER="gemini"
GEMINI_API_KEY="your_gemini_api_key"
GEMINI_MODEL="gemini-2.5-flash"

# 若后续使用 OpenAI / DeepSeek / 硅基流动:
# DEFAULT_LLM_PROVIDER="openai"
# OPENAI_API_KEY="your_api_key"
# OPENAI_BASE_URL="https://api.deepseek.com/v1"
# OPENAI_MODEL="deepseek-chat"
```

### 3. 启动运行

#### 方式 A：本地直接运行 (推荐日常使用)
```bash
python main.py
```

#### 方式 B：本地终端交互模式 (无需配置 Telegram，即刻体验)
```bash
python main.py --cli
```

#### 方式 C：Docker 一键常驻运行
```bash
docker compose up -d --build
```

---

## 👥 多用户复用与密钥隔离机制 (Multi-Tenant Ready)

系统原生支持**多用户复用同一个 Telegram Bot**：
- **物理数据隔离**：每个用户的数据均独立保存在 `vault/users/<user_id>/` 下，彼此完全隔离，互不串扰。
- **各自绑定 API Key**：未绑定 Key 的用户**无法调用 AI 记录与复盘功能**，保障系统资源的公平与安全。
- **密钥聊天防泄露**：当用户在 Telegram 私聊发送 `/setkey` 时，机器人会自动删除该条包含明文密钥的消息，防止留存在聊天记录中。

---

## 📱 日常交互指令速查

| 指令 / 动作 | 格式示例与说明 |
| :--- | :--- |
| **`/setkey`** | **绑定/修改个人的 AI API Key**：<br>• 绑定 Gemini: `/setkey gemini 你的GeminiKey`<br>• 绑定 OpenAI: `/setkey openai 你的OpenAIKey`<br>• 绑定第三方 (如 DeepSeek): `/setkey openai 你的Key https://api.deepseek.com/v1` |
| **`/switch`** | **在已配置的 Gemini 与 OpenAI 之间快速切换**：`/switch gemini` 或 `/switch openai` |
| **`/status`** | 查看当前生效的模型提供商、掩码 Key、Base URL 及账号就绪状态 |
| **发送文本消息** | 自动记录时间戳并追加到个人今日时间流日志（L0） |
| **发送语音消息** | 自动识别转写为文字并按时间戳归档 |
| **发送照片 (可带附言)** | 视觉大模型即时提取饮食热量、穿搭适宜度或场景文字记录（节省 90% Token） |
| **`/today`** | 快速查看今日记录的时间流水账 |
| **`/review`** | 立即手动触发今日深度日复盘（默认每晚 23:00 系统也会自动定向推送） |
| **`/review 2026-10-10`** | 指定复盘某一天的日记 |
| **`/weekly`** | 立即生成本周战略复盘，并自动提炼更新个人的 L3 长期画像 |
| **`/profile`** | 查看当前 AI 提炼的个人长期思维与行为画像 (L3 Memory) |
| **`/id`** | 查询当前用户的 Telegram 数字 ID |

---

## 🚢 云服务器 (VPS) 迁移指南

当你购入云服务器后，得益于 Telegram 的长轮询（Long Polling）机制，**无需域名、无需公网 IP 解析、无需 Nginx 反代**：

```bash
# 1. 将项目同步至服务器
rsync -avz --exclude 'venv' ./ root@your_server_ip:/opt/ChronoMirror/

# 2. 在服务器上一键启动容器
cd /opt/ChronoMirror
docker compose up -d --build

# 3. 实时查看后台运行日志
docker compose logs -f
```

---

## 🛡️ 隐私与安全说明

- **个人日记不随代码提交**：项目的 `.gitignore` 已预设规则，会自动忽略 `vault/logs/*.md`、`vault/reviews/**/*.md` 以及 `vault/attachments/*`。
- **敏感配置隔离**：所有的 API Key 与 Token 严格隔离在 `.env` 中，严禁提交到公共仓库。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源。
