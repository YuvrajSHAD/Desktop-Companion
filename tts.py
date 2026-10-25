"""Mouth: Kokoro-82M on GPU, streamed sentence-by-sentence through a playback thread.

While it talks it also tells the desktop body what to do: mood tag, subtitle text, and the
live loudness of the audio (25x a second) so the character's mouth moves with the real voice.
"""
from __future__ import annotations
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import torch
from kokoro import KPipeline

from bridge import NullBridge
from textutil import clean_for_tts, split_emotion

SR_OUT = 24000
BLOCK = 960  # 40 ms -> 25 mouth updates per second


class Speaker:
    def __init__(self, cfg, bridge=None):
        self.cfg = cfg
        self.bridge = bridge or NullBridge()
        self.pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
        self.synth("Ready.")  # warm-up

    def synth(self, text: str):
        parts = []
        for _, _, audio in self.pipe(text, voice=self.cfg.tts_voice, speed=self.cfg.tts_speed):
            if audio is None:
                continue
            parts.append(audio.detach().cpu().numpy() if torch.is_tensor(audio) else np.asarray(audio))
        return np.concatenate(parts).astype(np.float32) if parts else None


class Playback:
    """Pulls sentences from any iterator, synthesises them, plays them. Cancellable."""

    def __init__(self, speaker: Speaker, sentences, show_text: bool = True):
        self.speaker = speaker
        self.bridge = speaker.bridge
        self.sentences = sentences
        self.show_text = show_text
        self.cancel_ev = threading.Event()
        self.done = threading.Event()
        self.produced_all = threading.Event()
        self.audio_q: queue.Queue = queue.Queue(maxsize=4)
        self.first_audio_at: float | None = None
        self._threads = [
            threading.Thread(target=self._produce, daemon=True),
            threading.Thread(target=self._play, daemon=True),
        ]

    def start(self):
        for t in self._threads:
            t.start()
        return self

    def cancel(self):
        self.cancel_ev.set()

    def _produce(self):
        try:
            for s in self.sentences:
                if self.cancel_ev.is_set():
                    break
                emotion, text = split_emotion(s)
                text = clean_for_tts(text)
                if not text:
                    continue
                if self.show_text:
                    print(f"{self.speaker.cfg.name}: {text}", flush=True)
                audio = self.speaker.synth(text)
                if audio is None:
                    continue
                item = (audio, emotion, text)
                while not self.cancel_ev.is_set():
                    try:
                        self.audio_q.put(item, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        except Exception as e:  # keep the player from hanging
            print(f"[speech error] {e}", flush=True)
        finally:
            close = getattr(self.sentences, "close", None)
            if close:
                close()
            self.produced_all.set()

    def _play(self):
        out = sd.OutputStream(
            samplerate=int(SR_OUT * getattr(self.speaker.cfg, "tts_pitch", 1.0)), channels=1, dtype="float32",
            device=self.speaker.cfg.output_device, latency="low",
        )
        out.start()
        try:
            out.write(np.zeros((int(0.08 * SR_OUT), 1), np.float32))  # wake the DAC
            while True:
                try:
                    audio, emotion, text = self.audio_q.get(timeout=0.05)
                except queue.Empty:
                    if self.cancel_ev.is_set() or self.produced_all.is_set():
                        break
                    continue
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                    self.bridge.emit({"type": "state", "value": "speaking"})
                if emotion:
                    self.bridge.emit({"type": "emotion", "value": emotion})
                self.bridge.emit({"type": "subtitle", "text": text})
                for i in range(0, len(audio), BLOCK):
                    if self.cancel_ev.is_set():
                        break
                    blk = audio[i : i + BLOCK]
                    rms = float(np.sqrt(np.mean(blk * blk))) if len(blk) else 0.0
                    self.bridge.emit({"type": "mouth", "v": round(min(1.0, rms * 9.0), 2)})
                    out.write(blk.reshape(-1, 1))
            if self.cancel_ev.is_set():
                out.abort()
            else:
                out.write(np.zeros((int(0.15 * SR_OUT), 1), np.float32))
                out.stop()
        finally:
            out.close()
            self.bridge.emit({"type": "mouth", "v": 0})
            self.bridge.emit({"type": "state", "value": "idle"})
            self.done.set()
