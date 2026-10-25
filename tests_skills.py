"""Self-tests for the voice chores (run: python tests_skills.py). No GPU, mic or Windows needed:
the Windows calls are replaced by a fake, and the mic by scripted frames."""
from __future__ import annotations
import json
import random
import sys
import tempfile
import types
from pathlib import Path

import intents as I
from config import Config
from chores import Skills


# --------------------------------------------------------------------------- parser
def test_parser():
    P = lambda s: (lambda r: None if r is None else (r.kind, r.note))(I.parse(s))
    fire = {
        "Moss, take a note.": ("note", ""),
        "Hey Moss, can you take a note?": ("note", ""),
        "Take a note buy milk tomorrow": ("note", "buy milk tomorrow"),
        "Moss take a note, call mom at 5.": ("note", "call mom at 5."),
        "make a note that I need to fix the build": ("note", "I need to fix the build"),
        "note to self: pay rent": ("note", "pay rent"),
        "write this down": ("note", ""),
        "Moss, empty the recycle bin.": ("recycle", ""),
        "hey moss can you please empty the recycling bin": ("recycle", ""),
        "Empty the re-cycle bin": ("recycle", ""),
        "clear the trash": ("recycle", ""),
        "next song": ("next", ""),
        "Moss, skip this song.": ("next", ""),
        "skip": ("next", ""),
        "play the next song on spotify": ("next", ""),
        "change the song": ("next", ""),
        "previous song": ("previous", ""),
        "Moss, go back to the previous song": ("previous", ""),
        "play the last song": ("previous", ""),
        "go back": ("previous", ""),
    }
    never = [
        "What's the next song on that album?", "skip the intro", "I emptied the recycle bin yesterday",
        "don't empty the recycle bin", "how do I empty the recycle bin", "I was going to take a note about it",
        "back", "what was the last song you played", "tell me a joke", "I'll go back to work", "play some music",
        "the next time I see you",
    ]
    for s, exp in fire.items():
        assert P(s) == exp, (s, P(s), exp)
    for s in never:
        assert P(s) is None, (s, P(s))
    # looser phrasing is only *flagged* for the LLM, never fired directly
    assert P("could you maybe flip to the following song") is None
    assert I.maybe_command("the recycle thing is full") and not I.maybe_command("tell me a joke")
    assert I.from_action({"action": "take_note", "note": " hi "}) == I.Intent("note", "hi")
    assert I.from_action({"action": "next_song", "note": "ignored"}) == I.Intent("next")
    assert I.from_action({"action": "none"}) is None and I.from_action("garbage") is None
    for y in ["yes", "Yeah, do it", "go ahead", "yes please", "empty it"]:
        assert I.is_yes(y), y
    for n in ["no", "no don't", "okay no wait", "hmm", "cancel"]:
        assert not I.is_yes(n), n
    assert I.is_cancel("never mind") and I.is_cancel("Cancel that") and not I.is_cancel("buy milk")
    assert I.human_size(1288490188) == "1.2 gigabytes" and I.human_size(350 << 20) == "350 megabytes"
    print("ok parser")


# --------------------------------------------------------------------------- flows
class FakeOps:
    Unsupported = RuntimeError

    def __init__(self, bin_info=(3, 5 << 20), spotify=True):
        self.bin, self.spotify = bin_info, spotify
        self.log: list = []

    def recycle_bin_info(self): return self.bin
    def empty_recycle_bin(self): self.log.append("empty")
    def spotify_running(self): return self.spotify
    def press_media_key(self, k): self.log.append(("key", k))
    def open_in_notepad(self, p): self.log.append(("notepad", Path(p).name))
    def press_volume(self, k, n=1): self.log.append(("vol", k, n))
    def read_notes(self, path, day=None):
        import winops
        return winops.read_notes(path, day)

    def append_note(self, path, text):
        import winops
        self.log.append(("note", text))
        return winops.append_note(path, text)


def make(tmp, replies=(), **ops_kw):
    cfg = Config(notes_path=str(Path(tmp) / "n" / "Moss Notes.txt"))
    spoken, heard_args, queue = [], [], list(replies)
    ops = FakeOps(**ops_kw)
    clock = [100.0]
    sk = Skills(cfg, spoken.append,
                lambda t, patient=False: (heard_args.append((t, patient)), queue.pop(0) if queue else "")[1],
                ops=ops, rng=random.Random(1), clock=lambda: clock[0], sleep=lambda s: None)
    return sk, ops, spoken, heard_args, clock


def test_flows():
    with tempfile.TemporaryDirectory() as tmp:
        # recycle bin: asks, then empties on "yes"
        sk, ops, said, _, _ = make(tmp, ["yes do it"])
        sk.handle(I.Intent(I.RECYCLE))
        assert ops.log == ["empty"], ops.log
        assert "3 items" in said[0] and "5 megabytes" in said[0] and "permanent" in said[0], said
        assert "Done" in said[-1] and "5 megabytes back" in said[-1]
        # ...does NOT empty on "no", on silence, or on a vague answer
        for ans in (["no"], [], ["hmm what"]):
            sk, ops, said, _, _ = make(tmp, ans)
            sk.handle(I.Intent(I.RECYCLE))
            assert ops.log == [], (ans, ops.log)
        # already empty -> never asks
        sk, ops, said, heard, _ = make(tmp, ["yes"], bin_info=(0, 0))
        sk.handle(I.Intent(I.RECYCLE))
        assert ops.log == [] and heard == [] and "empty" in said[0].lower()
        # unknown size still asks first
        sk, ops, said, _, _ = make(tmp, ["yes"], bin_info=None)
        sk.handle(I.Intent(I.RECYCLE))
        assert ops.log == ["empty"] and "can't tell" in said[0]

        # notes: dictated in a second utterance (patient listening), file written, Notepad opened once
        sk, ops, said, heard, _ = make(tmp, ["buy milk and eggs", "call mom"])
        sk.handle(I.Intent(I.NOTE))
        assert heard[0][1] is True, "dictation must use patient listening"
        sk.handle(I.Intent(I.NOTE, "call mom"))
        assert [e for e in ops.log if e[0] == "notepad"] == [("notepad", "Moss Notes.txt")], ops.log  # only the first time
        body = (Path(tmp) / "n" / "Moss Notes.txt").read_bytes().decode("utf-8")
        lines = body.split("\r\n")
        assert len(lines) == 3 and lines[2] == "" and lines[0].endswith("] buy milk and eggs") and lines[1].endswith("] call mom"), lines
        assert said[1] == "[happy] Noted: buy milk and eggs", said
        # cancelled / nothing heard -> no note written
        sk, ops, said, _, _ = make(tmp, ["never mind"])
        sk.handle(I.Intent(I.NOTE)); assert not [e for e in ops.log if e[0] == "note"]
        sk, ops, said, _, _ = make(tmp, [])
        sk.handle(I.Intent(I.NOTE)); assert not [e for e in ops.log if e[0] == "note"] and "didn't catch" in said[-1]

        # spotify: next = one press; previous = two presses mid-song, one right after a skip
        sk, ops, said, _, clock = make(tmp)
        sk.handle(I.Intent(I.NEXT)); assert ops.log == [("key", "next")]
        ops.log.clear(); clock[0] += 1.0
        sk.handle(I.Intent(I.PREV)); assert ops.log == [("key", "previous")], "just skipped: a single press"
        ops.log.clear(); clock[0] += 30
        sk.handle(I.Intent(I.PREV)); assert ops.log == [("key", "previous")] * 2, "mid-song: restart + previous"
        # spotify closed -> says so, presses nothing (so it can't skip your YouTube)
        sk, ops, said, _, _ = make(tmp, spotify=False)
        sk.handle(I.Intent(I.NEXT)); assert ops.log == [] and "Spotify" in said[0]

        # a crashing chore is reported, not raised
        sk, ops, said, _, _ = make(tmp, ["yes"])
        ops.empty_recycle_bin = lambda: (_ for _ in ()).throw(OSError("boom"))
        assert sk.handle(I.Intent(I.RECYCLE)) is True and "didn't work" in said[-1]
    print("ok flows")


# --------------------------------------------------------------------------- brain + listener (stubbed deps)
def test_brain_and_listener():
    class Msg:  # ollama-like response
        def __init__(self, c): self.message = types.SimpleNamespace(content=c)

    class FakeClient:
        def __init__(self, host=None): self.calls = []
        def chat(self, **kw):
            self.calls.append(kw)
            return Msg(json.dumps({"action": "next_song", "note": ""}))

    sys.modules["ollama"] = types.SimpleNamespace(Client=FakeClient)
    from brain import Brain

    b = Brain(Config())
    it = b.classify("could you maybe flip to the following song")
    assert it == I.Intent("next")
    kw = b.client.calls[0]
    assert kw["format"] == I.CLASSIFY_SCHEMA and kw["options"]["num_ctx"] == Config().llm_num_ctx and kw["options"]["temperature"] == 0
    b.client.chat = lambda **k: Msg("not json")
    assert b.classify("x") is None  # bad output -> no action
    b.history = []
    for i in range(20):
        b.remember(f"u{i}", f"a{i}")
    assert len(b.history) == Config().history_turns * 2 and b.history[0]["role"] == "user"

    # Listener.listen(timeout=...) gives up when nobody speaks, and still captures speech otherwise
    import numpy as np
    sys.modules["sounddevice"] = types.SimpleNamespace()
    sys.modules["webrtcvad"] = types.SimpleNamespace(Vad=lambda a: types.SimpleNamespace(is_speech=lambda b, sr: True))
    import audio_io

    class Mic:
        def __init__(self, loud_after): self.n, self.loud_after = 0, loud_after
        def read(self, t=0.5):
            self.n += 1
            return np.full(audio_io.FRAME_SAMPLES, 3000 if self.n > self.loud_after else 0, np.int16)

    cfg = Config(min_rms=150)
    t0 = __import__("time").perf_counter()
    assert audio_io.Listener(Mic(10**9), cfg).listen(timeout=0.2) is None
    assert __import__("time").perf_counter() - t0 < 1.0
    got = audio_io.Listener(Mic(5), cfg).listen(timeout=5, max_s=0.6)  # speaks, runs to the 0.6 s cap
    assert got is not None and 0.5 < len(got) / 16000 < 0.8, None if got is None else len(got) / 16000
    print("ok brain + listener")


def test_new_parsers():
    P = lambda s: (lambda r: None if r is None else (r.kind, r.amt))(I.parse(s))
    fire = {
        "volume up": ("volume_up", ""), "turn it up": ("volume_up", ""), "Moss, make it louder please": ("volume_up", ""),
        "turn the volume down": ("volume_down", ""), "a little quieter": ("volume_down", "small"),
        "lower the volume a lot": ("volume_down", "big"), "turn the music down": ("volume_down", ""),
        "mute": ("mute", ""), "unmute the sound": ("mute", "un"),
        "what did I note today": ("read_notes", ""), "read my notes": ("read_notes", ""),
        "summarize my notes": ("read_notes", ""), "what's in my notes": ("read_notes", ""),
        "how lazy was I today": ("lazy_score", ""), "what's my lazy score": ("lazy_score", ""),
        "how much time did you save me": ("lazy_score", ""),
        "introduce yourself": ("intro", ""), "start the demo": ("intro", ""), "say hello to everyone": ("intro", ""),
    }
    never = ["pick it up", "look it up", "what's the volume of a sphere", "what is a note in music", "I turned the volume up yesterday",
             "don't mute", "my score in the game was bad", "tell me a joke", "what did I eat today", "up", "the sound of silence", "who are you"]
    for t, exp in fire.items():
        assert P(t) == exp, (t, P(t), exp)
    for t in never:
        assert P(t) is None, (t, P(t))
    assert I.maybe_command("could you make it a bit quieter") and I.maybe_command("could you tell me my laziness numbers, chores and all")
    assert I.from_action({"action": "volume_up", "amount": "big"}) == I.Intent("volume_up", "", "big")
    assert I.from_action({"action": "mute"}) == I.Intent("mute")
    print("ok new parsers")


def test_new_flows():
    import datetime, stats
    with tempfile.TemporaryDirectory() as tmp:
        # volume: presses scale with "a little" / "a lot", mute presses once, nothing needs Spotify
        sk, ops, said, _, _ = make(tmp, spotify=False)
        sk.handle(I.Intent("volume_up")); sk.handle(I.Intent("volume_down", "", "small")); sk.handle(I.Intent("volume_up", "", "big")); sk.handle(I.Intent("mute"))
        assert ops.log == [("vol", "volume_up", 5), ("vol", "volume_down", 2), ("vol", "volume_up", 10), ("vol", "mute", 1)], ops.log

        # lazy score: only chores that really happened count; brag every 5th; it persists
        path = Path(tmp) / "stats.json"
        tally = stats.Tally(path)
        sk, ops, said, _, _ = make(tmp, ["no"], spotify=True)
        sk.tally = tally
        sk.handle(I.Intent("recycle"))        # answered "no" -> not counted
        assert tally.today_stats() == (0, 0)
        for _ in range(4):
            sk.handle(I.Intent("next"))
        assert tally.today_stats()[0] == 4 and not any("chores" in x for x in said)
        sk.handle(I.Intent("volume_up"))      # 5th -> brags
        assert "That's 5 chores and about 48 seconds today" in said[-1], said[-1]
        sk.handle(I.Intent("lazy_score")); assert "5 chores" in said[-1]
        assert stats.Tally(path).today_stats()[0] == 5, "must be saved to disk"
        sk2, _, _, _, _ = make(tmp, spotify=False); sk2.tally = tally
        sk2.handle(I.Intent("next")); assert tally.today_stats()[0] == 5, "Spotify closed: nothing happened, nothing counted"
        assert stats.line(11, 540) == "[happy] That's 11 chores and about 9 minutes today. I'm proud of us."
        assert stats.line(1, 30) == "[happy] That's 1 chore and about 30 seconds today. Not bad for a sloth."
        assert "Nothing yet" in stats.line(0, 0)

        # read notes: today only, Gemma summary, fallbacks
        notes = Path(tmp) / "n" / "Moss Notes.txt"
        notes.parent.mkdir(exist_ok=True)
        today = datetime.date(2026, 10, 25)
        notes.write_bytes(("[2026-10-24 09:00] old news\r\n[2026-10-25 09:00] buy milk\r\n[2026-10-25 12:30] call mom\r\n").encode())
        sk, ops, said, _, _ = make(tmp); sk.today = lambda: today
        sk.summarize = lambda n: f"Buy milk and call mom. ({len(n)})"
        sk.handle(I.Intent("read_notes")); assert said[-1] == "[neutral] 2 notes today. Buy milk and call mom. (2)", said
        sk.summarize = lambda n: (_ for _ in ()).throw(RuntimeError("ollama down"))
        sk.handle(I.Intent("read_notes")); assert "buy milk" in said[-1] and "old news" not in said[-1], said[-1]
        sk, ops, said, _, _ = make(tmp); sk.today = lambda: datetime.date(2026, 10, 26)
        sk.handle(I.Intent("read_notes")); assert "haven't noted anything" in said[-1]

        # intro: scripted, mentions what she can do, never counted as a chore
        sk, ops, said, _, _ = make(tmp); sk.tally = stats.Tally(Path(tmp) / "s2.json")
        sk.handle(I.Intent("intro"))
        text = " ".join(said).lower()
        assert len(said) >= 6 and "moss" in text and "recycle" in text and "volume" in text and "lazy score" in text and "notes" in text
        assert sk.tally.today_stats() == (0, 0)
    print("ok new flows")


def test_persona():
    from persona import system_prompt
    p = system_prompt(Config())
    assert "recycle bin" in p and "Spotify" in p and "take a note" in p and "{" not in p
    print("ok persona")


if __name__ == "__main__":
    test_parser()
    test_flows()
    test_new_parsers()
    test_new_flows()
    test_brain_and_listener()
    test_persona()
    print("all chore tests passed")
