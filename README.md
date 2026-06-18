# Discord Voice Chatbot

Discord 語音 Bot，具備雙向語音互動能力。

## 功能
- 加入 Discord 語音頻道，監聽其他人發言
- STT（語音轉文字）→ LLM（DeepSeek-chat 思考）→ TTS（文字轉語音）→ 播放回頻道
- 忽略擁有者的聲音
- 多人同時說話時自動打斷：「太吵了，一個一個說」

## 技術棧
- **Bot 框架**: pycord
- **STT**: faster-whisper (tiny, CPU)
- **LLM**: DeepSeek-chat API
- **TTS**: GPT-SoVITS (Google Colab)

## 快速開始
1. 複製 `.env.example` 為 `.env`，填入設定值
2. `pip install -r requirements.txt`
3. `python bot.py`

## 指令
- `/join` — Bot 加入你所在的語音頻道
- `/leave` — Bot 離開語音頻道
