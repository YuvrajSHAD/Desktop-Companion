"""Microphone capture + voice-activity detection (hands-free listening)."""
from __future__ import annotations
import collections
import queue
import time

import numpy as np
import sounddevice as sd
import webrtcvad

SR_IN = 16000
FRAME_MS = 30
FRAME_SAMPLES = SR_IN * FRAME_MS // 1000  # 480 samples


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


class Mic:
    def __init__(self, device=None):
        self.q: queue.Queue = queue.Queue()
        self.stream = sd.InputStream(
            samplerate=SR_IN, channels=1, dtype="int16",
            blocksize=FRAME_SAMPLES, device=device, callback=self._cb,
        )

    def _cb(self, indata, frames, t, status):
        self.q.put(indata[:, 0].copy())

    def start(self):
        self.stream.start()

    def stop(self):
        self.stream.stop()
        self.stream.close()

    def read(self, timeout: float = 0.5):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self):
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


class Listener:
    def __init__(self, mic: Mic, cfg):
        self.mic = mic
        self.cfg = cfg
        self.vad = webrtcvad.Vad(cfg.vad_aggressiveness)
        self.last_end = 0.0  # perf_counter() when the user stopped talking
        self.on_speech_start = None  # optional callback, fired when you start talking

    def voiced(self, frame: np.ndarray, min_rms: float | None = None) -> bool:
        if rms(frame) < (self.cfg.min_rms if min_rms is None else min_rms):
            return False
        return self.vad.is_speech(frame.tobytes(), SR_IN)

    def listen(self, initial_frames=None, timeout=None, end_silence_ms=None, max_s=None):
        """Block until one full utterance is captured. Returns float32 16 kHz audio.

        timeout: give up (return None) if you haven't started talking within this many seconds.
        end_silence_ms / max_s: override the pause length / max length (used for dictating notes).
        """
        cfg = self.cfg
        end_frames = (end_silence_ms or cfg.end_silence_ms) // FRAME_MS
        max_frames = int((max_s or cfg.max_utterance_s) * 1000 / FRAME_MS)
        deadline = time.perf_counter() + timeout if timeout else None
        pre = collections.deque(maxlen=10)  # ~300 ms pre-roll
        frames: list = []
        triggered = False
        run = 0
        silence = 0
        if initial_frames:
            frames, triggered = list(initial_frames), True
            if self.on_speech_start:
                self.on_speech_start()

        while True:
            if deadline is not None and not triggered and time.perf_counter() > deadline:
                return None
            f = self.mic.read(0.5)
            if f is None:
                continue
            v = self.voiced(f)
            if not triggered:
                pre.append(f)
                run = run + 1 if v else 0
                if run >= 4:  # ~120 ms of speech
                    triggered, frames, silence = True, list(pre), 0
                    if self.on_speech_start:
                        self.on_speech_start()
            else:
                frames.append(f)
                silence = 0 if v else silence + 1
                if silence >= end_frames or len(frames) >= max_frames:
                    break

        self.last_end = time.perf_counter() - silence * FRAME_MS / 1000
        if (len(frames) - silence) * FRAME_MS < 300:  # too short: cough / click
            return None
        return np.concatenate(frames).astype(np.float32) / 32768.0
