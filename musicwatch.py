"""Tells the body when music is PLAYING (not merely open, not paused) and how loud it is, so Moss can dance.

* "Playing" comes from Windows' media-session API (same source as the volume flyout): Spotify reports
  PLAYING only while audio is actually flowing, PAUSED when you pause, and nothing when it's just open.
* The loudness comes from the app's own WASAPI audio session meter (via pycaw), so the dance follows the beat.
  No microphone, no loopback capture, nothing is recorded.
If winrt is missing it falls back to "is that app producing sound right now?" using only the meter.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque


class AudioLevel:
    """Peak output level (0..1) of every audio session whose process name contains `hint`."""

    def __init__(self, hint: str):
        self.hint = (hint or "").lower()
        self.meters: list = []
        self._next_scan = 0.0
        self.available = sys.platform == "win32"
        self._warned = False

    def _scan(self) -> None:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

            found = []
            for s in AudioUtilities.GetAllSessions():
                try:
                    name = (s.Process.name() if s.Process else "").lower()
                except Exception:
                    continue
                if name and (not self.hint or self.hint in name):
                    found.append(s._ctl.QueryInterface(IAudioMeterInformation))
            self.meters = found
        except Exception as e:
            self.meters = []
            if not self._warned:
                self._warned = True
                print(f"[music] audio meter unavailable ({e}); the dance will use a steady rhythm.\n"
                      "        Better:  pip install pycaw comtypes")

    def peak(self) -> float:
        if not self.available:
            return 0.0
        now = time.monotonic()
        if now >= self._next_scan:
            self._scan()
            self._next_scan = now + (2.0 if self.meters else 1.0)
        best = 0.0
        for m in list(self.meters):
            try:
                best = max(best, float(m.GetPeakValue()))
            except Exception:
                self.meters = []
                self._next_scan = 0.0
        return best


class MusicWatcher:
    HZ = 15

    def __init__(self, media, emit, cfg):
        self.media = media
        self.emit = emit
        self.hint = cfg.media_app_hint
        self.playing = False
        self.title = ""
        self._stop = threading.Event()

    def start(self) -> None:
        if sys.platform != "win32":
            print("[music] Windows only; Moss won't dance to music here.")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def resend(self) -> None:
        self.emit({"type": "music", "playing": self.playing, "title": self.title})

    def _run(self) -> None:
        try:
            import comtypes

            comtypes.CoInitialize()
        except Exception:
            pass
        audio = AudioLevel(self.hint)
        recent: deque = deque(maxlen=self.HZ * 2)  # last ~2 s of peaks, for the no-winrt fallback
        last_poll = 0.0
        while not self._stop.is_set():
            t0 = time.monotonic()
            level = audio.peak()
            recent.append(level)
            if t0 - last_poll >= 0.5:
                last_poll = t0
                st = self.media.status()
                if st is not None:
                    now_playing, title = st.playing, st.title
                else:  # no media-session API: "audible in the last ~1.5 s" counts as playing
                    now_playing, title = (max(list(recent)[-int(self.HZ * 1.5):], default=0) > 0.004), ""
                if now_playing != self.playing or (now_playing and title != self.title):
                    self.playing, self.title = now_playing, title
                    self.resend()
                    print(f"[music] {'playing ' + title if now_playing else 'stopped'}".strip())
            if self.playing:
                self.emit({"type": "level", "v": round(level, 3)})
            time.sleep(max(0.0, 1.0 / self.HZ - (time.monotonic() - t0)))
