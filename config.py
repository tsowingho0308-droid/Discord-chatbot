"""
Discord Voice Bot — 設定中心
所有機密資訊從 .env 載入
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# 輔助函式 — 檢查 .env 是否已正確填寫
# ============================================================
def _require_env(key: str) -> str:
    """讀取環境變數，若未設定或還是範本值則報錯退出"""
    value = os.getenv(key, "")
    if not value or value.startswith("your_"):
        print(f"\n{'='*60}")
        print(f"❌ .env 設定錯誤：{key} 尚未填寫")
        print(f"   請編輯專案根目錄的 .env 檔案")
        print(f"   把 {key}=your_xxx 換成你的真實資料")
        print(f"{'='*60}\n")
        sys.exit(1)
    return value


def _require_int(key: str) -> int:
    """讀取並轉為整數，無法轉換則報錯"""
    raw = _require_env(key)
    try:
        return int(raw)
    except ValueError:
        print(f"\n{'='*60}")
        print(f"❌ .env 設定錯誤：{key} 必須是純數字")
        print(f"   目前的值: {raw}")
        print(f"   Discord User ID 是 17-19 位數字，在 Discord 設定中可找到")
        print(f"{'='*60}\n")
        sys.exit(1)


# ============================================================
# Discord 設定
# ============================================================
DISCORD_TOKEN = _require_env("DISCORD_TOKEN")
MY_USER_ID = _require_int("MY_USER_ID")

# ============================================================
# STT (faster-whisper — tiny, CPU only)
# ============================================================
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# ============================================================
# LLM (DeepSeek-chat — OpenAI 相容 API)
# ============================================================
DEEPSEEK_API_KEY = _require_env("DEEPSEEK_API_KEY")
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
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "待兼诗歌剧 Matikane Tannhauser (Umamusume Pretty Derby)")
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "简体中文")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.0"))

# ============================================================
# 音訊設定
# ============================================================
AUDIO_SAMPLE_RATE = 48000          # Discord / PyAudio 通用
AUDIO_CHANNELS = 2
AUDIO_SAMPLE_WIDTH = 2             # 16-bit PCM
SILENCE_TIMEOUT = 1.5              # 靜音超時（秒）
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "400"))      # VAD 音量閾值
NOISE_THRESHOLD = int(os.getenv("NOISE_THRESHOLD", "3000"))         # 多人吵雜閾值
AUDIO_CAPTURE_DEVICE = os.getenv("AUDIO_CAPTURE_DEVICE")            # None=預設裝置
if AUDIO_CAPTURE_DEVICE is not None:
    AUDIO_CAPTURE_DEVICE = int(AUDIO_CAPTURE_DEVICE)

# ============================================================
# 檔案路徑
# ============================================================
TOO_NOISY_WAV = "audio/too_noisy.wav"
TOO_NOISY_OWNER_WAV = "audio/too_noisy_owner.wav"  # 主人也在時的版本
TEMP_DIR = "temp"
