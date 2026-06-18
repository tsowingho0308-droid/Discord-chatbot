# Discord Voice Chatbot

Discord 語音 Bot，具備雙向語音互動能力。

## 功能
- 加入 Discord 語音頻道，監聽所有人發言（包含你）
- STT（語音轉文字）→ LLM（DeepSeek-chat 思考）→ TTS（文字轉語音）→ 播放回頻道
- 辨識到你的聲音時，稱呼「主人」並以恭敬態度回答
- 多人同時說話時自動打斷：
  - 主人不在場：「太吵了，一個一個說」
  - 主人在場：「你們安靜，吵到我主人講話了」

## 技術棧
- **Bot 框架**: pycord
- **STT**: faster-whisper (tiny, CPU)
- **LLM**: DeepSeek-chat API（回答限制 ≤20 字）
- **TTS**: [VITS-Umamusume-voice-synthesizer](https://huggingface.co/spaces/Plachta/VITS-Umamusume-voice-synthesizer) (Hugging Face Spaces)
  - 內建上百個角色：賽馬娘全員、原神全員

## 快速開始
```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定環境
cp .env.example .env
# 編輯 .env 填入你的 Token 和 API Key

# 3. 生成打斷語音（可選）
python generate_too_noisy.py

# 4. 啟動
python bot.py
```

## 指令
| 指令 | 說明 |
|------|------|
| `/join` | Bot 加入你所在的語音頻道 |
| `/leave` | Bot 離開語音頻道 |
| `/set_voice <角色>` | 切換 TTS 角色（例如：`纳西妲 Nahida (Genshin Impact)`） |
| `/status` | 查看 Bot 狀態 |

## 環境變數 (.env)
```
DISCORD_TOKEN=你的BotToken
MY_USER_ID=你的DiscordUserID
DEEPSEEK_API_KEY=sk-你的DeepSeek金鑰
TTS_SPEAKER=纳西妲 Nahida (Genshin Impact)
TTS_LANGUAGE=简体中文
TTS_SPEED=1.0
```

## 可用角色
完整列表：https://huggingface.co/spaces/Plachta/VITS-Umamusume-voice-synthesizer

熱門角色舉例：
- `纳西妲 Nahida (Genshin Impact)` — 原神納西妲
- `胡桃 Hu Tao (Genshin Impact)` — 原神胡桃
- `雷电将军 Raiden Shogun (Genshin Impact)` — 原神雷電將軍
- `派蒙 Paimon (Genshin Impact)` — 原神派蒙
- `特别周 Special Week (Umamusume Pretty Derby)` — 賽馬娘特別週
- `东海帝王 Tokai Teio (Umamusume Pretty Derby)` — 賽馬娘東海帝王
