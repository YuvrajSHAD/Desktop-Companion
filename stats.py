"""The lazy score: what Moss did for you today, and a rough estimate of the time it saved.

Pure python. The time per chore is an ESTIMATE of how long it would take you by hand
(open the bin and empty it, find Notepad and type, reach for the keyboard, ...). Say so in your write-up.
"""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path

# seconds a chore would take you by hand (rough, deliberately conservative)
SECONDS = {"recycle": 45, "note": 30, "next": 10, "previous": 12, "volume_up": 8, "volume_down": 8,
           "mute": 5, "read_notes": 40}


def spoken_time(secs: int) -> str:
    if secs < 60:
        return f"{secs} second{'s' if secs != 1 else ''}"
    m = round(secs / 60)
    return f"{m} minute{'s' if m != 1 else ''}"


def reaction(n: int) -> str:
    if n >= 20:
        return "Legendary laziness."
    if n >= 10:
        return "I'm proud of us."
    if n >= 3:
        return "We're getting somewhere. Slowly."
    return "Not bad for a sloth."


def line(n: int, secs: int) -> str:
    """'[happy] That's 11 chores and about 9 minutes today. I'm proud of us.'"""
    if n == 0:
        return "[sleepy] Nothing yet today. Peak laziness, and we haven't even started."
    return f"[happy] That's {n} chore{'s' if n != 1 else ''} and about {spoken_time(secs)} today. {reaction(n)}"


class Tally:
    def __init__(self, path, today=datetime.date.today):
        self.path, self.today = Path(path), today
        self.days: dict = {}
        try:
            self.days = json.loads(self.path.read_text(encoding="utf-8")).get("days", {})
        except (OSError, ValueError):
            pass

    def _day(self) -> dict:
        return self.days.setdefault(self.today().isoformat(), {"n": 0, "s": 0, "by": {}})

    def record(self, kind: str) -> tuple[int, int]:
        """Count one finished chore. Returns today's (chores, seconds saved)."""
        d = self._day()
        d["n"] += 1
        d["s"] += SECONDS.get(kind, 10)
        d["by"][kind] = d["by"].get(kind, 0) + 1
        self._save()
        return d["n"], d["s"]

    def today_stats(self) -> tuple[int, int]:
        d = self.days.get(self.today().isoformat())
        return (d["n"], d["s"]) if d else (0, 0)

    def total(self) -> tuple[int, int]:
        return sum(d["n"] for d in self.days.values()), sum(d["s"] for d in self.days.values())

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"days": self.days}, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:  # never crash a chore over a stats file
            print(f"[stats] couldn't save: {e}", flush=True)
