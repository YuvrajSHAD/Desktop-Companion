"""Listens to what your PC is playing (Spotify, YouTube, ...) so the pet can dance to it (Windows).

Uses WASAPI loopback via PyAudioWPatch: it hears the speaker mix, never the microphone.
Only loudness and beat timing leave this file - no audio is stored or sent anywhere.
It stays quiet while Moss is thinking/talking, so its own voice never makes it dance.
"""
from __future__ import annotations
import collections
import sys
import threading
import time

import numpy as np


class BeatTracker:
    """Energy-based beat detector. Feed it mono float32 blocks; it says when a beat lands.

    Pure numpy and clock-injected, so it is unit-tested without any audio hardware.
    """

    def __init__(self, sample_rate: int, threshold: float = 0.02, min_seconds: float = 1.0,
                 hold_seconds: float = 3.0):
        self.sr = sample_rate
        self.threshold = threshold      # RMS (0..1) the music has to exceed to count as "playing"
        self.min_seconds = min_seconds  # loud for this long before we start dancing
        self.hold_seconds = hold_seconds  # quiet for this long before we stop
        self.hist = collections.deque(maxlen=max(8, int(1.0 * sample_rate / 1024)))
        self.beats = collections.deque(maxlen=12)
        self.active = False
        self.level = 0.0
        self.bpm = 0.0
        self._loud_since = None
        self._quiet_since = None
        self._last_beat = -1.0

    def feed(self, block: np.ndarray, now: float):
        """Returns (beat: bool, changed: bool). `changed` is True when `active` flipped."""
        e = float(np.sqrt(np.mean(block.astype(np.float32) ** 2))) if len(block) else 0.0
        self.level = e
        beat = False
        avg = (sum(self.hist) / len(self.hist)) if self.hist else 0.0
        if (e > self.threshold and e > 1.35 * avg and len(self.hist) >= 8
                and now - self._last_beat >= 0.24):
            beat = True
            self._last_beat = now
            self.beats.append(now)
            self._update_bpm()
        self.hist.append(e)

        changed = False
        if e > self.threshold:
            self._quiet_since = None
            if self._loud_since is None:
                self._loud_since = now
            if not self.active and now - self._loud_since >= self.min_seconds:
                self.active, changed = True, True
        else:
            self._loud_since = None
            if self._quiet_since is None:
                self._quiet_since = now
            if self.active and now - self._quiet_since >= self.hold_seconds:
                self.active, changed = False, True
                self.beats.clear()
                self.bpm = 0.0
        return beat and self.active, changed

    def _update_bpm(self):
        if len(self.beats) < 4:
            return
        gaps = np.diff(np.array(self.beats))
        gaps = gaps[(gaps > 0.25) & (gaps < 1.3)]
        if len(gaps) < 3:
            return
        bpm = 60.0 / float(np.median(gaps))
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
        self.bpm = bpm if not self.bpm else 0.7 * self.bpm + 0.3 * bpm


class MusicListener:
    def __init__(self, bridge, cfg):
        self.bridge = bridge
        self.cfg = cfg
        self.busy = False          # Moss is listening/thinking/talking: ignore the speakers
        self.busy_until = 0.0
        self._stop = threading.Event()
        self._last_level_sent = 0.0

    def note(self, ev: dict) -> None:
        """Called for every event Moss sends to the body (see Bridge.tap)."""
        if ev.get("type") == "state":
            was = self.busy
            self.busy = ev.get("value") != "idle"
            if was and not self.busy:
                self.busy_until = time.perf_counter() + 1.5  # let the tail of its own voice die out

    def start(self) -> None:
        if sys.platform != "win32":
            print("[music] Windows only; the pet will not dance to music here.")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            print("[music] pip install PyAudioWPatch  to let Moss dance to your music.")
            return
        try:
            pa = pyaudio.PyAudio()
            dev = pa.get_default_wasapi_loopback()
            ch = int(dev["maxInputChannels"])
            sr = int(dev["defaultSampleRate"])
            tracker = BeatTracker(sr, self.cfg.music_threshold, self.cfg.music_min_seconds,
                                  self.cfg.music_hold_seconds)

            def cb(data, frames, t, status):
                if self._stop.is_set():
                    return (None, pyaudio.paComplete)
                x = np.frombuffer(data, dtype=np.float32)
                x = x.reshape(-1, ch).mean(axis=1) if ch > 1 else x
                self._on_block(tracker, x)
                return (None, pyaudio.paContinue)

            stream = pa.open(format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                             input_device_index=int(dev["index"]), frames_per_buffer=1024,
                             stream_callback=cb)
            print(f"[music] listening to: {dev['name']}")
            while not self._stop.is_set() and stream.is_active():
                time.sleep(0.5)
            stream.close()
            pa.terminate()
        except Exception as e:  # no loopback device, driver hiccup... never kill the pet
            print(f"[music] disabled: {e}")

    def _on_block(self, tracker: BeatTracker, x: np.ndarray) -> None:
        now = time.perf_counter()
        gated = self.busy or now < self.busy_until
        beat, changed = tracker.feed(np.zeros(1, np.float32) if gated else x, now)
        if changed:
            self.bridge.emit({"type": "music", "active": tracker.active, "bpm": round(tracker.bpm)})
        if beat:
            self.bridge.emit({"type": "music", "active": True, "beat": True,
                              "level": round(min(1.0, tracker.level * 6), 2), "bpm": round(tracker.bpm)})
