"""
Discord Voice Bot — 主程式入口
功能：加入語音頻道 → 監聽 → STT → DeepSeek → TTS → 播放
"""
import asyncio
import time
import os
import sys
import logging
import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    MY_USER_ID,
    SILENCE_TIMEOUT,
    TOO_NOISY_WAV,
    TOO_NOISY_OWNER_WAV,
    TEMP_DIR,
    TTS_CHARACTER,
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

# 降低 discord 內部 log 噪音
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
                callback=lambda s: None,  # 我們自行處理 sink
            )
            logger.debug("開始錄音週期")

            # -------- 2. 等待觸發條件（靜音 或 打斷）--------
            while True:
                await asyncio.sleep(0.3)

                # 檢查是否已斷線
                if not vc.is_connected():
                    break

                # 檢查打斷旗標
                if sink.interrupted:
                    logger.info("觸發打斷：多人同時說話")
                    break

                # 檢查靜音超時（有人在說話後停止）
                elapsed = time.time() - sink.last_audio_time
                if elapsed > SILENCE_TIMEOUT and len(sink.audio_data) > 0:
                    logger.info("偵測到靜音超時 (%.1fs)，處理語音", elapsed)
                    break

            # 如果已斷線則結束
            if not vc.is_connected():
                vc.stop_recording()
                break

            # -------- 3. 停止錄音 --------
            vc.stop_recording()

            # -------- 4. 處理階段 --------
            if sink.interrupted:
                # 打斷機制：根據主人是否在場選擇不同語音
                if sink.owner_involved:
                    logger.info("播放主人版打斷語音: 「你們安靜，吵到我主人講話了」")
                    await play_audio_file(vc, TOO_NOISY_OWNER_WAV)
                else:
                    logger.info("播放一般打斷語音: 「太吵了，一個一個說」")
                    await play_audio_file(vc, TOO_NOISY_WAV)
            else:
                # 正常流程：處理每位說話者的音訊
                await process_audio(sink, vc, channel_id)

        except Exception as e:
            logger.error("語音循環發生錯誤: %s", e, exc_info=True)
            await asyncio.sleep(0.5)  # 避免錯誤時瘋狂重試

    _active_loops.pop(guild_id, None)
    logger.info("語音循環結束: guild_id=%d", guild_id)


# ============================================================
# 音訊處理管線
# ============================================================
async def process_audio(
    sink: FilteringWaveSink,
    vc: discord.VoiceClient,
    channel_id: int,
):
    """
    管線：WAV 檔 → STT → LLM → TTS → 播放
    處理所有使用者音訊（包含主人）
    主人說話時 → LLM 以恭敬態度回答，稱呼「主人」
    """
    if not sink.audio_data:
        logger.debug("無音訊資料，跳過")
        return

    for user_id, audio_data in sink.audio_data.items():
        if not audio_data.file or audio_data.file.getbuffer().nbytes == 0:
            continue

        try:
            # ---- 寫入暫存 WAV ----
            timestamp = int(time.time() * 1000)
            wav_path = os.path.join(TEMP_DIR, f"user_{user_id}_{timestamp}.wav")
            with open(wav_path, "wb") as f:
                audio_data.file.seek(0)
                f.write(audio_data.file.read())
            logger.info("已儲存音訊: %s (%d bytes)", wav_path, os.path.getsize(wav_path))

            # ---- STT ----
            text = stt_engine.transcribe(wav_path)
            if not text:
                logger.info("STT 結果為空，跳過")
                continue

            # ---- LLM (辨識是否為主人，傳入對應態度) ----
            is_owner = (user_id == MY_USER_ID)
            if is_owner:
                logger.info("🎩 主人說話，使用恭敬模式")
            reply = await llm_engine.chat(text, channel_id, is_owner=is_owner)
            if not reply:
                logger.info("LLM 回覆為空，跳過 TTS")
                continue

            # ---- TTS ----
            tts_out = os.path.join(TEMP_DIR, "tts_output.wav")
            ok = tts_engine.synthesize(reply, tts_out)
            if not ok:
                logger.warning("TTS 失敗，跳過播放")
                continue

            # ---- 播放 ----
            await play_audio_file(vc, tts_out)

        except Exception as e:
            logger.error("處理音訊時發生錯誤 (user_id=%d): %s", user_id, e, exc_info=True)

        finally:
            # 清理暫存 WAV
            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass


# ============================================================
# 播放輔助函式
# ============================================================
async def play_audio_file(vc: discord.VoiceClient, file_path: str):
    """使用 FFmpeg 播放音訊檔案，等待播放完成"""
    if not os.path.exists(file_path):
        logger.warning("播放檔案不存在: %s", file_path)
        return

    if vc.is_playing():
        vc.stop()  # 中斷當前播放

    try:
        source = discord.FFmpegPCMAudio(file_path)
        vc.play(source)

        # 等待播放結束
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
    logger.info("主人 ID (特殊態度對象): %d", MY_USER_ID)

    # 初始化 STT 引擎（首次載入會下載 tiny 模型）
    logger.info("正在載入 faster-whisper 模型...")
    try:
        stt_engine = STTEngine()
        logger.info("STT 引擎就緒")
    except Exception as e:
        logger.error("STT 引擎初始化失敗: %s", e)
        sys.exit(1)

    # 初始化 LLM 引擎
    try:
        llm_engine = LLMEngine()
        logger.info("LLM 引擎就緒")
    except Exception as e:
        logger.error("LLM 引擎初始化失敗: %s", e)
        sys.exit(1)

    # 初始化 TTS 引擎
    try:
        tts_engine = TTSEngine()
        logger.info("TTS 引擎就緒: %s", tts_engine.api_url)
    except Exception as e:
        logger.error("TTS 引擎初始化失敗: %s", e)
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("✅ 所有引擎就緒，等待指令...")
    logger.info("   使用 /join 讓 Bot 加入語音頻道")


@bot.event
async def on_voice_state_update(member, before, after):
    """語音狀態更新 — 當 Bot 被踢出頻道時清理"""
    if member.id != bot.user.id:
        return
    if before.channel and not after.channel:
        # Bot 被踢出或移動到無頻道狀態
        guild_id = member.guild.id
        _active_loops[guild_id] = False
        logger.info("Bot 已離開語音頻道，清理狀態: guild_id=%d", guild_id)


# ============================================================
# 指令: /join
# ============================================================
@bot.slash_command(name="join", description="讓 Bot 加入你所在的語音頻道並開始監聽")
async def cmd_join(ctx: discord.ApplicationContext):
    """加入語音頻道"""
    # 檢查使用者是否在語音頻道中
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.respond("❌ 你必須先加入一個語音頻道！", ephemeral=True)
        return

    channel = ctx.author.voice.channel

    # 檢查 Bot 是否已在語音頻道中
    if ctx.voice_client is not None:
        # 已在某個頻道中
        if ctx.voice_client.channel.id == channel.id:
            await ctx.respond(f"⚠ 我已經在 `{channel.name}` 了！", ephemeral=True)
        else:
            await ctx.voice_client.move_to(channel)
            await ctx.respond(f"🔊 已移動到 `{channel.name}`")
        return

    # 連接到語音頻道
    try:
        vc = await channel.connect()
    except Exception as e:
        logger.error("無法連接到語音頻道: %s", e)
        await ctx.respond(f"❌ 無法連線: {e}", ephemeral=True)
        return

    await ctx.respond(f"🔊 已加入 `{channel.name}`，開始監聽！")

    # 啟動語音處理循環（非同步背景執行）
    asyncio.create_task(voice_loop(vc, channel.id))


# ============================================================
# 指令: /leave
# ============================================================
@bot.slash_command(name="leave", description="讓 Bot 離開語音頻道")
async def cmd_leave(ctx: discord.ApplicationContext):
    """離開語音頻道"""
    vc = ctx.voice_client

    if vc is None:
        await ctx.respond("❌ Bot 目前不在任何語音頻道中", ephemeral=True)
        return

    # 停止語音循環
    guild_id = ctx.guild.id
    _active_loops[guild_id] = False

    # 停止錄音
    if vc.recording:
        vc.stop_recording()

    # 中斷播放
    if vc.is_playing():
        vc.stop()

    # 斷線
    await vc.disconnect()

    # 清除對話歷史
    if llm_engine:
        llm_engine.clear_history(ctx.channel.id)

    await ctx.respond("👋 已離開語音頻道")


# ============================================================
# 指令: /set_voice
# ============================================================
@bot.slash_command(name="set_voice", description="切換 TTS 音色")
async def cmd_set_voice(
    ctx: discord.ApplicationContext,
    character: discord.Option(str, "GPT-SoVITS 音色名稱", default="default"),
):
    """切換 TTS 音色"""
    if tts_engine is None:
        await ctx.respond("❌ TTS 引擎尚未初始化", ephemeral=True)
        return

    tts_engine.update_character(character)
    await ctx.respond(f"🎤 TTS 音色已切換為 `{character}`")


# ============================================================
# 指令: /status
# ============================================================
@bot.slash_command(name="status", description="查看 Bot 目前狀態")
async def cmd_status(ctx: discord.ApplicationContext):
    """顯示 Bot 狀態"""
    vc = ctx.voice_client
    voice_status = "未連接"
    if vc and vc.is_connected():
        voice_status = f"在 `{vc.channel.name}`"
        if vc.recording:
            voice_status += " (錄音中)"

    tts_char = tts_engine.character if tts_engine else "未初始化"

    msg = (
        f"**Bot 狀態**\n"
        f"• 語音頻道: {voice_status}\n"
        f"• TTS 音色: `{tts_char}`\n"
        f"• LLM: `deepseek-chat`\n"
        f"• STT: `faster-whisper tiny (CPU)`\n"
        f"• 主人 ID: `{MY_USER_ID}` (特殊態度 + 打斷優先)\n"
    )
    await ctx.respond(msg, ephemeral=True)


# ============================================================
# 啟動
# ============================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.error("❌ DISCORD_TOKEN 未設定！請在 .env 檔案中設定")
        sys.exit(1)
    if MY_USER_ID == 0:
        logger.warning("⚠ MY_USER_ID 未設定或為 0，Bot 將無法辨識主人！")

    logger.info("啟動 Discord Bot...")
    bot.run(DISCORD_TOKEN)
