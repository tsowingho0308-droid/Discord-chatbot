"""
TTS 模組 — 發送 POST 請求到 Google Colab 上運行的 GPT-SoVITS API
下載回傳的 WAV 檔案
"""
import logging
import requests
from config import TTS_API_URL, TTS_CHARACTER

logger = logging.getLogger(__name__)


class TTSEngine:
    """文字轉語音引擎 — GPT-SoVITS (遠端 Colab)"""

    def __init__(self):
        self.api_url = TTS_API_URL.rstrip("/")
        self.character = TTS_CHARACTER
        logger.info("TTS 引擎初始化完成: api_url=%s, character=%s", self.api_url, self.character)

    def update_character(self, character: str):
        """切換 TTS 音色"""
        self.character = character
        logger.info("TTS 音色已切換為: %s", character)

    def synthesize(self, text: str, output_path: str) -> bool:
        """
        將文字透過 POST 發送到 GPT-SoVITS API，下載 WAV 到 output_path。
        回傳 True 表示成功，False 表示失敗。
        """
        if not text:
            logger.warning("TTS 輸入文字為空，跳過")
            return False

        url = f"{self.api_url}/tts"
        payload = {
            "text": text,
            "character": self.character,
        }

        try:
            logger.info("TTS 請求: text='%s', character=%s", text, self.character)
            resp = requests.post(url, json=payload, timeout=30)

            if resp.status_code == 200:
                # GPT-SoVITS 直接回傳 WAV 二進位資料
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                logger.info("TTS 成功: WAV 已寫入 %s (%d bytes)", output_path, len(resp.content))
                return True
            else:
                logger.error(
                    "TTS API 回傳錯誤: status=%d, body=%s",
                    resp.status_code, resp.text[:200],
                )
                return False

        except requests.exceptions.Timeout:
            logger.error("TTS API 請求超時")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("TTS API 連線失敗: 無法連線到 %s", url)
            return False
        except Exception as e:
            logger.error("TTS 發生未預期錯誤: %s", e)
            return False
