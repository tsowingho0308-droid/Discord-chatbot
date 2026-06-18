"""
TTS 模組 — Hugging Face Spaces 上的 VITS-Umamusume-voice-synthesizer
透過 gradio_client 直接呼叫，內建上百個角色（賽馬娘 + 原神 + 更多）

切換角色：改 .env 的 TTS_SPEAKER，或 Discord 內用 /set_voice
完整角色列表：https://huggingface.co/spaces/Plachta/VITS-Umamusume-voice-synthesizer
"""
import os
import shutil
import logging
from gradio_client import Client, handle_file
from config import TTS_HF_SPACE, TTS_SPEAKER, TTS_LANGUAGE, TTS_SPEED

logger = logging.getLogger(__name__)


class TTSEngine:
    """文字轉語音引擎 — VITS 模型 (Hugging Face Spaces)"""

    def __init__(self):
        logger.info("正在連線到 Hugging Face Space: %s", TTS_HF_SPACE)
        self.client = Client(TTS_HF_SPACE)
        self.speaker = TTS_SPEAKER
        self.language = TTS_LANGUAGE
        self.speed = TTS_SPEED
        logger.info(
            "TTS 引擎就緒: speaker=%s, language=%s, speed=%.1f",
            self.speaker, self.language, self.speed,
        )

    def update_character(self, speaker: str):
        """切換 TTS 說話者（角色）"""
        self.speaker = speaker
        logger.info("TTS 角色已切換為: %s", speaker)

    def synthesize(self, text: str, output_path: str) -> bool:
        """
        將文字送入 VITS API，下載產生的 WAV 到 output_path。
        回傳 True 表示成功，False 表示失敗。
        """
        if not text:
            logger.warning("TTS 輸入文字為空，跳過")
            return False

        try:
            logger.info(
                "TTS 請求: text='%s', speaker=%s, lang=%s, speed=%.1f",
                text, self.speaker, self.language, self.speed,
            )

            # 呼叫 Hugging Face Gradio API
            result = self.client.predict(
                text=text,
                speaker=self.speaker,
                language=self.language,
                speed=self.speed,
                is_symbol=False,
                api_name="/tts_fn",
            )

            # result 是 tuple: (message_str, filepath_str)
            # filepath 是 gradio_client 自動下載到本機暫存的路徑
            message, tmp_path = result

            if tmp_path and os.path.exists(tmp_path):
                shutil.copy2(tmp_path, output_path)
                size = os.path.getsize(output_path)
                logger.info("TTS 成功: WAV 已寫入 %s (%d bytes)", output_path, size)
                return True
            else:
                logger.error("TTS 回傳的檔案不存在: %s, message=%s", tmp_path, message)
                return False

        except Exception as e:
            logger.error("TTS 呼叫失敗: %s", e)
            return False
