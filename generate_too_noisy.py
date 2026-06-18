"""
生成打斷語音檔案（雙版本）— 使用 Hugging Face VITS TTS API
- 「太吵了，一個一個說」（一般版）
- 「你們安靜，吵到我主人講話了」（主人版）

使用方式：
    python generate_too_noisy.py              # 用 TTS API 生成真實語音
    python generate_too_noisy.py --beep-only  # 只用替代音效（無網路時）
"""
import os
import sys
import wave
import struct
import argparse

# 修正 Windows 中文編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gradio_client import Client
from config import TTS_HF_SPACE, TTS_SPEAKER, TTS_LANGUAGE, TTS_SPEED

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
    duration = 0.3
    freq = 880
    gap = 0.2

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

    print(f"[OK] Beep fallback generated: {path}")


def generate_tts_wav(client: Client, path: str, text: str):
    """透過 VITS Gradio API 生成語音"""
    print(f"Text: {text}")
    print(f"Speaker: {TTS_SPEAKER}")
    print(f"Language: {TTS_LANGUAGE}")

    result = client.predict(
        text=text,
        speaker=TTS_SPEAKER,
        language=TTS_LANGUAGE,
        speed=TTS_SPEED,
        is_symbol=False,
        api_name="/tts_fn",
    )

    message, tmp_path = result

    if tmp_path and os.path.exists(tmp_path):
        import shutil
        shutil.copy2(tmp_path, path)
        print(f"[OK] TTS audio saved: {path} ({os.path.getsize(path)} bytes)")
    else:
        print(f"[FAIL] No file returned. Message: {message}")
        return False
    return True


def generate_all(beep_only: bool = False):
    """生成所有打斷語音版本"""
    os.makedirs(AUDIO_DIR, exist_ok=True)

    client = None
    if not beep_only:
        try:
            print(f"Connecting to {TTS_HF_SPACE} ...")
            client = Client(TTS_HF_SPACE)
            print("Connected!")
        except Exception as e:
            print(f"[WARN] Cannot connect to TTS API: {e}")
            print("[WARN] Falling back to beep sounds...")
            beep_only = True

    for key, text in VERSION_TEXTS.items():
        path = OUTPUT_PATHS[key]
        print(f"\n{'=' * 50}")
        print(f"Generating: {key}")

        if beep_only or client is None:
            beeps = 3 if "owner" in key else 2
            generate_beep_wav(path, beep_count=beeps)
        else:
            try:
                ok = generate_tts_wav(client, path, text)
                if not ok:
                    beeps = 3 if "owner" in key else 2
                    generate_beep_wav(path, beep_count=beeps)
            except Exception as e:
                print(f"[WARN] TTS error: {e}")
                beeps = 3 if "owner" in key else 2
                generate_beep_wav(path, beep_count=beeps)

    print(f"\n{'=' * 50}")
    print("All done!")
    for key, path in OUTPUT_PATHS.items():
        if os.path.exists(path):
            print(f"  {key}: {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate interrupt audio for Discord Bot")
    parser.add_argument("--beep-only", action="store_true", help="Use beep sounds only (no internet)")
    args = parser.parse_args()
    generate_all(beep_only=args.beep_only)
