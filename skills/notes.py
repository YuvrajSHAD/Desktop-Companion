"""Voice notes: "Hey Moss, take a note" -> she listens -> your words appear in a Notepad window.

* Every note is ALWAYS appended to a plain text file first (cfg.notes_file), so nothing is ever lost.
* On top of that she types into a visible Notepad window by sending messages straight to its edit box,
  which does not need focus - so Notepad never becomes the active window and your current app keeps focus.
* If typing into Notepad isn't possible on your Windows build, she opens the notes file in Notepad instead
  (and puts focus back where it was).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import Result, Skill

# ---------------------------------------------------------------- parsing (pure, unit-tested)
_FILLER = r"^\W*(?:(?:please|can you|could you|would you|will you|just|now|hey|hi|hello|ok|okay|so|and|then)\W+)*"
_START = [
    r"(?:take|make|write|jot|start|begin|open|add)(?:\s+(?:me|down))?\s+(?:a\s+|an\s+|some\s+|the\s+)?(?:quick\s+|new\s+|short\s+)?notes?\b",
    r"(?:note|write|jot)\s+(?:this|that|it)\s+down\b",
    r"take\s+notes\b",
]
_END = re.compile(
    r"^(?:(?:ok|okay|alright)\s+)?(?:(?:that's|that is|thats)\s+(?:all|it|enough)|that will be all|(?:i'm|i am|im)\s+(?:done|finished)|"
    r"done|finished|stop|stop (?:taking )?notes?|end (?:the )?notes?|close (?:the )?notes?|save(?: it| that| the notes?)?|"
    r"nothing else|never ?mind|cancel|thanks|thank you)$"
)


def parse_note_start(body: str) -> str | None:
    """'Take a note.' -> ''   'take a note: buy milk' -> 'buy milk'   anything else -> None."""
    for pat in _START:
        m = re.match(_FILLER + pat + r"(.*)$", body.strip(), flags=re.I | re.S)
        if m:
            rest = m.group(1).lstrip(" ,.:;-—!?").strip()
            rest = re.sub(r"^(?:that|saying|to say|which says)\b[\s,:]*", "", rest, flags=re.I).strip()
            return rest
    return None


def is_note_end(text: str) -> bool:
    return len(text.split()) <= 6 and bool(_END.match(text))


# ---------------------------------------------------------------- Windows helpers
_W = sys.platform == "win32"
WM_GETTEXT, WM_GETTEXTLENGTH, WM_SETTEXT, WM_CHAR, WM_CLOSE = 0x0D, 0x0E, 0x0C, 0x102, 0x10
EM_SETSEL, EM_REPLACESEL = 0xB1, 0xC2
SMTO_ABORTIFHUNG = 0x2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
EDIT_CLASSES = {"Edit", "RichEditD2DPT", "RICHEDIT50W", "RichEdit20W"}


class _Win:
    """Thin ctypes layer. Only constructed on Windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self.ct, self.wt = ctypes, wintypes
        u = self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.k = ctypes.WinDLL("kernel32")
        self.ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self.ENUM, wintypes.LPARAM]
        u.EnumChildWindows.argtypes = [wintypes.HWND, self.ENUM, wintypes.LPARAM]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p,
                                           wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        u.SendMessageTimeoutW.restype = ctypes.c_void_p
        try:  # physical pixels, same as winwatch
            u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass

    def cls(self, h) -> str:
        b = self.ct.create_unicode_buffer(128)
        self.u.GetClassNameW(h, b, 128)
        return b.value

    def top_windows(self, wanted_class: str) -> list[int]:
        out: list[int] = []

        def cb(h, _):
            if self.u.IsWindowVisible(h) and self.cls(h) == wanted_class:
                out.append(int(h))
            return True

        self.u.EnumWindows(self.ENUM(cb), 0)
        return out  # z-order, topmost first

    def edit_child(self, top: int) -> int:
        found: list[int] = []

        def cb(h, _):
            if self.u.IsWindowVisible(h) and self.cls(h) in EDIT_CLASSES:
                found.append(int(h))
            return True

        self.u.EnumChildWindows(top, self.ENUM(cb), 0)
        return found[0] if found else 0

    def send(self, h, msg, wparam=0, lparam=0) -> bool:
        res = self.ct.c_size_t(0)
        r = self.u.SendMessageTimeoutW(h, msg, wparam, lparam, SMTO_ABORTIFHUNG, 800, self.ct.byref(res))
        return bool(r)

    def get_text(self, h) -> str:
        res = self.ct.c_size_t(0)
        if not self.u.SendMessageTimeoutW(h, WM_GETTEXTLENGTH, 0, 0, SMTO_ABORTIFHUNG, 800, self.ct.byref(res)):
            return ""
        n = int(res.value)
        buf = self.ct.create_unicode_buffer(n + 2)
        self.u.SendMessageTimeoutW(h, WM_GETTEXT, n + 1, self.ct.addressof(buf), SMTO_ABORTIFHUNG, 800, self.ct.byref(res))
        return buf.value

    def append_text(self, h, text: str) -> None:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        buf = self.ct.create_unicode_buffer(text)
        self.send(h, EM_SETSEL, self.ct.c_size_t(-1).value, self.ct.c_size_t(-1).value)  # caret to the end
        self.send(h, EM_REPLACESEL, 1, self.ct.addressof(buf))

    def type_chars(self, h, text: str) -> None:
        units = text.replace("\r\n", "\n").replace("\n", "\r").encode("utf-16-le")
        for i in range(0, len(units), 2):
            self.u.PostMessageW(h, WM_CHAR, int.from_bytes(units[i:i + 2], "little"), 0)
            time.sleep(0.006)

    def restore_foreground(self, target) -> None:
        """Hand focus back to `target` if something (e.g. a freshly launched Notepad) grabbed it."""
        if not target or not self.u.IsWindow(target) or self.u.GetForegroundWindow() == target:
            return
        fg = self.u.GetForegroundWindow()
        tid_fg = self.u.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_me = self.k.GetCurrentThreadId()
        if tid_fg and tid_fg != tid_me:
            self.u.AttachThreadInput(tid_me, tid_fg, True)
        self.u.SetForegroundWindow(target)
        if tid_fg and tid_fg != tid_me:
            self.u.AttachThreadInput(tid_me, tid_fg, False)

    def place_without_activating(self, h, w: int, hgt: int) -> None:
        """Top-right of the work area, brought to the front of the z-order but NOT activated."""
        rect = self.wt.RECT()
        self.u.SystemParametersInfoW(0x30, 0, self.ct.byref(rect), 0)  # SPI_GETWORKAREA
        x, y = max(0, rect.right - w - 24), rect.top + 80
        self.u.ShowWindow(h, 4)  # SW_SHOWNOACTIVATE
        flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
        self.u.SetWindowPos(h, self.wt.HWND(-1), x, y, w, hgt, flags)  # HWND_TOPMOST: jump to the top...
        self.u.SetWindowPos(h, self.wt.HWND(-2), x, y, w, hgt, flags)  # ...then HWND_NOTOPMOST: stay a normal window


# ---------------------------------------------------------------- the sink: file + Notepad
class NoteSink:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = Path(os.path.expanduser(cfg.notes_file))
        self.win = _Win() if (_W and cfg.notes_live_notepad) else None
        self.hwnd = 0      # Notepad top-level window
        self.edit = 0      # its text control
        self.live = bool(self.win)
        self._opening: threading.Thread | None = None
        self._started = False
        self._prev_fg = 0

    # -- opening Notepad (in the background, so Moss can say "go ahead" meanwhile)
    def open_async(self) -> None:
        if self.win and self.live and not self._opening:
            self._prev_fg = int(self.win.u.GetForegroundWindow() or 0)
            self._opening = threading.Thread(target=self._open_blank, daemon=True)
            self._opening.start()

    def _launch(self, args: list[str]):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 4  # SW_SHOWNOACTIVATE (some Notepad builds ignore it; we fix focus below)
        before = set(self.win.top_windows("Notepad"))
        subprocess.Popen(["notepad.exe", *args], startupinfo=si)
        deadline = time.time() + 6
        h = 0
        while time.time() < deadline and not h:
            time.sleep(0.15)
            now = self.win.top_windows("Notepad")
            new = [x for x in now if x not in before]
            h = new[0] if new else 0
            if not h and now and time.time() > deadline - 4.5:  # Win11 may open a tab in the existing window
                h = now[0]
            self.win.restore_foreground(self._prev_fg)
        if h:
            self.win.place_without_activating(h, 480, 320)
            for _ in range(8):  # Notepad can grab focus a moment after it appears
                self.win.restore_foreground(self._prev_fg)
                time.sleep(0.1)
        return h

    def _open_blank(self) -> None:
        try:
            self.hwnd = self._launch([])
            for _ in range(20):  # the edit control appears a beat after the window
                self.edit = self.win.edit_child(self.hwnd) if self.hwnd else 0
                if self.edit:
                    break
                time.sleep(0.15)
            if not self.edit:
                self.live = False
        except Exception as e:
            print(f"[notes] couldn't open Notepad: {e}")
            self.live = False

    # -- writing
    def _file_append(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            f.write(text.replace("\n", "\r\n"))

    def write(self, line: str) -> str:
        """Returns 'live' (typed into Notepad) or 'file' (saved to the notes file only)."""
        text = ""
        if not self._started:
            self._started = True
            text += f"== {datetime.now():%a %d %b %Y, %H:%M} ==\n"
        text += f"- {line}\n"
        self._file_append(text)  # the safe copy, always first
        if not (self.win and self.live):
            return "file"
        if self._opening:
            self._opening.join(8)
        if not self.live or not self.edit or not self.win.u.IsWindow(self.edit):
            return self._fallback()
        before = self.win.get_text(self.edit)
        self.win.append_text(self.edit, text)
        if self._landed(self.win.get_text(self.edit), before, line):
            return "live"
        self.win.type_chars(self.edit, text)  # second method: simulate key presses straight to the control
        time.sleep(0.15)
        if self._landed(self.win.get_text(self.edit), before, line):
            return "live"
        return self._fallback()

    @staticmethod
    def _landed(after: str, before: str, line: str) -> bool:
        return len(after) > len(before) and line.strip()[-25:] in after.replace("\r", "")

    def _fallback(self) -> str:
        """Typing into this Notepad build isn't possible: show the notes file in Notepad instead."""
        print("[notes] couldn't type into Notepad directly; opening the notes file there instead.")
        self.live = False
        try:
            if self.hwnd and self.win.u.IsWindow(self.hwnd):
                self.win.u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)  # the blank, unmodified window
                time.sleep(0.3)
            self.hwnd = self._launch([str(self.path)])
        except Exception as e:
            print(f"[notes] {e}")
        return "file"

    def end_session(self) -> None:
        self._started = False  # next session gets a fresh date header


# ---------------------------------------------------------------- the skill
class NotesSkill(Skill):
    name = "notes"
    description = "Take voice notes into Notepad (and a notes.txt file)."

    def __init__(self, cfg):
        self.cfg = cfg
        self.sink = NoteSink(cfg)
        self.active = False
        self.count = 0
        self._last = 0.0

    def handle(self, text: str, body: str) -> Result | None:
        rest = parse_note_start(body)
        if rest is None:
            return None
        self._last = time.time()
        self.count = 0
        if rest:  # "take a note: buy milk" - one shot
            self.sink.open_async()
            self._save(rest)
            self._finish()
            return Result("[happy] Noted.", toast="noted")
        self.active = True
        self.sink.open_async()
        return Result("[relaxed] Go ahead, I'm listening.")

    def handle_active(self, text: str, body: str) -> Result | None:
        if time.time() - self._last > self.cfg.notes_session_timeout_s:
            self._finish()  # went quiet a while ago: this is normal conversation again
            return None
        self._last = time.time()
        if is_note_end(text):
            n = self.count
            self._finish()
            if n == 0:
                return Result("[neutral] Okay, no note then.")
            return Result(f"[happy] Saved {n} note{'s' if n != 1 else ''}.")
        self._save(body.strip())
        return Result("", toast="noted")  # silent: the text appearing in Notepad is the feedback

    def _save(self, line: str) -> None:
        how = self.sink.write(line)
        self.count += 1
        print(f"[notes] saved ({how}): {line}")

    def _finish(self) -> None:
        self.active = False
        self.sink.end_session()
