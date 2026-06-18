"""
生成打斷語音檔案（雙版本）
- 「太吵了，一個一個說」（一般版）
- 「你們安靜，吵到我主人講話了」（主人版）

使用方式：
    python generate_too_noisy.py              # 生成兩個版本
    python generate_too_noisy.py --beep-only  # 只用替代音效（無需 TTS）
"""
import os
import sys
import wave
import struct
import argparse

try:
    import requests
    from config import TTS_API_URL, TTS_CHARACTER
    HAS_TTS_CONFIG = True
except ImportError:
    HAS_TTS_CONFIG = False
    TTS_API_URL = "http://127.0.0.1:9880"
    TTS_CHARACTER = "default"

AUDIO_DIR = "audio"

# 兩個版本的文字內容
VERSION_TEXTS = {
    "too_noisy": "太吵了，一個一個說",
    "too_noisy_owner": "你們安靜，吵到我主人講話了",
}

OUTPUT_PATHS = {
    "too_noisy": os.path.join(AUDIO_DIR, "too_noisy.wav"),
    "too_noisy_owner": os.path.join(AUDIO_DIR, "too_noisy_owner.wav"),
}


def generate_beep_wav(path: str, beep_count: int = 2):
    """生成簡單的替代音效（多個短嗶聲）"""
    sample_rate = 48000
    duration = 0.3   # 每個嗶聲 0.3 秒
    freq = 880       # A5 音高
    gap = 0.2        # 嗶聲之間停頓 0.2 秒

    samples_per_beep = int(sample_rate * duration)
    samples_gap = int(sample_rate * gap)

    def gen_beep():
        for i in range(samples_per_beep):
            t = i / sample_rate
            envelope = 1.0 - (i / samples_per_beep)
            value = int(16000 * envelope * (
                (2.0 / 3.14159) * (freq * 2 * 3.14159 * t % (2 * 3.14159))
            ))
            value = max(-32768, min(32767, value))
            yield struct.pack("<h", value)

    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        for b in range(beep_count):
            for sample in gen_beep():
                wf.writeframes(sample)
            if b < beep_count - 1:
                wf.writeframes(b"\x00\x00" * samples_gap)

    print(f"✅ 替代音效已生成: {path}")


def generate_tts_wav(path: str, text: str):
    """透過 GPT-SoVITS API 生成語音"""
    url = f"{TTS_API_URL.rstrip('/')}/tts"
    payload = {"text": text, "character": TTS_CHARACTER}

    print(f"發送 TTS 請求到: {url}")
    print(f"文字: {text}")
    print(f"音色: {TTS_CHARACTER}")

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code == 200:
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"✅ TTS 語音已生成: {path} ({len(resp.content)} bytes)")
        return True
    else:
        print(f"❌ TTS API 失敗: status={resp.status_code}, body={resp.text[:200]}")
        return False


def generate_all(beep_only: bool = False):
    """生成所有打斷語音版本"""
    os.makedirs(AUDIO_DIR, exist_ok=True)

    for key, text in VERSION_TEXTS.items():
        path = OUTPUT_PATHS[key]
        print(f"\n{'=' * 50}")
        print(f"生成: {key} → \"{text}\"")

        if beep_only:
            # 主人版用 3 個嗶聲區別
            beeps = 3 if "owner" in key else 2
            generate_beep_wav(path, beep_count=beeps)
        else:
            try:
                ok = generate_tts_wav(path, text)
                if not ok:
                    print("⚠ TTS 失敗，改用替代音效...")
                    beeps = 3 if "owner" in key else 2
                    generate_beep_wav(path, beep_count=beeps)
            except Exception as e:
                print(f"⚠ TTS 錯誤: {e}，改用替代音效...")
                beeps = 3 if "owner" in key else 2
                generate_beep_wav(path, beep_count=beeps)

    print(f"\n{'=' * 50}")
    print("✅ 所有打斷語音生成完成！")
    for key, path in OUTPUT_PATHS.items():
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"  {key}: {path} ({size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 Discord Bot 打斷語音")
    parser.add_argument(
        "--beep-only", action="store_true",
        help="只使用替代嗶聲音效（無需 TTS API）"
    )
    args = parser.parse_args()
    generate_all(beep_only=args.beep_only)
