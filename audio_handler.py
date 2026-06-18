"""
音訊處理模組 — 自訂 Pycord Sink
- 監聽所有使用者（包含主人），不丟棄任何音訊
- 追蹤主人是否正在說話
- 多說話者追蹤與防吵鬧打斷（區分主人是否在場）
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
    1. 追蹤主人是否正在說話（用於後續以「主人」稱呼）
    2. 即時追蹤活躍說話者數量
    3. 超過閾值時觸發打斷旗標，並區分主人是否在場
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
        # 打斷時主人是否在場（用於選擇播放哪個打斷語音）
        self.owner_involved = False
        # 主人是否在本週期有說話
        self.owner_has_spoken = False
        # 最後收到有效音訊的時間（用於靜音偵測）
        self.last_audio_time: float = time.time()

    def write(self, data, user):
        """
        Pycord 每 20ms 呼叫一次，傳入 Opus 解碼後的 PCM 資料和說話者。
        不丟棄任何人的音訊，但追蹤主人狀態。
        """
        # 無效使用者 → 跳過
        if user is None:
            return

        now = time.time()

        # 追蹤主人是否正在說話
        if user.id == self.owner_id:
            self.owner_has_spoken = True

        # 更新說話者時間戳
        self.speaker_timestamps[user.id] = now
        self.last_audio_time = now

        # 計算活躍說話者數量（包含主人）
        active = sum(
            1 for ts in self.speaker_timestamps.values()
            if now - ts < self.cooldown
        )

        # 超過閾值 → 觸發打斷旗標
        if active > self.max_speakers:
            if not self.interrupted:
                # 檢查主人是否在活躍說話者中
                owner_active = (
                    self.owner_id in self.speaker_timestamps
                    and now - self.speaker_timestamps[self.owner_id] < self.cooldown
                )
                self.owner_involved = owner_active
                if owner_active:
                    logger.info(
                        "⚠ 多人同時說話 (active=%d)，主人也在說話者中！",
                        active,
                    )
                else:
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
        self.owner_involved = False
        self.owner_has_spoken = False
        self.speaker_timestamps.clear()
        self.last_audio_time = time.time()

    def get_active_speakers_count(self) -> int:
        """取得目前活躍說話者數量"""
        now = time.time()
        return sum(
            1 for ts in self.speaker_timestamps.values()
            if now - ts < self.cooldown
        )

    def is_owner(self, user_id: int) -> bool:
        """檢查指定 user_id 是否為主人"""
        return user_id == self.owner_id
