"""
STT 模組 — 使用 faster-whisper (tiny, CPU only) 將語音轉為文字
"""
import logging
from faster_whisper import WhisperModel
from config import WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

logger = logging.getLogger(__name__)


class STTEngine:
    """語音轉文字引擎 — faster-whisper tiny 模型"""

    def __init__(self):
        logger.info(
            "載入 faster-whisper 模型: size=%s, device=%s, compute=%s",
            WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
        )
        self.model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info("faster-whisper 模型載入完成")

    def transcribe(self, wav_path: str) -> str:
        """
        將 WAV 檔案轉為文字。
        回傳辨識結果字串；若失敗或無內容則回傳空字串。
        """
        try:
            segments, _ = self.model.transcribe(
                wav_path,
                language="zh",
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text)
            logger.info("STT 辨識結果: %s", text)
            return text
        except Exception as e:
            logger.error("STT 辨識失敗: %s", e)
            return ""
