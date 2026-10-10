<div align="center">

# 🪞 ChronoMirror · 溯镜
### AI-Powered Quantified-Self & Cognitive Retrospective Second Brain

> *“Trace time back to its origins; gaze into the mirror of the self.”*

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

## 📖 Vision

Traditional journaling and personal retrospective routines almost always fail for two reasons:
1. **High friction of recording**: Staring at a blank document every night with complex templates is unsustainable.
2. **Cognitive bias and self-deception**: Humans instinctively sanitize their memories, rationalizing poor habits and evading uncomfortable truths.

**ChronoMirror (溯镜)** acts as your objective, dispassionate second brain: **it captures your raw daily stream (voice, photos, thoughts) with zero friction, and lets an AI serve as an honest mirror to dissect your cognitive blind spots, energy fluctuations, and habits.**

---

## ⚡ Quickstart: Zero-Setup (No Deployment Needed)

> **💡 Don't want to manage a server or configure code?**  
> You can directly use the ready-to-use official Telegram Bot:

1. **Open Telegram**: Search and start a chat with [**@ChronoMirrorBot**](https://t.me/ChronoMirrorBot)
2. **Start the Bot**: Send `/start` to view the welcome guide.
3. **Bind Your API Key** (Choose either):
   - For Google Gemini: `/setkey gemini YOUR_GEMINI_KEY`
   - For OpenAI / DeepSeek: `/setkey openai YOUR_KEY [OPTIONAL_BASE_URL]`
4. **Start Logging**: Send voice messages, text, or photos anytime. Every night at 23:00, the bot will automatically deliver your in-depth daily reflection!

> *Note: Multi-tenant data isolation is natively built-in. Your logs are completely private. Messages containing API keys are automatically retracted and deleted from the chat history upon receipt.*

---

## ✨ Key Features

- **Frictionless Multimodal Life-Logging**:
  - 💬 **Text / Quick Thoughts**: Instant timestamped appending to your daily log.
  - 🎙️ **Voice Notes**: Speech is automatically transcribed into raw, natural text.
  - 📸 **Photos (Meals / Outfits / Scenes)**: The vision model instantly condenses images into structured descriptions (saving >90% Tokens for future reviews).
- **Multi-LLM Provider Flexibility**:
  - Native support for **Google Gemini API** (Gemini 2.5 Flash / 2.0).
  - Native support for **OpenAI-compatible APIs** (DeepSeek, GPT-4o, SiliconFlow, OneAPI, etc.).
- **Evolving Long-Term Memory (L3 Profile)**:
  - Continuously abstracts your physiological patterns, cognitive biases, and high-ROI habits into `vault/memory/user_profile.md`.
- **Local-First & Obsidian Compatible**:
  - All logs and reviews are saved as standard Markdown files, perfectly compatible with **Obsidian**.
- **Automated Scheduled Reviews**:
  - **Daily Review (23:00)**: Energy fluctuation diagnosis, cognitive deconstruction, and top 3 micro-actions for tomorrow.
  - **Weekly Strategic Review (Sunday 22:00)**: Macro trend analysis, recurring traps, and system-level habit adjustments.

---

## 📱 Command Reference

| Command / Action | Description |
| :--- | :--- |
| **`/setkey`** | **Bind/Update your personal AI API Key**:<br>• Gemini: `/setkey gemini YOUR_KEY`<br>• OpenAI: `/setkey openai YOUR_KEY`<br>• DeepSeek / Third-party: `/setkey openai YOUR_KEY https://api.deepseek.com/v1` |
| **`/switch`** | **Toggle active provider**: `/switch gemini` or `/switch openai` |
| **`/status`** | View current active provider, masked API keys, custom Base URL, and account readiness. |
| **Send Text** | Automatically timestamps and appends to today's log (L0). |
| **Send Voice** | Auto-transcribes speech to text and saves into today's log. |
| **Send Photo** | Extracts structured meal nutrition, outfit suitability, or scene features. |
| **`/today`** | View today's recorded stream of thoughts and events. |
| **`/review`** | Manually trigger today's deep reflection immediately. |
| **`/review YYYY-MM-DD`** | Retrospect a specific date in the past. |
| **`/weekly`** | Generate weekly strategic retro and evolve long-term memory profile. |
| **`/profile`** | View your accumulated long-term cognitive and behavioral profile. |
| **`/id`** | Check your Telegram User ID. |

---

## 🛠️ Self-Hosting Guide

If you prefer to run your own private instance:

### 1. Clone & Setup Environment

```bash
git clone https://github.com/wywwwwei/ChronoMirror.git
cd ChronoMirror

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:
```ini
TELEGRAM_BOT_TOKEN="your_bot_token_from_botfather"
# Optional proxy for networks requiring VPN (e.g. Clash):
# TELEGRAM_PROXY="http://127.0.0.1:7890"

DEFAULT_LLM_PROVIDER="gemini"
GEMINI_API_KEY="your_gemini_key"
```

### 3. Run

```bash
# Run Telegram Bot & Scheduler daemon
python main.py

# Or run terminal CLI interactive test mode (no Telegram token required)
python main.py --cli
```

### 4. Docker Deployment (VPS)

```bash
docker compose up -d --build
docker compose logs -f
```

---

## 🔒 Privacy & Data Security

- **Strict User Isolation**: All logs, attachments, reviews, and credentials are physically separated under `vault/users/<user_id>/`.
- **Git Shield**: `.gitignore` strictly blocks all personal diaries (`vault/logs/`), reviews, attachments, and user configuration files from ever being committed.
- **Key Safety**: The Telegram bot automatically deletes the message containing your API key upon receiving `/setkey`.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
