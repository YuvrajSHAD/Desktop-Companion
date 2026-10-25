"""The real-world side effects of Moss's chores (Windows).

Kept separate from the voice flow (chores.py) so the flow can be tested with a fake.
Only append_note() works off-Windows; the rest raise Unsupported.
"""
from __future__ import annotations
import ctypes
import datetime
import re
import subprocess
import time
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000


class Unsupported(RuntimeError):
    pass


def _need_windows():
    if not IS_WIN:
        raise Unsupported("this chore only works on Windows")


# ------------------------------------------------------------------ recycle bin
class _RBInfo(ctypes.Structure):  # SHQUERYRBINFO (natural alignment, 24 bytes on 64-bit)
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_info() -> tuple[int, int] | None:
    """(item count, bytes) across all drives, or None if Windows won't say."""
    _need_windows()
    info = _RBInfo()
    info.cbSize = ctypes.sizeof(info)
    hr = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    return (int(info.i64NumItems), int(info.i64Size)) if hr == 0 else None


def empty_recycle_bin() -> None:
    """Empties it for good, with no Windows dialog, progress window or sound."""
    _need_windows()
    SHERB_NOCONFIRMATION, SHERB_NOPROGRESSUI, SHERB_NOSOUND = 0x1, 0x2, 0x4
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND)
    if hr != 0:
        raise OSError(f"SHEmptyRecycleBin failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})")


# ------------------------------------------------------------------ notes
def append_note(path, text: str, now: datetime.datetime | None = None) -> Path:
    """Append '[2026-10-25 14:40] text' to the notes file (CRLF so even old Notepad is happy)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = now or datetime.datetime.now()
    line = " ".join(text.split())
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(f"[{now:%Y-%m-%d %H:%M}] {line}\r\n")
    return path


def read_notes(path, day: datetime.date | None = None) -> list[str]:
    """Note texts from the notes file ('[2026-10-25 14:40] text'); only those of `day` if given."""
    try:
        raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    want = day.isoformat() if day else None
    out = []
    for ln in raw.splitlines():
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]\s*(.*)$", ln.strip())
        if m and m.group(2) and (want is None or m.group(1) == want):
            out.append(m.group(2))
    return out


def open_in_notepad(path) -> None:
    _need_windows()
    subprocess.Popen(["notepad.exe", str(path)])


# ------------------------------------------------------------------ Spotify (media keys)
_VK = {"next": 0xB0, "previous": 0xB1}  # VK_MEDIA_NEXT_TRACK / VK_MEDIA_PREV_TRACK


def press_media_key(kind: str) -> None:
    """Same as pressing the keyboard's media key; Spotify listens to it even when it's in the background."""
    _need_windows()
    vk = _VK[kind]
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
    u = ctypes.windll.user32
    u.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    u.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


_VOL = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}  # VK_VOLUME_UP / DOWN / MUTE


def press_volume(kind: str, presses: int = 1) -> None:
    """Same as the keyboard's volume keys (system-wide). On Windows each press is about 2 percent."""
    _need_windows()
    vk = _VOL[kind]
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
    u = ctypes.windll.user32
    for _ in range(max(1, presses)):
        u.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        u.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)


def spotify_running() -> bool:
    _need_windows()
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Spotify.exe", "/NH"],
                         capture_output=True, text=True, creationflags=CREATE_NO_WINDOW).stdout
    return "spotify.exe" in out.lower()


if __name__ == "__main__":
    # Safe self-check on your PC:  python winops.py            (reads only, writes a test note)
    #                              python winops.py --next     (also presses the Spotify "next" key)
    import tempfile

    print("recycle bin (items, bytes):", recycle_bin_info())
    print("Spotify running:", spotify_running())
    p = append_note(Path(tempfile.gettempdir()) / "moss_test_note.txt", "hello from Moss")
    print("test note written to", p)
    print("notes from today:", read_notes(p, datetime.date.today()))
    if "--volume" in sys.argv:
        press_volume("volume_up", 3)
        press_volume("volume_down", 3)
        print("pressed volume up x3, then down x3")
    if "--next" in sys.argv:
        press_media_key("next")
        print("pressed the media 'next' key")
