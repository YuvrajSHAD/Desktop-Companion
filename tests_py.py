"""Quick self-tests for the pure-python parts (run: python tests_py.py)."""
from textutil import split_emotion, clean_for_tts, pop_sentence
from winwatch import compute_surfaces

assert split_emotion("[happy] Hi there.") == ("happy", "Hi there.")
assert split_emotion("[Sleepy]   Yawn.") == ("sleepy", "Yawn.")
assert split_emotion("No tag here") == (None, "No tag here")
assert clean_for_tts("[laughs] Okay [happy] sure") == "Okay sure"
assert clean_for_tts("[happy]") == ""

W = lambda i, l, t, r, b: {"id": i, "l": l, "t": t, "r": r, "b": b, "fg": False}
# window 1 (on top) spans the row where window 2's top edge sits -> covers x 0..1000 of it
s = compute_surfaces([W(1, 0, 200, 1000, 900), W(2, 200, 300, 1800, 900)])
byid = {x["id"]: x for x in s}
assert byid[1]["vis"] == [[0, 1000]]
assert byid[2]["vis"] == [[1000, 1800]], byid[2]
# fully covered ledge disappears
s = compute_surfaces([W(1, 0, 100, 1000, 900), W(2, 50, 300, 900, 900)])
assert [x["id"] for x in s] == [1], s
# leftover sliver narrower than the minimum ledge is dropped
s = compute_surfaces([W(1, 0, 200, 950, 900), W(2, 0, 300, 1000, 900)])
assert [x["id"] for x in s] == [1], s
# a window whose top edge is below a higher window's bottom stays fully visible
s = compute_surfaces([W(1, 0, 100, 1000, 300), W(2, 0, 500, 1000, 900)])
assert {x["id"]: x["vis"] for x in s}[2] == [[0, 1000]]
# covering window in the middle splits the ledge in two
s = compute_surfaces([W(1, 400, 200, 700, 900), W(2, 0, 300, 1100, 900)])
assert {x["id"]: x["vis"] for x in s}[2] == [[0, 400], [700, 1100]], s
print("python self-tests passed")


def test_beat_tracker():
    """Silence stays inactive; a steady 120 bpm kick pattern turns on, finds beats and ~120 bpm; silence turns it off."""
    import numpy as np
    from music import BeatTracker

    sr = 44100
    tr = BeatTracker(sr, threshold=0.02, min_seconds=1.0, hold_seconds=3.0)
    blk = 1024
    t = 0.0
    dt = blk / sr
    for _ in range(100):
        beat, changed = tr.feed(np.zeros(blk, np.float32), t)
        assert not beat and not changed
        t += dt
    assert not tr.active
    beats, flipped_on = 0, False
    for i in range(int(8 / dt)):
        phase = (t % 0.5) / 0.5  # 120 bpm
        amp = 0.5 if phase < 0.12 else 0.06
        beat, changed = tr.feed(np.full(blk, amp, np.float32), t)
        beats += beat
        flipped_on |= changed and tr.active
        t += dt
    assert flipped_on and tr.active, "should start dancing after ~1s of music"
    assert beats >= 8, f"found {beats} beats"
    assert 100 <= tr.bpm <= 140, f"bpm {tr.bpm}"
    off = False
    for _ in range(int(4 / dt)):
        _, changed = tr.feed(np.zeros(blk, np.float32), t)
        off |= changed and not tr.active
        t += dt
    assert off and not tr.active, "should stop after silence"
    print("ok beat tracker")


if __name__ == "__main__":
    test_beat_tracker()
