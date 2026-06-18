"""
LLM 模組 — DeepSeek-chat API (OpenAI 相容格式)
System prompt 嚴格限制回答 ≤ 20 中文字
"""
import logging
from openai import AsyncOpenAI
from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class LLMEngine:
    """DeepSeek-chat 大腦引擎"""

    def __init__(self):
        if not DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY 未設定，請檢查 .env 檔案")

        self.client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        self.model = LLM_MODEL
        # 每個語音頻道獨立的對話歷史
        self._histories: dict[int, list[dict]] = {}
        logger.info("LLM 引擎初始化完成: model=%s, base_url=%s", LLM_MODEL, DEEPSEEK_BASE_URL)

    def _get_history(self, channel_id: int) -> list[dict]:
        """取得指定頻道的對話歷史，若無則建立"""
        if channel_id not in self._histories:
            self._histories[channel_id] = []
        return self._histories[channel_id]

    def clear_history(self, channel_id: int):
        """清除指定頻道的對話歷史"""
        self._histories.pop(channel_id, None)

    async def chat(self, user_text: str, channel_id: int = 0) -> str:
        """
        將使用者文字送入 DeepSeek-chat，取得回覆。
        回覆限制在 20 中文字以內。
        """
        history = self._get_history(channel_id)

        # 建立訊息列表：system prompt + 歷史 + 當前輸入
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=LLM_MAX_TOKENS,
                temperature=0.8,
            )
            reply = response.choices[0].message.content.strip()
            logger.info("LLM 回覆 (%d 字): %s", len(reply), reply)

            # 更新對話歷史（保留最近 10 輪）
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 20:  # 10 輪 = 20 條訊息
                self._histories[channel_id] = history[-20:]

            return reply

        except Exception as e:
            logger.error("LLM API 呼叫失敗: %s", e)
            return ""
