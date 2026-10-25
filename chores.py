"""Moss's chores, as spoken conversations (chores.py).

Skills never touch the microphone or speakers directly. main.py hands it two functions:
    say(line)                     speak a "[mood] text" line
    hear(timeout_s, patient=...)  listen for one reply, "" if nothing was heard
and (for tests) a fake `ops` in place of winops.
"""
from __future__ import annotations
import datetime
import random
import time
from pathlib import Path

import intents
import stats
import winops
from intents import INTRO, MUTE, NEXT, NOTE, PREV, READ_NOTES, RECYCLE, STATS, VOL_DOWN, VOL_UP
from textutil import split_emotion

EMPTY_ALREADY = [
    "[relaxed] The recycle bin's already empty. My favourite kind of chore.",
    "[neutral] Nothing in there. Already clean.",
]
CANCELLED = ["[relaxed] Okay, leaving it alone.", "[neutral] Fine by me. Nothing deleted."]
EMPTYING = ["[relaxed] Emptying it. Slowly, as is tradition.", "[sleepy] On it. Mostly."]
NEXT_LINES = ["[relaxed] Next one.", "[neutral] Skipped.", "[happy] Onwards."]
PREV_LINES = ["[relaxed] Back we go.", "[neutral] Previous song.", "[happy] Rewinding."]
UP_LINES = ["[happy] Louder.", "[relaxed] Turning it up.", "[happy] A little more."]
DOWN_LINES = ["[relaxed] Quieter.", "[neutral] Turning it down.", "[sleepy] Shh, shh."]

# The demo introduction ("introduce yourself", or python main.py --intro). Scripted on purpose: it must be
# the same every take, and it only claims things Moss really does.
INTRO_LINES = [
    "[happy] Konnichiwa, everyone! I'm Moss, a very small, very sleepy desktop sloth.",
    "[relaxed] My whole philosophy is slow and steady. I do the boring little chores, so you can stay comfy and lazy.",
    "[happy] I live on your taskbar, and when your music plays, I dance. Ehehe.",
    "[neutral] Just ask, and I will empty your recycle bin. I always ask first, because that is permanent.",
    "[neutral] I take notes and read them back to you. I skip your Spotify songs, and turn the volume up, down, or off.",
    "[surprised] And I keep a lazy score! How many chores I did, and how many minutes I saved you.",
    "[happy] Everything runs on this computer, with Gemma. No cloud, no spying. Yoroshiku onegaishimasu! So, what chore shall we do first?",
]


class Skills:
    def __init__(self, cfg, say, hear, ops=winops, rng: random.Random | None = None, clock=time.monotonic, sleep=time.sleep,
                 tally=None, summarize=None, today=datetime.date.today):
        self.cfg, self._say, self.hear, self.ops = cfg, say, hear, ops
        self.tally, self.summarize, self.today = tally, summarize, today  # lazy score / Gemma note summary (both optional)
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
                done = self._recycle()
            elif it.kind == NOTE:
                done = self._note(it.note)
            elif it.kind in (NEXT, PREV):
                done = self._skip(it.kind)
            elif it.kind in (VOL_UP, VOL_DOWN, MUTE):
                done = self._volume(it)
            elif it.kind == READ_NOTES:
                done = self._read_notes()
            elif it.kind == STATS:
                self.say(self.score_line())
                return True
            elif it.kind == INTRO:
                self.intro()
                return True
            else:
                return False
            if done:
                self._count(it.kind)
        except winops.Unsupported:
            self.say("[sad] That chore only works on Windows, sadly.")
        except Exception as e:  # never crash the voice loop over a chore
            print(f"[chore] {it.kind} failed: {e}", flush=True)
            self.say("[sad] That didn't work. I've left the details in the console.")
        return True

    # ----------------------------------------------------------- lazy score + intro
    def score_line(self) -> str:
        n, secs = self.tally.today_stats() if self.tally else (0, 0)
        return stats.line(n, secs)

    def _count(self, kind: str) -> None:
        """A chore really happened: add it to today's score, and brag every Nth one."""
        if not self.tally:
            return
        n, secs = self.tally.record(kind)
        every = self.cfg.lazy_brag_every
        if every and n % every == 0:
            self.say(stats.line(n, secs))

    def intro(self) -> None:
        for line in INTRO_LINES:
            self.say(line)

    # ----------------------------------------------------------- recycle bin
    def _recycle(self) -> bool:
        info = self.ops.recycle_bin_info()
        if info is not None and info[0] == 0:
            self.say(self.pick(EMPTY_ALREADY))
            return False
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
            return True
        return False

    # ----------------------------------------------------------- notes
    def _note(self, text: str) -> bool:
        if not text:
            self.say("[happy] Go ahead, I'm listening.")
            text = self.hear(self.cfg.note_timeout_s, patient=True)
            if not text:
                self.say("[sleepy] I didn't catch anything, so no note. Ask again when you're ready.")
                return False
            if intents.is_cancel(text):
                self.say("[relaxed] Okay, scrapped it.")
                return False
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
        return True

    def _read_notes(self) -> bool:
        """'What did I note today?' Gemma summarises today's lines of Moss Notes.txt and Moss says it back."""
        notes = self.ops.read_notes(Path(self.cfg.notes_path), self.today())
        if not notes:
            self.say("[relaxed] You haven't noted anything today. A clean slate.")
            return False
        if len(notes) == 1:
            self.say(f"[neutral] One note today: {notes[0]}")
            return True
        spoken = ""
        if self.summarize:
            try:
                spoken = (self.summarize(notes) or "").strip()
            except Exception as e:  # fall back to reading them out
                print(f"[chore] summary failed: {e}", flush=True)
        if not spoken:
            spoken = f"{len(notes)} notes. " + ". ".join(notes[-3:])
        self.say(f"[neutral] {len(notes)} notes today. {spoken}")
        return True

    def _volume(self, it) -> bool:
        if it.kind == MUTE:
            self.ops.press_volume("mute", 1)
            self.say("[relaxed] Unmuted." if it.amt == "un" else "[relaxed] Muted. Shh.")
            return True
        presses = self.cfg.volume_presses
        presses = max(1, presses // 2) if it.amt == "small" else presses * 2 if it.amt == "big" else presses
        self.ops.press_volume(it.kind, presses)
        self.say(self.pick(UP_LINES if it.kind == VOL_UP else DOWN_LINES))
        return True

    # ----------------------------------------------------------- Spotify
    def _skip(self, kind: str) -> bool:
        if self.cfg.media_require_spotify and not self.ops.spotify_running():
            self.say("[neutral] I don't see Spotify running, so I'm not touching your other players.")
            return False
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
        return True
