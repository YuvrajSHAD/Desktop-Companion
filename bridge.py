"""WebSocket bridge between the voice/brain loop and the desktop body (Electron).

Security: binds to 127.0.0.1 only, and a client must send a hello containing a random
token (written to .bridge_token at startup) before it receives anything. A web page in
your browser can reach localhost, but it can't read that file, so it can't listen in on
your conversation.
"""
from __future__ import annotations
import asyncio
import json
import secrets
import threading
from pathlib import Path

from websockets.asyncio.server import serve


class NullBridge:
    """Stand-in when the body is disabled, so callers never need an `if`."""

    def emit(self, ev: dict) -> None:
        pass


class Bridge:
    def __init__(self, port: int, token_file: Path):
        self.port = port
        self.token = secrets.token_hex(16)
        self.token_file = Path(token_file)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set = set()
        self.on_event = None  # callable(dict) - runs on the bridge thread
        self.tap = None       # optional callable(dict): sees everything we emit (used to mute music while talking)
        self._ready = threading.Event()
        self.error: Exception | None = None

    def start(self) -> None:
        self.token_file.write_text(self.token, encoding="ascii")
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)
        if self.error:
            raise self.error

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except Exception as e:  # e.g. port already in use
            self.error = e
            self._ready.set()

    async def _serve(self) -> None:
        async with serve(self._handler, "127.0.0.1", self.port, max_size=1 << 16):
            self._ready.set()
            await asyncio.Future()

    async def _handler(self, ws) -> None:
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 3))
            ok = hello.get("type") == "hello" and secrets.compare_digest(
                str(hello.get("token", "")), self.token
            )
        except Exception:
            ok = False
        if not ok:
            await ws.close(1008, "unauthorised")
            return
        self.clients.add(ws)
        self._fire({"type": "connected", "hwnd": hello.get("hwnd", 0)})
        try:
            async for msg in ws:
                try:
                    ev = json.loads(msg)
                except Exception:
                    continue
                if isinstance(ev, dict):
                    self._fire(ev)
        except Exception:
            pass
        finally:
            self.clients.discard(ws)
            self._fire({"type": "disconnected"})

    def _fire(self, ev: dict) -> None:
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception as e:
                print(f"[bridge] handler error: {e}")

    def emit(self, ev: dict) -> None:
        if self.tap:
            try:
                self.tap(ev)
            except Exception:
                pass
        if not self.loop or not self.clients:
            return
        data = json.dumps(ev, separators=(",", ":"))
        asyncio.run_coroutine_threadsafe(self._broadcast(data), self.loop)

    async def _broadcast(self, data: str) -> None:
        for ws in list(self.clients):
            try:
                await ws.send(data)
            except Exception:
                self.clients.discard(ws)
