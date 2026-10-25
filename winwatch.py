"""Tells the body where your windows are, so the pet can sit on them (Windows only).

Only geometry is reported (top edges of visible windows). Window titles are never read.
"""
from __future__ import annotations
import sys
import threading
import time

MIN_LEDGE = 140  # ignore ledges narrower than this (px)


def _subtract(segs, a, b):
    out = []
    for s, e in segs:
        if b <= s or a >= e:
            out.append((s, e))
            continue
        if a > s:
            out.append((s, a))
        if b < e:
            out.append((b, e))
    return out


def compute_surfaces(wins, min_width: int = MIN_LEDGE):
    """wins: list of {id,l,t,r,b,fg}, ordered top of z-order first.
    Returns [{id,l,r,y,fg,vis:[[a,b],..]}] where vis = parts of the top edge not covered by higher windows."""
    out = []
    for i, w in enumerate(wins):
        y = w["t"]
        segs = [(w["l"], w["r"])]
        for h in wins[:i]:
            if h["t"] <= y < h["b"]:
                segs = _subtract(segs, h["l"], h["r"])
        vis = [[a, b] for a, b in segs if b - a >= min_width]
        if vis:
            out.append({"id": w["id"], "l": w["l"], "r": w["r"], "y": y, "fg": w["fg"], "vis": vis})
    return out


class WindowWatcher:
    def __init__(self, bridge, hz: float = 15.0):
        self.bridge = bridge
        self.period = 1.0 / hz
        self.own_hwnd = 0
        self.latest = None
        self._last_key = None
        self._stop = threading.Event()

    def start(self):
        if sys.platform != "win32":
            print("[winwatch] Windows only; the pet will just stand on the taskbar.")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def resend(self):
        if self.latest is not None:
            self.bridge.emit(self.latest)

    # ------------------------------------------------------------------
    def _run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        dwm = ctypes.WinDLL("dwmapi")
        try:  # physical pixels, so rects match what Electron converts from
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass

        RECT = wintypes.RECT
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                        "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow"}
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
        cls_buf = ctypes.create_unicode_buffer(128)

        def snapshot():
            fg = user32.GetForegroundWindow()
            fg_id = int(fg) if fg else 0
            wins = []

            def cb(hwnd, _lp):
                if not hwnd or not user32.IsWindowVisible(hwnd):
                    return True
                hid = int(hwnd)
                if hid == self.own_hwnd:
                    return True
                r = RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    return True
                if r.right - r.left < 150 or r.bottom - r.top < 80 or user32.IsIconic(hwnd):
                    return True
                cloaked = wintypes.DWORD(0)
                dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)  # DWMWA_CLOAKED
                if cloaked.value:
                    return True
                if (user32.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
                    return True
                user32.GetClassNameW(hwnd, cls_buf, 128)
                if cls_buf.value in SKIP_CLASSES:
                    return True
                fr = RECT()  # visible frame without the invisible resize border
                if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(fr), ctypes.sizeof(RECT)) == 0:
                    r = fr
                wins.append({"id": hid, "l": r.left, "t": r.top, "r": r.right, "b": r.bottom, "fg": hid == fg_id})
                return True

            user32.EnumWindows(ENUMPROC(cb), 0)  # z-order, topmost first

            fullscreen = False
            if fg:
                r = RECT()
                user32.GetWindowRect(fg, ctypes.byref(r))
                user32.GetClassNameW(fg, cls_buf, 128)
                if cls_buf.value not in SKIP_CLASSES and int(fg) != self.own_hwnd:
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    mon = user32.MonitorFromWindow(fg, 2)  # MONITOR_DEFAULTTONEAREST
                    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                        m = mi.rcMonitor
                        fullscreen = (r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom)
            return wins, fullscreen

        last_sent = 0.0
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                wins, fullscreen = snapshot()
                surf = compute_surfaces(wins)
                key = (tuple((s["id"], s["l"], s["r"], s["y"], tuple(map(tuple, s["vis"]))) for s in surf), fullscreen)
                msg = {
                    "type": "windows",
                    "wins": [{"id": s["id"], "l": s["l"], "r": s["r"], "y": s["y"], "fg": s["fg"], "vis": s["vis"]} for s in surf],
                    "fullscreen": fullscreen,
                }
                self.latest = msg
                if key != self._last_key or t0 - last_sent > 2.0:
                    self._last_key = key
                    last_sent = t0
                    self.bridge.emit(msg)
            except Exception as e:  # never let a hiccup kill the pet
                print(f"[winwatch] {e}")
                time.sleep(1)
            time.sleep(max(0.0, self.period - (time.perf_counter() - t0)))
