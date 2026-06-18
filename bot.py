"""
Discord Voice Bot — 主程式入口 (discord.py 2.4+)
功能：加入語音頻道 → 監聽 → STT → DeepSeek → TTS → 播放
"""
from __future__ import annotations
import asyncio
import time
import os
import sys
import logging
import discord
from discord.ext import commands
from discord import app_commands

from config import (
    DISCORD_TOKEN,
    MY_USER_ID,
    SILENCE_TIMEOUT,
    TOO_NOISY_WAV,
    TOO_NOISY_OWNER_WAV,
    TEMP_DIR,
    TTS_SPEAKER,
)
from audio_handler import FilteringWaveSink
from stt import STTEngine
from llm import LLMEngine
from tts import TTSEngine

# ============================================================
# Logging 設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")

logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

# ============================================================
# 目錄初始化
# ============================================================
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TOO_NOISY_WAV), exist_ok=True)

# ============================================================
# Bot 初始化
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="/", intents=intents)

# 全域引擎實例（在 on_ready 中初始化）
stt_engine: STTEngine | None = None
llm_engine: LLMEngine | None = None
tts_engine: TTSEngine | None = None

# 每個伺服器的語音 loop 控制旗標
_active_loops: dict[int, bool] = {}


# ============================================================
# 語音處理核心循環
# ============================================================
async def voice_loop(vc: discord.VoiceClient, channel_id: int):
    """
    語音處理主循環：
    錄音 → 等靜音/打斷 → 停止 → 處理 → 播放 → 重複
    """
    guild_id = vc.guild.id
    _active_loops[guild_id] = True
    logger.info("語音循環開始: guild_id=%d, channel_id=%d", guild_id, channel_id)

    while _active_loops.get(guild_id, False) and vc.is_connected():
        try:
            # -------- 1. 建立 Sink 並開始錄音 --------
            sink = FilteringWaveSink()
            vc.start_recording(
                sink,
                callback=lambda s: None,
            )
            logger.debug("開始錄音週期")

            # -------- 2. 等待觸發條件 --------
            while True:
                await asyncio.sleep(0.3)

                if not vc.is_connected():
                    break

                if sink.interrupted:
                    logger.info("觸發打斷：多人同時說話")
                    break

                elapsed = time.time() - sink.last_audio_time
                if elapsed > SILENCE_TIMEOUT and len(sink.audio_data) > 0:
                    logger.info("偵測到靜音超時 (%.1fs)，處理語音", elapsed)
                    break

            if not vc.is_connected():
                vc.stop_recording()
                break

            # -------- 3. 停止錄音 --------
            vc.stop_recording()

            # -------- 4. 處理階段 --------
            if sink.interrupted:
                if sink.owner_involved:
                    logger.info("播放主人版打斷語音")
                    await play_audio_file(vc, TOO_NOISY_OWNER_WAV)
                else:
                    logger.info("播放一般打斷語音")
                    await play_audio_file(vc, TOO_NOISY_WAV)
            else:
                await process_audio(sink, vc, channel_id)

        except Exception as e:
            logger.error("語音循環發生錯誤: %s", e, exc_info=True)
            await asyncio.sleep(0.5)

    _active_loops.pop(guild_id, None)
    logger.info("語音循環結束: guild_id=%d", guild_id)


# ============================================================
# 音訊處理管線（每次只回覆一人）
# ============================================================
async def process_audio(
    sink: FilteringWaveSink,
    vc: discord.VoiceClient,
    channel_id: int,
):
    """
    管線：WAV → STT → LLM → TTS → 播放
    每次只處理音量最大的一個人，避免多人混雜。
    AI 回覆期間不監聽，播放完才重新錄音。
    """
    if not sink.audio_data:
        logger.debug("無音訊資料，跳過")
        return

    # 只取音量最大的一個人
    def _size(item):
        _, ad = item
        return ad.file.getbuffer().nbytes if ad.file else 0

    sorted_users = sorted(sink.audio_data.items(), key=_size, reverse=True)
    user_id, top_audio = sorted_users[0]

    if not top_audio.file or top_audio.file.getbuffer().nbytes == 0:
        return

    skipped = len(sorted_users) - 1
    if skipped > 0:
        logger.info("多人同時說話，只處理 user_id=%d，跳過 %d 人", user_id, skipped)

    wav_path = None
    try:
        # ---- 寫入暫存 WAV ----
        timestamp = int(time.time() * 1000)
        wav_path = os.path.join(TEMP_DIR, f"user_{user_id}_{timestamp}.wav")
        with open(wav_path, "wb") as f:
            top_audio.file.seek(0)
            f.write(top_audio.file.read())
        logger.info("已儲存音訊: %s (%d bytes)", wav_path, os.path.getsize(wav_path))

        # ---- STT ----
        text = stt_engine.transcribe(wav_path)
        if not text:
            logger.info("STT 結果為空，跳過")
            return

        # ---- LLM ----
        is_owner = (user_id == MY_USER_ID)
        if is_owner:
            logger.info("🎩 主人說話，使用恭敬模式")
        reply = await llm_engine.chat(text, channel_id, is_owner=is_owner)
        if not reply:
            logger.info("LLM 回覆為空，跳過 TTS")
            return

        # ---- TTS ----
        tts_out = os.path.join(TEMP_DIR, "tts_output.wav")
        ok = tts_engine.synthesize(reply, tts_out)
        if not ok:
            logger.warning("TTS 失敗，跳過播放")
            return

        # ---- 播放 ----
        await play_audio_file(vc, tts_out)

    except Exception as e:
        logger.error("處理音訊錯誤 (user_id=%d): %s", user_id, e, exc_info=True)

    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass


# ============================================================
# 播放輔助函式
# ============================================================
async def play_audio_file(vc: discord.VoiceClient, file_path: str):
    """使用 FFmpeg 播放音訊，等待播放完成"""
    if not os.path.exists(file_path):
        logger.warning("播放檔案不存在: %s", file_path)
        return

    if vc.is_playing():
        vc.stop()

    try:
        source = discord.FFmpegPCMAudio(file_path)
        vc.play(source)
        while vc.is_playing():
            await asyncio.sleep(0.1)
        logger.info("播放完成: %s", file_path)
    except Exception as e:
        logger.error("播放失敗 (%s): %s", file_path, e)


# ============================================================
# Bot 事件
# ============================================================
@bot.event
async def on_ready():
    """Bot 啟動完成"""
    global stt_engine, llm_engine, tts_engine

    logger.info("=" * 50)
    logger.info("Bot 已上線: %s (ID: %d)", bot.user.name, bot.user.id)
    logger.info("主人 ID: %d", MY_USER_ID)

    # 初始化 STT
    logger.info("正在載入 faster-whisper 模型...")
    try:
        stt_engine = STTEngine()
        logger.info("STT 引擎就緒")
    except Exception as e:
        logger.error("STT 初始化失敗: %s", e)
        sys.exit(1)

    # 初始化 LLM
    try:
        llm_engine = LLMEngine()
        logger.info("LLM 引擎就緒")
    except Exception as e:
        logger.error("LLM 初始化失敗: %s", e)
        sys.exit(1)

    # 初始化 TTS
    try:
        tts_engine = TTSEngine()
        logger.info("TTS 引擎就緒: %s", tts_engine.speaker)
    except Exception as e:
        logger.error("TTS 初始化失敗: %s", e)
        sys.exit(1)

    # 同步 Slash 指令
    try:
        synced = await bot.tree.sync()
        logger.info("Slash 指令已同步: %d 個", len(synced))
    except Exception as e:
        logger.warning("Slash 指令同步失敗: %s", e)

    logger.info("=" * 50)
    logger.info("全部就緒！使用 /join 讓 Bot 加入語音頻道")


@bot.event
async def on_voice_state_update(member, before, after):
    """Bot 被踢出頻道時清理"""
    if member.id != bot.user.id:
        return
    if before.channel and not after.channel:
        guild_id = member.guild.id
        _active_loops[guild_id] = False
        logger.info("Bot 已離開語音頻道: guild_id=%d", guild_id)


# ============================================================
# 指令: /join
# ============================================================
@bot.tree.command(name="join", description="讓 Bot 加入你所在的語音頻道並開始監聽")
async def cmd_join(interaction: discord.Interaction):
    """加入語音頻道"""
    await interaction.response.defer(ephemeral=True)

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ 你必須先加入一個語音頻道！", ephemeral=True)
        return

    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is not None:
        if voice_client.channel.id == channel.id:
            await interaction.followup.send(f"⚠ 我已經在 `{channel.name}` 了！", ephemeral=True)
        else:
            await voice_client.move_to(channel)
            await interaction.followup.send(f"🔊 已移動到 `{channel.name}`")
        return

    try:
        vc = await channel.connect()
    except Exception as e:
        logger.error("無法連接到語音頻道: %s", e)
        await interaction.followup.send(f"❌ 無法連線: {e}", ephemeral=True)
        return

    await interaction.followup.send(f"🔊 已加入 `{channel.name}`，開始監聽！")
    asyncio.create_task(voice_loop(vc, channel.id))


# ============================================================
# 指令: /leave
# ============================================================
@bot.tree.command(name="leave", description="讓 Bot 離開語音頻道")
async def cmd_leave(interaction: discord.Interaction):
    """離開語音頻道"""
    await interaction.response.defer(ephemeral=True)

    vc = interaction.guild.voice_client

    if vc is None:
        await interaction.followup.send("❌ Bot 目前不在任何語音頻道中", ephemeral=True)
        return

    guild_id = interaction.guild_id
    _active_loops[guild_id] = False

    if vc.recording:
        vc.stop_recording()
    if vc.is_playing():
        vc.stop()

    await vc.disconnect()

    if llm_engine:
        llm_engine.clear_history(interaction.channel_id)

    await interaction.followup.send("👋 已離開語音頻道")


# ============================================================
# 指令: /set_voice
# ============================================================
@bot.tree.command(name="set_voice", description="切換 TTS 角色聲音")
@app_commands.describe(character="角色名稱，例如：纳西妲 Nahida (Genshin Impact)")
async def cmd_set_voice(interaction: discord.Interaction, character: str):
    """切換 TTS 角色"""
    if tts_engine is None:
        await interaction.response.send_message("❌ TTS 引擎尚未初始化", ephemeral=True)
        return

    tts_engine.update_character(character)
    await interaction.response.send_message(f"🎤 TTS 角色已切換為 `{character}`")


# ============================================================
# 指令: /status
# ============================================================
@bot.tree.command(name="status", description="查看 Bot 目前狀態")
async def cmd_status(interaction: discord.Interaction):
    """顯示 Bot 狀態"""
    vc = interaction.guild.voice_client if interaction.guild else None
    voice_status = "未連接"
    if vc and vc.is_connected():
        voice_status = f"在 `{vc.channel.name}`"
        if vc.recording:
            voice_status += " (錄音中)"

    tts_char = tts_engine.speaker if tts_engine else "未初始化"

    msg = (
        f"**Bot 狀態**\n"
        f"• 語音頻道: {voice_status}\n"
        f"• TTS 角色: `{tts_char}`\n"
        f"• LLM: `deepseek-chat`\n"
        f"• STT: `faster-whisper tiny (CPU)`\n"
        f"• 主人 ID: `{MY_USER_ID}`\n"
    )
    await interaction.response.send_message(msg, ephemeral=True)


# ============================================================
# 啟動
# ============================================================
if __name__ == "__main__":
    logger.info("啟動 Discord Bot...")
    bot.run(DISCORD_TOKEN)
