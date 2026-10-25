"""Audition voices for Moss (needs the GPU + Kokoro, like main.py):  python voice_test.py
Plays the same line with each candidate so you can pick. Put your favourite in config.py -> tts_voice / tts_pitch."""
from dataclasses import replace
import time

from config import CFG
from tts import Playback, Speaker

LINE = "[happy] Konnichiwa, everyone! I'm Moss, a very small, very sleepy desktop sloth. I will do your boring chores, ne?"
CANDIDATES = [  # (voice, pitch)
    ("jf_alpha", 1.05), ("jf_alpha", 1.0), ("jf_alpha", 1.10), ("jf_tebukuro", 1.05), ("jf_nezumi", 1.05),
    ("jf_gongitsune", 1.05), ("jf_alpha,af_bella", 1.05), ("jf_alpha,af_heart", 1.05), ("af_heart", 1.0),
]

speaker = Speaker(CFG)
for voice, pitch in CANDIDATES:
    speaker.cfg = replace(CFG, tts_voice=voice, tts_pitch=pitch)
    print(f"--> tts_voice={voice!r}  tts_pitch={pitch}", flush=True)
    Playback(speaker, iter([LINE]), show_text=False).start().done.wait(30)
    time.sleep(0.6)
