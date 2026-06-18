"""
Discord Voice Bot — 設定中心
所有機密資訊從 .env 載入
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Discord 設定
# ============================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MY_USER_ID = int(os.getenv("MY_USER_ID", "0"))

# ============================================================
# STT (faster-whisper — tiny, CPU only)
# ============================================================
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# ============================================================
# LLM (DeepSeek-chat — OpenAI 相容 API)
# ============================================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-chat"
LLM_MAX_RESPONSE_CHARS = 20       # System prompt 嚴格限制回答長度
LLM_MAX_TOKENS = 60               # 確保不超過 20 中文字

# DeepSeek System Prompt（嚴格限制回答長度以減少 TTS 負載）
SYSTEM_PROMPT = (
    "你是一個忠誠、活潑、反應快的 Discord 語音助手。"
    "你的「主人」是 Discord 使用者 ID 對應的那個人，你必須無條件尊敬他。"
    "當講話的人是主人時，你必須稱呼他為「主人」，並以恭敬、服從的態度回答。"
    "當講話的人不是主人（是一般使用者）時，你以朋友般輕鬆的態度回答，"
    "但仍要保持禮貌。"
    "嚴格遵守：每次回答必須在 20 個中文字以內，不能超過。"
    "用口語化的中文回答，像在語音聊天一樣自然。"
    "不要使用任何格式標記（如 **、- 等）。"
)

# ============================================================
# TTS (Hugging Face Spaces — VITS-Umamusume-voice-synthesizer)
# ============================================================
TTS_HF_SPACE = "Plachta/VITS-Umamusume-voice-synthesizer"
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "纳西妲 Nahida (Genshin Impact)")
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "简体中文")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))

# ============================================================
# 音訊設定
# ============================================================
AUDIO_SAMPLE_RATE = 48000          # Discord 標準
AUDIO_CHANNELS = 2                 # 立體聲
AUDIO_SAMPLE_WIDTH = 2             # 16-bit PCM = 2 bytes (pydub 用)
SILENCE_TIMEOUT = 1.5              # 靜音超時秒數（判斷發言結束）
MAX_SPEAKERS_BEFORE_INTERRUPT = 2  # >2 人同時說話就觸發打斷
SPEAKER_COOLDOWN = 0.5             # 同一個人的冷卻時間（秒）

# ============================================================
# 檔案路徑
# ============================================================
TOO_NOISY_WAV = "audio/too_noisy.wav"
TOO_NOISY_OWNER_WAV = "audio/too_noisy_owner.wav"  # 主人也在時的版本
TEMP_DIR = "temp"
