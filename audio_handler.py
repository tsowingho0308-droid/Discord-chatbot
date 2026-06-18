"""
音訊處理模組 — 自訂 Pycord Sink
- 過濾擁有者聲音
- 多說話者追蹤與防吵鬧打斷
- 靜音偵測（發言結束判斷）
"""
import time
import logging
import discord
from config import MY_USER_ID, MAX_SPEAKERS_BEFORE_INTERRUPT, SPEAKER_COOLDOWN

logger = logging.getLogger(__name__)


class FilteringWaveSink(discord.sinks.WaveSink):
    """
    繼承 pycord 內建 WaveSink，覆寫 write() 實現：
    1. 丟棄擁有者的音訊（不聽你說話）
    2. 即時追蹤活躍說話者數量
    3. 超過閾值時觸發「太吵了」打斷旗標
    """

    def __init__(self, *, filters=None, **kwargs):
        super().__init__(filters=filters, **kwargs)
        self.owner_id = MY_USER_ID
        self.max_speakers = MAX_SPEAKERS_BEFORE_INTERRUPT
        self.cooldown = SPEAKER_COOLDOWN

        # 說話者時間戳 (user_id → last_spoke_time)
        self.speaker_timestamps: dict[int, float] = {}
        # 是否觸發打斷
        self.interrupted = False
        # 最後收到有效音訊的時間（用於靜音偵測）
        self.last_audio_time: float = time.time()

    def write(self, data, user):
        """
        Pycord 每 20ms 呼叫一次，傳入 Opus 解碼後的 PCM 資料和說話者。
        回傳 None 表示丟棄此音訊；否則呼叫父類寫入。
        """
        # 無效使用者 → 跳過
        if user is None:
            return

        # 過濾擁有者 — Bot 不聽你說話
        if user.id == self.owner_id:
            return

        now = time.time()

        # 更新說話者時間戳
        self.speaker_timestamps[user.id] = now
        self.last_audio_time = now

        # 清理過期的時間戳（超過 cooldown 的視為已停止說話）
        active = sum(
            1 for ts in self.speaker_timestamps.values()
            if now - ts < self.cooldown
        )

        # 超過閾值 → 觸發打斷旗標，丟棄此音訊
        if active > self.max_speakers:
            if not self.interrupted:
                logger.info(
                    "⚠ 偵測到多人同時說話 (active=%d > max=%d)，觸發打斷",
                    active, self.max_speakers,
                )
                self.interrupted = True
            return

        # 正常寫入父類緩衝區
        super().write(data, user)

    def reset_interrupt(self):
        """重置打斷旗標和說話者記錄（用於下一個聆聽週期）"""
        self.interrupted = False
        self.speaker_timestamps.clear()
        self.last_audio_time = time.time()

    def get_active_speakers_count(self) -> int:
        """取得目前活躍說話者數量"""
        now = time.time()
        return sum(
            1 for ts in self.speaker_timestamps.values()
            if now - ts < self.cooldown
        )
