"""
Discord Voice Bot — 主程式入口
Bot 只負責語音播放，錄音透過 PyAudio 從系統音效卡擷取（繞過 Discord DAVE）。
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
import logging
import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    MY_USER_ID,
    SILENCE_THRESHOLD,
    NOISE_THRESHOLD,
    AUDIO_CAPTURE_DEVICE,
    AUDIO_SAMPLE_RATE,
    TOO_NOISY_WAV,
    TOO_NOISY_OWNER_WAV,
    TEMP_DIR,
    TTS_SPEAKER,
)
from audio_capture import SystemAudioCapture
from stt import STTEngine
from llm import LLMEngine
from tts import TTSEngine

# ============================================================
# Logging
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
# 目錄
# ============================================================
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(TOO_NOISY_WAV), exist_ok=True)

# ============================================================
# Bot
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)

stt_engine: STTEngine | None = None
llm_engine: LLMEngine | None = None
tts_engine: TTSEngine | None = None
audio_capture: SystemAudioCapture | None = None

_active_loops: dict[int, bool] = {}


# ============================================================
# 輔助 — 清空擷取佇列
# ============================================================
def _flush_capture_queue():
    """清空音訊擷取佇列，丟棄 AI 播放期間錄到的自己聲音"""
    if audio_capture is None:
        return
    flushed = 0
    while True:
        try:
            audio_capture.output_queue.get_nowait()
            flushed += 1
        except Exception:
            break
    if flushed:
        logger.debug("清空擷取佇列: 丟棄 %d 個片段", flushed)


# ============================================================
# 語音處理主循環（使用系統音訊擷取）
# ============================================================
async def voice_loop(vc: discord.VoiceClient, channel_id: int):
    """
    Bot 加入語音頻道後啟動，從系統音效卡持續擷取音訊。
    偵測到語音 → STT → LLM → TTS → 播放回頻道。
    AI 回覆期間不處理新音訊，播完才繼續。
    """
    global audio_capture
    guild_id = vc.guild.id
    _active_loops[guild_id] = True
    logger.info("語音循環開始: guild_id=%d (系統音訊擷取模式)", guild_id)

    # 啟動系統音訊擷取
    audio_capture = SystemAudioCapture(
        device_index=AUDIO_CAPTURE_DEVICE,
        sample_rate=AUDIO_SAMPLE_RATE,
        silence_threshold=SILENCE_THRESHOLD,
        noise_threshold=NOISE_THRESHOLD,
    )
    audio_capture.start()

    try:
        while _active_loops.get(guild_id, False) and vc.is_connected():
            # 用執行緒池包裝 blocking Queue.get()，避免卡住 asyncio 事件循環
            event = await asyncio.to_thread(audio_capture.get_next, timeout=0.3)

            if event is None:
                continue

            kind, *args = event

            if kind == "interrupt":
                # 多人吵雜 → 播放打斷語音
                logger.info("多人吵雜檢測，播放打斷語音")
                await play_audio_file(vc, TOO_NOISY_WAV)
                _flush_capture_queue()  # 清空播放期間錄到的自己聲音

            elif kind == "speech":
                wav_path = args[0]
                # 處理語音片段 → STT → LLM → TTS → 播放
                await process_captured_audio(vc, channel_id, wav_path)
                _flush_capture_queue()  # 清空 AI 講話期間錄到的自己聲音
                # 清理暫存
                if os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except OSError:
                        pass

    except Exception as e:
        logger.error("語音循環錯誤: %s", e, exc_info=True)
    finally:
        audio_capture.stop()
        audio_capture = None
        _active_loops.pop(guild_id, None)
        logger.info("語音循環結束: guild_id=%d", guild_id)


# ============================================================
# 處理擷取到的音訊片段
# ============================================================
async def process_captured_audio(vc: discord.VoiceClient, channel_id: int, wav_path: str):
    """單段語音：STT → LLM → TTS → 播放"""
    size = os.path.getsize(wav_path)
    if size < 2000:  # 太短，跳過
        logger.debug("音訊片段過短 (%d bytes)，跳過", size)
        return

    logger.info("處理音訊片段: %s (%d bytes)", wav_path, size)

    # ---- STT ----
    text = stt_engine.transcribe(wav_path)
    if not text:
        logger.info("STT 結果為空")
        return

    logger.info("STT: %s", text)

    # ---- LLM (無法辨識個別使用者，傳入一般模式) ----
    reply = await llm_engine.chat(text, channel_id, is_owner=False)
    if not reply:
        logger.info("LLM 回覆為空")
        return

    # ---- TTS ----
    tts_out = os.path.join(TEMP_DIR, "tts_output.wav")
    ok = await tts_engine.async_synthesize(reply, tts_out)
    if not ok:
        logger.warning("TTS 失敗")
        return

    # ---- 播放 ----
    await play_audio_file(vc, tts_out)


# ============================================================
# 播放輔助
# ============================================================
async def play_audio_file(vc: discord.VoiceClient, file_path: str):
    """使用 FFmpeg 播放音訊，等待完成"""
    if not os.path.exists(file_path):
        logger.warning("檔案不存在: %s", file_path)
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
        logger.error("播放失敗: %s", e)


# ============================================================
# Bot 事件
# ============================================================
@bot.event
async def on_ready():
    global stt_engine, llm_engine, tts_engine
    logger.info("=" * 50)
    logger.info("Bot 已上線: %s (ID: %d)", bot.user.name, bot.user.id)
    logger.info("模式: 系統音訊擷取（PyAudio）")

    try:
        stt_engine = STTEngine()
        logger.info("STT 就緒")
    except Exception as e:
        logger.error("STT 失敗: %s", e)
        sys.exit(1)
    try:
        llm_engine = LLMEngine()
        logger.info("LLM 就緒")
    except Exception as e:
        logger.error("LLM 失敗: %s", e)
        sys.exit(1)
    try:
        tts_engine = TTSEngine()
        logger.info("TTS 就緒: %s", tts_engine.speaker)
    except Exception as e:
        logger.error("TTS 失敗: %s", e)
        sys.exit(1)

    try:
        synced = await bot.tree.sync()
        logger.info("Slash 指令已同步: %d 個", len(synced))
    except Exception as e:
        logger.warning("指令同步失敗: %s", e)

    logger.info("=" * 50)
    logger.info("全部就緒！/join 加入頻道開始")


@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return
    if before.channel and not after.channel:
        _active_loops[member.guild.id] = False
        logger.info("Bot 已離開語音頻道")


# ============================================================
# /join
# ============================================================
@bot.slash_command(name="join", description="加入語音頻道並開始監聽（系統音訊擷取模式）")
async def cmd_join(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.followup.send("❌ 請先加入一個語音頻道", ephemeral=True)
        return

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None:
        if ctx.voice_client.channel.id == channel.id:
            await ctx.followup.send(f"⚠ 已經在 `{channel.name}` 了", ephemeral=True)
        else:
            await ctx.voice_client.move_to(channel)
            await ctx.followup.send(f"🔊 已移動到 `{channel.name}`")
        return

    try:
        vc = await channel.connect()
    except Exception as e:
        logger.error("語音連線失敗: %s", e)
        await ctx.followup.send(f"❌ 無法連線: {e}", ephemeral=True)
        return

    await ctx.followup.send(f"🔊 已加入 `{channel.name}`，開始監聽")
    asyncio.create_task(voice_loop(vc, channel.id))


# ============================================================
# /leave
# ============================================================
@bot.slash_command(name="leave", description="離開語音頻道")
async def cmd_leave(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)
    vc = ctx.voice_client
    if vc is None:
        await ctx.followup.send("❌ 不在任何頻道中", ephemeral=True)
        return

    _active_loops[ctx.guild.id] = False
    if vc.is_playing():
        vc.stop()
    await vc.disconnect()
    if llm_engine:
        llm_engine.clear_history(ctx.channel.id)
    await ctx.followup.send("👋 已離開")


# ============================================================
# /set_voice
# ============================================================
@bot.slash_command(name="set_voice", description="切換 TTS 角色")
async def cmd_set_voice(
    ctx: discord.ApplicationContext,
    character: discord.Option(str, "角色名稱"),
):
    if tts_engine is None:
        await ctx.respond("❌ TTS 尚未初始化", ephemeral=True)
        return
    tts_engine.update_character(character)
    await ctx.respond(f"🎤 已切換為 `{character}`")


# ============================================================
# /status
# ============================================================
@bot.slash_command(name="status", description="查看狀態")
async def cmd_status(ctx: discord.ApplicationContext):
    vc = ctx.voice_client
    vs = "未連接"
    if vc and vc.is_connected():
        vs = f"`{vc.channel.name}`" + (" (播放中)" if vc.is_playing() else "")
    cap = "執行中" if (audio_capture and audio_capture._running) else "未啟動"

    msg = (
        f"**Bot 狀態**\n"
        f"• 語音頻道: {vs}\n"
        f"• 音訊擷取: {cap}\n"
        f"• TTS: `{tts_engine.speaker if tts_engine else '?'}`\n"
        f"• LLM: `deepseek-chat` / STT: `whisper-tiny`\n"
    )
    await ctx.respond(msg, ephemeral=True)


# ============================================================
# /devices — 列出可用音效裝置
# ============================================================
@bot.slash_command(name="devices", description="列出可用的系統音效裝置")
async def cmd_devices(ctx: discord.ApplicationContext):
    """列出 PyAudio 可用裝置"""
    await ctx.defer(ephemeral=True)
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        lines = ["**可用輸入裝置：**"]
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                lines.append(f"`[{i}]` {info['name']}")
        pa.terminate()
        await ctx.followup.send("\n".join(lines), ephemeral=True)
    except Exception as e:
        await ctx.followup.send(f"❌ {e}", ephemeral=True)


# ============================================================
# 啟動
# ============================================================
if __name__ == "__main__":
    logger.info("啟動 Discord Bot（系統音訊擷取模式）...")
    bot.run(DISCORD_TOKEN)
