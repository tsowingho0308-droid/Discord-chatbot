"""
生成「太吵了，一個一個說」打斷語音
透過 GPT-SoVITS TTS API 產生，若 API 不可用則生成簡單替代音效
"""
import os
import sys
import wave
import struct
import requests
from config import TTS_API_URL, TTS_CHARACTER

OUTPUT_PATH = "audio/too_noisy.wav"
TEXT = "太吵了，一個一個說"


def generate_beep_wav(path: str):
    """生成簡單的替代音效（兩個短嗶聲）"""
    sample_rate = 48000
    duration = 0.3  # 每個嗶聲 0.3 秒
    freq = 880      # A5 音高
    gap = 0.2       # 兩個嗶聲之間停頓 0.2 秒

    samples_per_beep = int(sample_rate * duration)
    samples_gap = int(sample_rate * gap)

    def gen_beep():
        for i in range(samples_per_beep):
            t = i / sample_rate
            # 簡單的衰減正弦波
            envelope = 1.0 - (i / samples_per_beep)
            value = int(16000 * envelope * (
                (2.0 / 3.14159) * (freq * 2 * 3.14159 * t % (2 * 3.14159))
            ))
            # clamp to 16-bit signed
            value = max(-32768, min(32767, value))
            yield struct.pack("<h", value)

    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        # 第一個嗶
        for sample in gen_beep():
            wf.writeframes(sample)
        # 停頓
        wf.writeframes(b"\x00\x00" * samples_gap)
        # 第二個嗶
        for sample in gen_beep():
            wf.writeframes(sample)

    print(f"✅ 替代音效已生成: {path}")


def generate_tts_wav(path: str):
    """透過 GPT-SoVITS API 生成語音"""
    url = f"{TTS_API_URL.rstrip('/')}/tts"
    payload = {"text": TEXT, "character": TTS_CHARACTER}

    print(f"發送 TTS 請求到: {url}")
    print(f"文字: {TEXT}")
    print(f"音色: {TTS_CHARACTER}")

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code == 200:
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"✅ TTS 語音已生成: {path} ({len(resp.content)} bytes)")
    else:
        print(f"❌ TTS API 失敗: status={resp.status_code}, body={resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    # 嘗試用 TTS API 生成
    try:
        generate_tts_wav(OUTPUT_PATH)
    except requests.exceptions.ConnectionError:
        print("⚠ 無法連線到 TTS API，改用替代音效...")
        generate_beep_wav(OUTPUT_PATH)
    except Exception as e:
        print(f"⚠ TTS API 錯誤: {e}，改用替代音效...")
        generate_beep_wav(OUTPUT_PATH)
