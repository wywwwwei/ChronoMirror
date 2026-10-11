<div align="center">

# 🪞 ChronoMirror · 溯镜
### AI-Powered Quantified-Self & Cognitive Retrospective Second Brain

> *“Trace time back to its origins; gaze into the mirror of the self.”*

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
3. **Bind Your API Key**:
   - Google Gemini: `/setkey gemini YOUR_GEMINI_KEY` (**recommended** — the voice and photo features depend on its multimodal ability)
   - OpenAI (official): `/setkey openai YOUR_KEY`
   - ⚠️ **DeepSeek and any text-only service will not work** — see [Model Capability Requirements](#-model-capability-requirements--compatibility)
4. **Start Logging**: Send voice messages, text, or photos anytime. Every night at 23:00, the bot will automatically deliver your in-depth daily reflection!

> *Note: Multi-tenant data isolation is natively built-in. Your logs are completely private. Messages containing API keys are automatically retracted and deleted from the chat history upon receipt.*

---

## ✨ Key Features

- **Frictionless Multimodal Life-Logging**:
  - 💬 **Text / Quick Thoughts**: Instant timestamped appending to your daily log.
  - 🎙️ **Voice Notes**: Speech is automatically transcribed into raw, natural text.
  - 📸 **Photos (Meals / Outfits / Scenes)**: The vision model instantly condenses images into structured descriptions (saving >90% Tokens for future reviews).
- **Multi-LLM Provider Flexibility**:
  - Native support for **Google Gemini API** (recommended default, multimodal).
  - Supports **OpenAI-compatible APIs**, but the service **must provide both audio transcription and image understanding** (e.g. OpenAI official). Text-only services (**DeepSeek**, most text-only relays) **cannot run this bot in full** — see [Model Capability Requirements](#-model-capability-requirements--compatibility).
- **Evolving Long-Term Memory (L3 Profile)**:
  - Continuously abstracts your physiological patterns, cognitive biases, and high-ROI habits into `vault/memory/user_profile.md`.
- **Local-First & Obsidian Compatible**:
  - All logs and reviews are saved as standard Markdown files, perfectly compatible with **Obsidian**.
- **Automated Scheduled Reviews**:
  - **Daily Review (23:00)**: Energy fluctuation diagnosis, cognitive deconstruction, and top 3 micro-actions for tomorrow.
  - **Weekly Strategic Review (Sunday 22:00)**: Macro trend analysis, recurring traps, and system-level habit adjustments.

---

## ⚠️ Model Capability Requirements & Compatibility

This project calls the LLM for **three** different jobs, each with its own interface requirements:

| Purpose | Required capability | Where in the code |
| :--- | :--- | :--- |
| Text logging, daily/weekly reviews, L3 profile evolution | Text chat (`chat/completions`) | `generate_daily_review` / `generate_weekly_review` / `evolve_memory` |
| Voice message → text | Audio transcription endpoint | The OpenAI branch of `transcribe_audio()` calls `client.audio.transcriptions.create()` |
| Photo → meal / outfit / scene features | Image input (multimodal vision) | The OpenAI branch of `describe_image()` sends an `image_url` data URI |

### Why DeepSeek does not work

**DeepSeek's platform only offers text chat.** It has no `/audio/transcriptions` endpoint like OpenAI's, and it does not accept image input.

So even when `/setkey openai <YOUR_KEY> https://api.deepseek.com/v1` binds successfully and `/status` looks healthy, in practice this is what you get:

| Action | Result |
| :--- | :--- |
| Send a voice message | ❌ The transcription request hits an endpoint that does not exist — hard error |
| Send a photo | ❌ The vision request carries image data the server cannot handle — hard error |
| Send text, `/review`, `/weekly` | ✅ Works (text-only path) |

The whole point of this project is capturing your day "with almost zero friction", and that capture is mostly **voice and photos**. So **DeepSeek cannot run this bot in full.**

> An earlier version of this README listed DeepSeek as a directly usable option. That was wrong and has been corrected.

### What does work

You need a compatible service that offers **all three**: text, audio transcription, and image understanding.

- ✅ **Google Gemini** — the recommended default; one key covers all three.
- ✅ **OpenAI official** — a `gpt-4o`-class model plus `whisper-1`.
- ⚠️ **Aggregators / relay services** — it depends on whether the upstream really forwards audio and vision requests; verify it yourself (sending one voice message is the fastest test).
- ❌ **Text-only services** (DeepSeek, most text-only relays) — not usable.

---

## 🧠 Model Tiers & Free-Tier Quotas

The project makes **two very different kinds** of LLM calls, and ships with a different model tier for each:

| Tier | Purpose | Frequency | Default model |
| :--- | :--- | :--- | :--- |
| **capture** | Voice transcription, photo description | Once per voice/photo message — **high frequency** | `gemini-3.5-flash-lite` |
| **review** | Daily review, weekly review, L3 profile evolution | ~1/day + 1/week — **low frequency** | `gemini-3.8-flash` |

**Why split them**: on Gemini's free tier the daily quota is **shared per project, not per key** (roughly 20 requests/day for Flash vs ~500/day for Flash-Lite). Since one deployment is shared by several people, using a heavy model for capture blows through the quota after a few voice messages — while reviews only run once or twice a day and fit comfortably on the strong model. So **capture runs on the cheap tier, reviews keep the strong one**.

**Nothing to configure**: right after `/setkey gemini YOUR_KEY` both tiers already work with the defaults above. Use `/setmodel` only if you want to change them:

```
/setmodel                              Show current tiers and where each value comes from
/setmodel capture gemini-3.5-flash     Point the capture tier at another model
/setmodel reset capture                Fall back to the default
/setmodel reset all                    Reset everything
```

Tiers are **grouped by provider**, and only the provider you bound a key for is shown — so there is never a "configure several providers at once" situation:

- Gemini key only → you see `capture` and `review`
- OpenAI key only → you see `chat` (text reviews + photo description) and `whisper` (voice transcription)

> **⚠️ The privacy cost of the free tier**: on Gemini's free tier your inputs are used to improve Google's products, with **no opt-out**; only the paid tier (after linking a billing account in Google Cloud) carries the "content not used to improve our products" guarantee. This project stores a personal journal — if that matters to you, link a billing account for the paid tier, or use OpenAI official.

---

## 📱 Command Reference

| Command / Action | Description |
| :--- | :--- |
| **`/setkey`** | **Bind/Update your personal AI API Key**:<br>• Gemini: `/setkey gemini YOUR_KEY`<br>• OpenAI official: `/setkey openai YOUR_KEY`<br>• Third-party compatible service: `/setkey openai YOUR_KEY https://…/v1` (**must support both audio transcription and vision**; DeepSeek does not, so don't use it) |
| **`/switch`** | **Toggle active provider**: `/switch gemini` or `/switch openai` |
| **`/setmodel`** | **View / change the model used by each tier**:<br>• `/setmodel` — show current tiers and their source<br>• `/setmodel capture gemini-3.5-flash` — set a tier<br>• `/setmodel reset <tier\|all>` — fall back to the default<br>(Unset tiers follow the `.env` defaults — **binding a key is enough, no configuration needed**; see [Model Tiers & Free-Tier Quotas](#-model-tiers--free-tier-quotas)) |
| **`/status`** | View current active provider, masked API keys, custom Base URL, per-tier models, and account readiness. |
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

# Access whitelist (comma-separated numeric Telegram user IDs).
#   your own ID -> private mode (recommended for self-hosting)
#   "*"         -> public mode (open to every Telegram user)
#   empty       -> public mode, with a startup warning (not recommended)
ALLOWED_USER_IDS="123456789"

# Optional proxy for networks requiring VPN (e.g. Clash):
# TELEGRAM_PROXY="http://127.0.0.1:7890"

DEFAULT_LLM_PROVIDER="gemini"
GEMINI_API_KEY="your_gemini_key"
# Capture tier (high frequency — cheap, wide free-tier quota)
GEMINI_CAPTURE_MODEL="gemini-3.5-flash-lite"
# Review tier (once a day/week — keeps the strong model)
GEMINI_REVIEW_MODEL="gemini-3.8-flash"

# If you prefer OpenAI official (must support both audio transcription and vision):
# DEFAULT_LLM_PROVIDER="openai"
# OPENAI_API_KEY="your_api_key"
# OPENAI_MODEL="gpt-4o-mini"
# OPENAI_VISION_MODEL="gpt-4o-mini"
# OPENAI_WHISPER_MODEL="whisper-1"
#
# ⚠️ Do NOT use DeepSeek or any other text-only service:
#    they expose no audio-transcription endpoint and reject image input,
#    so voice and photo messages will fail outright.
```

> **⚠️ Global keys vs. whitelist**: the `GEMINI_API_KEY` / `OPENAI_API_KEY` in `.env` are used as a fallback **only in private mode (i.e. when `ALLOWED_USER_IDS` is set)**. In public mode they are never used as a fallback, so every user must run `/setkey` with their own key — otherwise strangers would spend your API quota. A key bound per-user via `/setkey` always takes precedence; `/status` shows the effective key source.


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
