<div align="center">

# 🪞 溯镜 · ChronoMirror
### AI 驱动的量化自我与认知复盘外脑 (Quantified Self & Cognitive Retro)

> *“溯源时空，鉴己之镜。”*

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Telegram Bot](https://img.shields.io/badge/Telegram_Bot-@ChronoMirrorBot-2CA5E0.svg?logo=telegram&logoColor=white)](https://t.me/ChronoMirrorBot)
[![Google Gemini](https://img.shields.io/badge/LLM-Gemini_3.x-4E75F6.svg?logo=google&logoColor=white)](https://ai.google.dev/)
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
3. **绑定个人密钥**：发送你的 API Key：
   - 绑定 Gemini：`/setkey gemini 你的GeminiKey`（**推荐**，语音与照片依赖它的多模态能力）
   - 绑定 OpenAI 官方：`/setkey openai 你的Key`
   - ⚠️ **DeepSeek 及任何纯文本服务用不了**，原因见 [模型能力要求与兼容性说明](#-模型能力要求与兼容性说明)
4. **即刻开始使用**：随时发语音、文字或生活照片，每晚 23:00 系统将自动为你定向推送深度日复盘！

> *注：系统已内置多用户物理隔离，每位用户的数据完全独立保密；发送包含密钥的消息会被机器人自动删除销毁，确保隐私无虞。*

---

## ✨ 主要特性

- **全平台随时采集**：通过 Telegram Bot 发送语音、拍照、文字，无网络穿透负担，开机即用。
- **双大模型引擎自由切换**：
  - 原生支持 **Google Gemini API**（多模态性价比首选，**默认推荐**）。
  - 支持 **OpenAI 兼容接口**，但**要求该服务同时具备音频转写与图片理解能力**（如 OpenAI 官方）。
    只提供文本对话的服务（**DeepSeek**、多数纯文本中转）**无法完整使用本机器人** —— 详见 [模型能力要求与兼容性说明](#-模型能力要求与兼容性说明)。
- **长期个人画像动态进化 (L3 Memory)**：
  - AI 持续在 `vault/memory/user_profile.md` 中记录并迭代关于你的身体规律、认知偏差与高 ROI 行为习惯。
- **本地优先与隐私保护**：
  - 核心记录均保存在本地 Markdown 文件中，可用 **Obsidian** 直接打开查看与关系图谱分析。
  - `.gitignore` 默认屏蔽个人日记与多媒体，开源上传时无需担心隐私外泄。
- **定时自动推送**：
  - 每晚 23:00 自动分析今日日志，生成深度日复盘并回推到手机。
  - 每周日 22:00 自动汇总过去 7 天，生成宏观周度战略分析报告。

---

## ⚠️ 模型能力要求与兼容性说明

本项目对 LLM 的调用分三类，对接口能力的要求完全不同：

| 用途 | 需要的能力 | 代码位置 |
| :--- | :--- | :--- |
| 文字归档、日/周复盘、L3 画像进化 | 文本对话 (`chat/completions`) | `generate_daily_review` / `generate_weekly_review` / `evolve_memory` |
| 语音消息 → 文字 | 音频转写端点 | `transcribe_audio()` 的 OpenAI 分支调用 `client.audio.transcriptions.create()` |
| 照片 → 饮食/穿搭/场景特征 | 图片输入（多模态视觉） | `describe_image()` 的 OpenAI 分支发送 `image_url` 的 data URI |

### 为什么 DeepSeek 用不了

**DeepSeek 的开放平台只提供文本对话接口。** 它没有 OpenAI 的 `/audio/transcriptions` 语音转写端点，也不接受图片输入。

所以即使 `/setkey openai <你的Key> https://api.deepseek.com/v1` 能绑定成功、`/status` 也显示正常，实际使用时是这样：

| 操作 | 结果 |
| :--- | :--- |
| 发送语音 | ❌ 转写请求打向一个不存在的端点，直接报错 |
| 发送照片 | ❌ 视觉请求携带图片数据，服务端无法处理，直接报错 |
| 发送文字、`/review`、`/weekly` | ✅ 可用（纯文本路径） |

而本项目的核心价值是「以极低摩擦捕获全天生活流」，录入方式主要就是**语音和照片**。因此 **DeepSeek 无法完整使用本机器人**。

> 早期版本的 README 曾把 DeepSeek 列为可直接接入的推荐项，那是错的，现已更正。

### 哪些服务可以用

需要**同时**具备文本、音频转写、图片理解三种能力的兼容服务：

- ✅ **Google Gemini** —— 默认推荐，一次绑定三种能力齐备。
- ✅ **OpenAI 官方** —— `gpt-4o` 系模型 + `whisper-1`。
- ⚠️ **聚合平台 / 中转服务** —— 取决于其上游是否真的转发了音频与视觉请求，需自行验证（发一条语音试一下最快）。
- ❌ **纯文本服务**（DeepSeek、多数纯文本中转）—— 不可用。

---

## 🧠 模型档位与免费额度

项目对 LLM 的调用分成**两类完全不同的工作负载**，默认给它们配了不同的模型档位：

| 档位 | 用途 | 调用频率 | 默认模型 |
| :--- | :--- | :--- | :--- |
| **capture** | 语音转写、照片描述 | 每条语音/照片各一次，**高频** | `gemini-3.5-flash-lite` |
| **review** | 日复盘、周复盘、L3 画像进化 | 约每天 1 次 + 每周 1 次，**低频** | `gemini-3.8-flash` |

**为什么要分开**：Gemini 免费档的每日额度是**按 project 共享的，不按 Key**（Flash 约 20 次/天，
Flash-Lite 约 500 次/天）。本项目是多人共用一个部署，采集用强档的话几个人发几条语音就打爆额度，
而复盘每天/每周只跑一两次，用强档完全放得下。所以**采集走便宜档、复盘保留强档**。

**你不需要做任何配置**：`/setkey gemini 你的Key` 之后两个档位就自动按上表的默认值工作。
想调整再用 `/setmodel`：

```
/setmodel                              查看当前档位与来源（个人设置 / 跟随 .env）
/setmodel capture gemini-3.5-flash     把采集档换成别的模型
/setmodel reset capture                恢复跟随默认
/setmodel reset all                    全部恢复默认
```

档位是**按提供商分组**的，只会显示你绑过 Key 的那一家，所以不会有"要同时配好几家"的情况：

- 只有 Gemini Key → 看到 `capture`、`review`
- 只有 OpenAI Key → 看到 `chat`（文本复盘 + 照片描述）、`whisper`（语音转写）

> **⚠️ 免费档的隐私代价**：Gemini 免费档的输入内容会被 Google 用于改进其产品，且**没有关闭开关**；
> 付费档（在 Google Cloud 绑定结算账号后）才有 "content not used to improve our products" 的保证。
> 本项目记录的是个人日记，如果你在意这一点，请为项目绑定结算账号走付费档，或改用 OpenAI 官方。

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

# 2. 访问白名单（自建自用强烈建议填写，避免机器人被陌生人使用）
#    填你的数字 User ID = 私有模式；填 "*" = 公开模式；留空 = 公开（启动会告警）
ALLOWED_USER_IDS="123456789"

# 3. 如果在大陆网络且需要本地代理 (如 Clash 默认 7890 端口):
# TELEGRAM_PROXY="http://127.0.0.1:7890"

# 4. 大模型配置 (默认推荐 Gemini)
DEFAULT_LLM_PROVIDER="gemini"
GEMINI_API_KEY="your_gemini_api_key"
# 采集档（高频，走便宜、额度宽的档位）
GEMINI_CAPTURE_MODEL="gemini-3.5-flash-lite"
# 复盘档（每天/每周一次，保留强档）
GEMINI_REVIEW_MODEL="gemini-3.8-flash"

# 若后续使用 OpenAI 官方（须同时支持语音转写与图片理解）:
# DEFAULT_LLM_PROVIDER="openai"
# OPENAI_API_KEY="your_api_key"
# OPENAI_MODEL="gpt-4o-mini"
# OPENAI_VISION_MODEL="gpt-4o-mini"
# OPENAI_WHISPER_MODEL="whisper-1"
#
# ⚠️ 不要填 DeepSeek 或其它纯文本服务：
#    它们没有音频转写端点、也不接受图片输入，绑定后语音与照片消息会直接失败。
```

> **⚠️ 关于全局 Key 与白名单的关系**：`.env` 里的 `GEMINI_API_KEY` / `OPENAI_API_KEY` 只在**私有模式（配置了 `ALLOWED_USER_IDS`）**下作为白名单用户的兜底 Key 生效；公开模式下不会兜底，每位用户都必须自行 `/setkey`，以免陌生用户消耗你的 API 额度。
> 当然，任何用户在对话里用 `/setkey` 绑定的个人 Key 优先级永远高于 `.env` 的全局 Key。用 `/status` 可以看到当前生效的「Key 来源」。

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
  （例外：私有模式下，白名单用户可直接复用 `.env` 里的全局 Key，无需逐个 `/setkey`；公开模式一律要求自备 Key。）
- **密钥聊天防泄露**：当用户在 Telegram 私聊发送 `/setkey` 时，机器人会自动删除该条包含明文密钥的消息，防止留存在聊天记录中。
- **访问白名单**：`ALLOWED_USER_IDS` 控制谁能使用机器人；未配置即为公开模式，启动时会打印醒目警告。

---

## 📱 日常交互指令速查

| 指令 / 动作 | 格式示例与说明 |
| :--- | :--- |
| **`/setkey`** | **绑定/修改个人的 AI API Key**：<br>• 绑定 Gemini: `/setkey gemini 你的GeminiKey`<br>• 绑定 OpenAI 官方: `/setkey openai 你的OpenAIKey`<br>• 第三方兼容服务: `/setkey openai 你的Key https://…/v1`（**该服务必须同时支持音频转写与图片理解**；DeepSeek 不满足，请勿使用） |
| **`/switch`** | **在已配置的 Gemini 与 OpenAI 之间快速切换**：`/switch gemini` 或 `/switch openai` |
| **`/setmodel`** | **查看/调整各档位使用的模型**：<br>• `/setmodel` 查看当前档位与来源<br>• `/setmodel capture gemini-3.5-flash` 设置某档位<br>• `/setmodel reset <档位\|all>` 恢复跟随默认<br>（不设置时自动使用 `.env` 默认值，**绑完 Key 即可用，无需配置**；详见 [模型档位与免费额度](#-模型档位与免费额度)） |
| **`/status`** | 查看当前生效的模型提供商、掩码 Key、Base URL、各档位模型及账号就绪状态 |
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
