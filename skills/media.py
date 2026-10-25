"""Spotify (or any media app) control WITHOUT touching window focus.

Primary path: Windows' own media-session API (the thing behind the volume flyout / lock-screen controls),
through the `winrt` packages. It talks to the player directly, so nothing gets activated.
Fallback: the global media keys (next / previous only), which also never change the active window.
"""
from __future__ import annotations

import asyncio
import random
import re
import sys
import threading
from dataclasses import dataclass

from . import Result, Skill

# ---------------------------------------------------------------- parsing (pure, unit-tested)
_NOUN = re.compile(r"\b(song|songs|track|tracks|music|tune|tunes|spotify|playlist)\b")


def parse_media_command(text: str) -> str | None:
    """Normalised utterance -> 'next' | 'previous' | 'pause' | 'resume' | None."""
    w = text.split()
    if not w or len(w) > 10:  # long sentences are conversation, not commands
        return None
    noun = bool(_NOUN.search(text))
    if re.search(r"\b(next|skip)\b", text) and (noun or len(w) <= 3 or re.search(r"\b(next one|skip (this|it))\b", text)):
        return "next"
    if re.search(r"\b(previous|prev|last|before)\b", text) and noun:
        return "previous"
    if re.search(r"\bgo back\b", text) and noun:
        return "previous"
    if text in {"previous", "previous one", "go back", "previous track"}:
        return "previous"
    if re.search(r"\b(pause|stop)\b", text) and (noun or text in {"pause", "pause it"}):
        return "pause"
    if re.search(r"\b(resume|unpause|continue)\b", text) and (noun or text == "resume"):
        return "resume"
    if re.match(r"^(play|start|put on)( the| some| my)? (music|song|spotify)\b", text):
        return "resume"
    return None


# ---------------------------------------------------------------- controller
@dataclass
class MediaStatus:
    playing: bool
    title: str = ""


_VK = {"next": 0xB0, "previous": 0xB1}  # VK_MEDIA_NEXT_TRACK / VK_MEDIA_PREV_TRACK


class MediaController:
    """Thread-safe wrapper around the Windows media-session API (runs its own asyncio loop)."""

    def __init__(self, hint: str = "spotify"):
        self.hint = (hint or "").lower()
        self.backend: str | None = None  # 'gsmtc' | 'keys' | None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mgr = None
        self._lock = threading.Lock()
        self._warned = False

    # -- setup
    def _ensure(self) -> bool:
        with self._lock:
            if self.backend:
                return True
            if sys.platform != "win32":
                return False
            try:
                from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager  # noqa: F401
            except Exception as e:
                self.backend = "keys"
                print(f"[media] winrt not installed ({e}); falling back to media keys (next/previous only).\n"
                      "        Better:  pip install winrt-runtime winrt-Windows.Media.Control "
                      "winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Storage.Streams")
                return True
            self._loop = asyncio.new_event_loop()
            threading.Thread(target=self._loop.run_forever, daemon=True).start()
            self.backend = "gsmtc"
            return True

    def _run(self, coro, timeout: float = 4.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _manager(self):
        if self._mgr is None:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

            self._mgr = await M.request_async()
        return self._mgr

    async def _session(self):
        mgr = await self._manager()
        sessions = list(mgr.get_sessions())
        if not self.hint:
            return mgr.get_current_session() or (sessions[0] if sessions else None)
        for s in sessions:
            if self.hint in (s.source_app_user_model_id or "").lower():
                return s
        return None

    # -- public
    def command(self, act: str) -> str:
        """Returns 'ok' | 'no-player' | 'unsupported' | 'error'."""
        if not self._ensure():
            return "unsupported"
        if self.backend == "keys":
            return self._press(act)
        try:
            return self._run(self._do(act))
        except Exception as e:
            print(f"[media] {act} failed: {e}")
            return "error"

    async def _do(self, act: str) -> str:
        s = await self._session()
        if s is None:
            return "no-player"
        fn = {"next": s.try_skip_next_async, "previous": s.try_skip_previous_async,
              "pause": s.try_pause_async, "resume": s.try_play_async}[act]
        return "ok" if await fn() else "error"

    def status(self) -> MediaStatus | None:
        """None = can't tell (no winrt). MediaStatus(False) when the player isn't running / is paused."""
        if not self._ensure() or self.backend != "gsmtc":
            return None
        try:
            return self._run(self._status(), 2.0)
        except Exception:
            return None

    async def _status(self) -> MediaStatus:
        s = await self._session()
        if s is None:
            return MediaStatus(False)
        playing = int(s.get_playback_info().playback_status) == 5  # 5 = PLAYING (4 = PAUSED)
        title = ""
        if playing:
            try:
                title = (await s.try_get_media_properties_async()).title or ""
            except Exception:
                pass
        return MediaStatus(playing, title)

    @staticmethod
    def _press(act: str) -> str:
        vk = _VK.get(act)
        if vk is None:
            return "unsupported"
        import ctypes

        u = ctypes.windll.user32
        u.keybd_event(vk, 0, 0, 0)
        u.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
        return "ok"


# ---------------------------------------------------------------- the skill
_SAY = {
    "next": ["[relaxed] Next one.", "[neutral] Skipping.", "[relaxed] Okay, next."],
    "previous": ["[relaxed] Going back.", "[neutral] Previous one."],
    "pause": ["[relaxed] Paused.", "[sleepy] Quiet time."],
    "resume": ["[happy] Music's back.", "[relaxed] Playing."],
}


class MediaSkill(Skill):
    name = "media"
    description = "Next / previous / pause / resume the music player without switching windows."

    def __init__(self, media: MediaController):
        self.media = media

    def handle(self, text: str, body: str) -> Result | None:
        act = parse_media_command(text)
        if not act:
            return None
        res = self.media.command(act)
        if res == "ok":
            return Result(random.choice(_SAY[act]))
        if res == "no-player":
            return Result("[neutral] I can't find Spotify running.")
        if res == "unsupported":
            return Result("[neutral] I can't do that one right now.")
        return Result("[sad] Spotify didn't answer me.")
