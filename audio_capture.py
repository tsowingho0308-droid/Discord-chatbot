"""
系統音訊擷取模組 — 使用 PyAudio 從系統音效卡抓取喇叭輸出
繞過 Discord DAVE E2EE，不依賴 Discord API 錄音。

- 語音活動偵測 (VAD) — 基於音量能量
- 靜音分段 — 自動切出每段發言
- 多人吵雜檢測 — 能量異常暴增時觸發打斷
- 支援 VB-Cable / Stereo Mix / 實體線路輸入

使用前請先設定音效裝置：執行 list_devices() 查看可用裝置
"""
import time
import wave
import struct
import threading
import logging
from queue import Queue
from pathlib import Path

import numpy as np
import pyaudio

from config import (
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_WIDTH,
    SILENCE_TIMEOUT,
)

logger = logging.getLogger(__name__)


class SystemAudioCapture:
    """
    從系統音效卡擷取喇叭輸出（需搭配 VB-Cable 或 Stereo Mix）。
    背景執行緒持續監聽，自動分段並透過 callback 通知。
    """

    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int = AUDIO_SAMPLE_RATE,
        chunk: int = 1024,
        silence_threshold: int = 400,
        noise_threshold: int = 3000,
        silence_timeout: float = SILENCE_TIMEOUT,
    ):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.chunk = chunk
        self.silence_threshold = silence_threshold
        self.noise_threshold = noise_threshold
        self.silence_timeout = silence_timeout

        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._thread: threading.Thread | None = None
        self._running = False

        # 錄音狀態
        self._frames: list[bytes] = []
        self._recording = False
        self._last_voice_time = 0.0
        self._silence_start = 0.0

        # 輸出佇列：存放 (wav_path, energy_level) 或 ("interrupt",)
        self.output_queue: Queue = Queue()

        self._lock = threading.Lock()

    # ----------------------------------------------------------
    # 裝置查詢
    # ----------------------------------------------------------
    @staticmethod
    def list_devices():
        """列出所有可用的輸入裝置（含虛擬裝置）"""
        pa = pyaudio.PyAudio()
        print("\n可用的輸入裝置：")
        print("-" * 60)
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                print(f"  [{i}] {info['name']}")
                print(f"       取樣率: {int(info['defaultSampleRate'])} Hz, "
                      f"聲道: {info['maxInputChannels']}")
        print("-" * 60)
        pa.terminate()

    # ----------------------------------------------------------
    # 啟動 / 停止
    # ----------------------------------------------------------
    def start(self):
        """啟動背景監聽執行緒"""
        if self._running:
            return
        self._running = True
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk,
            stream_callback=self._audio_callback,
        )
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(
            "系統音訊擷取已啟動: device=%d, rate=%d, threshold=%d",
            self.device_index or 0, self.sample_rate, self.silence_threshold,
        )

    def stop(self):
        """停止監聽"""
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._thread:
            self._thread.join(timeout=2)
        self._pa.terminate()
        logger.info("系統音訊擷取已停止")

    # ----------------------------------------------------------
    # PyAudio 回呼（在背景執行緒中執行）
    # ----------------------------------------------------------
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio 串流回呼 — 每 chunk 觸發一次"""
        if not self._running:
            return (None, pyaudio.paAbort)

        try:
            samples = np.frombuffer(in_data, dtype=np.int16)
            energy = int(np.abs(samples).mean())

            with self._lock:
                now = time.time()

                # ---- 多人吵雜檢測 ----
                if energy > self.noise_threshold and not self._recording:
                    self.output_queue.put(("interrupt",))
                    return (in_data, pyaudio.paContinue)

                # ---- 語音活動 ----
                if energy > self.silence_threshold:
                    if not self._recording:
                        self._recording = True
                        self._frames = []
                        logger.debug("語音開始 (energy=%d)", energy)
                    self._frames.append(in_data)
                    self._last_voice_time = now
                else:
                    # 靜音中
                    if self._recording:
                        self._frames.append(in_data)  # 保留短暫靜音
                        # 檢查是否該切段
                        if now - self._last_voice_time > self.silence_timeout:
                            self._save_and_enqueue()
                            self._recording = False
                            self._frames = []

        except Exception as e:
            logger.error("音訊回呼錯誤: %s", e)

        return (in_data, pyaudio.paContinue)

    # ----------------------------------------------------------
    # 儲存 WAV 並放入佇列
    # ----------------------------------------------------------
    def _save_and_enqueue(self):
        """將累積的音訊幀儲存為 WAV，放入輸出佇列"""
        if not self._frames:
            return

        Path("temp").mkdir(exist_ok=True)
        timestamp = int(time.time() * 1000)
        wav_path = f"temp/capture_{timestamp}.wav"

        try:
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"".join(self._frames))

            size = len(b"".join(self._frames))
            logger.info("語音片段已儲存: %s (%d bytes)", wav_path, size)
            self.output_queue.put(("speech", wav_path))
        except Exception as e:
            logger.error("儲存 WAV 失敗: %s", e)

    # ----------------------------------------------------------
    # 監控循環（主執行緒用）
    # ----------------------------------------------------------
    def _monitor_loop(self):
        """保持串流活躍，直到停止"""
        while self._running:
            time.sleep(0.1)

    def get_next(self, timeout: float = 0.1):
        """非阻塞取得下一個事件，回傳 ("speech", path) 或 ("interrupt",) 或 None"""
        try:
            return self.output_queue.get(timeout=timeout)
        except Exception:
            return None
