"""Measured accuracy of Moss's command understanding.

    python eval_accuracy.py             # strict matcher only (instant, needs nothing)
    python eval_accuracy.py --gemma     # also the Gemma fallback (needs Ollama running)

For every command it makes 60 different ways of saying it (clear commands AND loose paraphrases, with polite
prefixes/suffixes), runs them through the SAME path main.py uses (strict matcher -> if it does not match and the
phrase looks like a command, ask Gemma) and counts the right answers. It also runs 60 ordinary sentences
(including near-misses like "skip the intro") to count FALSE triggers. The sample is seeded, so a rerun gives the
same phrases. Writes ACCURACY.md.
"""
from __future__ import annotations
import argparse
import itertools
import random

import intents as I

# core phrasings per command: the first group is clear/imperative, the second is loose paraphrase
CORES = {
    "recycle": ["empty the recycle bin", "empty the recycling bin", "clear the trash", "clean the recycle bin", "empty the trash",
                "wipe the recycle bin", "flush the trash", "delete everything in the recycle bin",
                "the recycle bin is overflowing, deal with it", "get rid of what is in the trash", "I need the recycle bin cleaned out",
                "take out the trash on my computer", "my recycle bin is full, sort it", "tidy up the recycle bin"],
    "note": ["take a note", "make a note", "write this down", "note to self", "take a note buy milk", "jot down a note", "start a new note",
             "open a new note", "I want to jot something down", "write something down for me", "put a note in my notepad",
             "save a quick note", "I have a note for you", "jot this down real quick"],
    "next": ["next song", "skip this song", "skip", "play the next song", "next track", "skip the song on spotify", "change the song",
             "flip to the following song", "I don't like this one, go to the next track", "move on to another song",
             "this song is boring, skip it", "go forward one track", "let's hear something else, next one", "jump to the next tune"],
    "previous": ["previous song", "go back to the previous song", "play the last song", "go back", "previous track", "prev song",
                 "go back one song", "play the song before this one", "I want the earlier song again", "take me back to the last track",
                 "rewind to the previous tune", "go to the song from before", "bring back the last song", "put the last track on again"],
    "volume_up": ["volume up", "turn it up", "make it louder", "turn the volume up", "raise the volume", "louder", "increase the volume",
                  "a little louder", "turn the music up a bit", "I can't hear it, make it louder", "the sound is too quiet, raise it",
                  "boost the volume", "bring the volume up", "crank the sound up"],
    "volume_down": ["volume down", "turn it down", "make it quieter", "turn the volume down", "lower the volume", "quieter", "decrease the volume",
                    "a little softer", "turn the music down a bit", "it's too loud, make it quieter", "the sound is too loud, lower it",
                    "reduce the volume", "bring the volume down", "bring the sound down a notch"],
    "mute": ["mute", "unmute", "mute the sound", "mute the volume", "unmute the music", "mute everything", "please mute it",
             "silence the speakers, mute them", "I need it muted", "mute the audio", "mute the sound for a second",
             "turn the sound off, mute", "unmute the speakers", "mute my music"],
    "read_notes": ["what did I note today", "read my notes", "summarize my notes", "what's in my notes", "read back my notes",
                   "what notes did I take today", "recap my notes", "tell me my notes from today", "read me what I wrote down today",
                   "do I have any notes today", "go over my notes for today", "what did I jot down today", "review my notes", "give me my notes"],
    "lazy_score": ["lazy score", "what's my lazy score", "how lazy was I today", "how many chores did you do", "what have you done for me today",
                   "how much time did you save me", "give me my lazy score", "show me the lazy score", "how many chores have you done",
                   "tell me my laziness score", "what did you do for me", "how much time have you saved me today",
                   "so how lazy have I been", "chores today?"],
}
PRE = ["", "", "Moss, ", "hey Moss ", "okay ", "can you ", "could you please ", "Moss can you ", "um ", "yo "]
POST = ["", "", "", " please", " for me", " now", " Moss", " thanks"]
NEGATIVE = [
    "what's the next song on that album", "skip the intro", "I emptied the recycle bin yesterday", "don't empty the recycle bin",
    "how do I empty the recycle bin", "I was going to take a note about it", "what was the last song you played", "tell me a joke",
    "I'll go back to work", "play some music", "the next time I see you", "what's the volume of a sphere", "I turned the volume up yesterday",
    "don't mute me", "what is a note in music", "how are you today", "what did I eat today", "pick it up", "look it up for me",
    "I need to take a break", "the sound of the rain is nice", "my score in the game was bad", "tell me about sloths", "who are you",
    "what time is it", "I'm so lazy today", "that was a great song", "the bin collection is on Tuesday", "I lost my notes",
    "can you recommend a song", "turn left at the corner", "skip dinner tonight", "what's the weather like", "I hate the next meeting",
    "go to sleep", "what does mute mean", "why is the music so loud in this cafe", "my recycling day is Monday", "back in a minute",
    "write me a poem", "read me a story", "how many songs are on this playlist", "I took a lot of notes in class", "remember to call mom tomorrow",
    "the previous owner left a note", "how loud is a jet engine", "turn on the lights", "what's the lowest price", "is this song any good",
    "please be quiet for a moment", "how do I summarize a book", "what's a good score in golf", "do you like chores", "next week I'm free",
    "what did you think of the movie", "I want a new laptop", "open the window", "clean my room later", "it's getting late", "thanks, that's all",
]


def phrases(cmd: str, n: int = 60, seed: int = 7) -> list[str]:
    combos = [f"{a}{c}{b}" for c in CORES[cmd] for a, b in itertools.product(PRE, POST)]
    combos = sorted(set(combos))
    return random.Random(f"{seed}-{cmd}").sample(combos, min(n, len(combos)))


def strict(text: str):
    it = I.parse(text)
    return it.kind if it else None


def full(text: str, brain):
    it = I.parse(text)
    if it is None and brain is not None and I.maybe_command(text):
        it = brain.classify(text)
    return it.kind if it else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemma", action="store_true", help="also run the Gemma fallback (needs Ollama)")
    ap.add_argument("-n", type=int, default=60, help="phrasings per command")
    args = ap.parse_args()
    brain = None
    if args.gemma:
        from brain import Brain
        from config import CFG
        brain = Brain(CFG)
        brain.check()
        brain.warmup()
        print(f"Gemma fallback: {CFG.llm_model}")
    rows, tot, ok_s, ok_f = [], 0, 0, 0
    misses = []
    for cmd in CORES:
        ps = phrases(cmd, args.n)
        s = sum(strict(p) == cmd for p in ps)
        f = sum(full(p, brain) == cmd for p in ps) if brain else None
        misses += [(cmd, p) for p in ps if (full(p, brain) if brain else strict(p)) != cmd][:4]
        rows.append((cmd, len(ps), s, f))
        tot += len(ps); ok_s += s; ok_f += f or 0
        print(f"{cmd:12s} strict {s}/{len(ps)}" + (f"   +Gemma {f}/{len(ps)}" if brain else ""), flush=True)
    neg_s = sum(strict(p) is not None for p in NEGATIVE)
    neg_f = sum(full(p, brain) is not None for p in NEGATIVE) if brain else None
    pct = lambda a, b: f"{100 * a / b:.0f}%"
    out = ["| Command | Phrasings | Strict matcher | Strict + Gemma fallback |", "|---|---|---|---|"]
    for cmd, n, s, f in rows:
        out.append(f"| {cmd} | {n} | {pct(s, n)} | {pct(f, n) if f is not None else 'not run'} |")
    out.append(f"| **All commands** | {tot} | **{pct(ok_s, tot)}** | " + (f"**{pct(ok_f, tot)}**" if brain else "not run") + " |")
    out.append(f"| False triggers on {len(NEGATIVE)} ordinary sentences | {len(NEGATIVE)} | {neg_s} | " + (str(neg_f) if brain else "not run") + " |")
    table = "\n".join(out)
    print("\n" + table)
    with open("ACCURACY.md", "w", encoding="utf-8") as fh:
        fh.write("# Moss command accuracy (measured)\n\n"
                 f"{args.n} seeded phrasings per command (clear commands and loose paraphrases), plus {len(NEGATIVE)} ordinary sentences that must NOT trigger anything.\n\n"
                 + table + "\n\nSample misses (first few per command):\n\n" + "\n".join(f"- {c}: \"{p}\"" for c, p in misses) + "\n")
    print("\nwrote ACCURACY.md")


if __name__ == "__main__":
    main()
