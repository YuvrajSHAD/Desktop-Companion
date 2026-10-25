"""Moss's chores, as spoken conversations.

Skills never touch the microphone or speakers directly. main.py hands it two functions:
    say(line)                     speak a "[mood] text" line
    hear(timeout_s, patient=...)  listen for one reply, "" if nothing was heard
and (for tests) a fake `ops` in place of winops.
"""
from __future__ import annotations
import random
import time
from pathlib import Path

import intents
import winops
from intents import NEXT, NOTE, PREV, RECYCLE
from textutil import split_emotion

EMPTY_ALREADY = [
    "[relaxed] The recycle bin's already empty. My favourite kind of chore.",
    "[neutral] Nothing in there. Already clean.",
]
CANCELLED = ["[relaxed] Okay, leaving it alone.", "[neutral] Fine by me. Nothing deleted."]
EMPTYING = ["[relaxed] Emptying it. Slowly, as is tradition.", "[sleepy] On it. Mostly."]
NEXT_LINES = ["[relaxed] Next one.", "[neutral] Skipped.", "[happy] Onwards."]
PREV_LINES = ["[relaxed] Back we go.", "[neutral] Previous song.", "[happy] Rewinding."]


class Skills:
    def __init__(self, cfg, say, hear, ops=winops, rng: random.Random | None = None, clock=time.monotonic, sleep=time.sleep):
        self.cfg, self._say, self.hear, self.ops = cfg, say, hear, ops
        self.rng, self.clock, self.sleep = rng or random.Random(), clock, sleep
        self.said: list[str] = []      # what Moss said during the last chore (for its memory)
        self._notepad_opened = False
        self._last_skip = -1e9         # when we last pressed next/previous

    # ----------------------------------------------------------- plumbing
    def say(self, line: str) -> None:
        self.said.append(split_emotion(line)[1])
        self._say(line)

    def pick(self, lines: list[str]) -> str:
        return self.rng.choice(lines)

    def handle(self, it: intents.Intent) -> bool:
        """Do the chore. Always speaks the outcome, including failures. Returns False for unknown intents."""
        self.said.clear()
        try:
            if it.kind == RECYCLE:
                self._recycle()
            elif it.kind == NOTE:
                self._note(it.note)
            elif it.kind in (NEXT, PREV):
                self._skip(it.kind)
            else:
                return False
        except winops.Unsupported:
            self.say("[sad] That chore only works on Windows, sadly.")
        except Exception as e:  # never crash the voice loop over a chore
            print(f"[chore] {it.kind} failed: {e}", flush=True)
            self.say("[sad] That didn't work. I've left the details in the console.")
        return True

    # ----------------------------------------------------------- recycle bin
    def _recycle(self) -> None:
        info = self.ops.recycle_bin_info()
        if info is not None and info[0] == 0:
            self.say(self.pick(EMPTY_ALREADY))
            return
        if info:
            n, size = info
            self.say(f"[surprised] That's {n} item{'s' if n != 1 else ''}, about {intents.human_size(size)}. "
                     "Emptying is permanent. Say yes to go ahead.")
        else:
            self.say("[neutral] I can't tell how full it is. Emptying is permanent. Say yes to go ahead.")
        answer = self.hear(self.cfg.confirm_timeout_s)
        if not answer:
            self.say("[sleepy] No answer, so I left it alone.")
        elif not intents.is_yes(answer):
            self.say(self.pick(CANCELLED))
        else:
            self.say(self.pick(EMPTYING))
            self.ops.empty_recycle_bin()
            freed = f" That's {intents.human_size(info[1])} back." if info and info[1] else ""
            self.say(f"[happy] Done.{freed}")

    # ----------------------------------------------------------- notes
    def _note(self, text: str) -> None:
        if not text:
            self.say("[happy] Go ahead, I'm listening.")
            text = self.hear(self.cfg.note_timeout_s, patient=True)
            if not text:
                self.say("[sleepy] I didn't catch anything, so no note. Ask again when you're ready.")
                return
            if intents.is_cancel(text):
                self.say("[relaxed] Okay, scrapped it.")
                return
        path = self.ops.append_note(Path(self.cfg.notes_path), text)
        opened = True
        mode = self.cfg.notes_open
        if mode == "always" or (mode == "first" and not self._notepad_opened):
            try:
                self.ops.open_in_notepad(path)
                self._notepad_opened = True
            except Exception as e:
                print(f"[chore] couldn't open Notepad: {e}", flush=True)
                opened = False
        said = f"Noted: {text}" if len(text) <= 80 else "Noted. That one's a long one, but it's saved."
        self.say(f"[happy] {said}" + ("" if opened else " I saved it but couldn't open Notepad."))

    # ----------------------------------------------------------- Spotify
    def _skip(self, kind: str) -> None:
        if self.cfg.media_require_spotify and not self.ops.spotify_running():
            self.say("[neutral] I don't see Spotify running, so I'm not touching your other players.")
            return
        presses = 1
        # Spotify's "previous" only changes track after the first 3 s, otherwise it restarts the song.
        # Mid-song we press twice (restart, then previous); right after a skip once is enough.
        if kind == PREV and self.cfg.media_prev_twice and self.clock() - self._last_skip > 3.5:
            presses = 2
        for i in range(presses):
            if i:
                self.sleep(0.3)
            self.ops.press_media_key(kind)
        self._last_skip = self.clock()
        self.say(self.pick(NEXT_LINES if kind == NEXT else PREV_LINES))
