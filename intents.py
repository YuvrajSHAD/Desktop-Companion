"""Voice commands: what you said -> which chore Moss should do.

Pure python (no heavy imports) so it is easy to test. Three chores:
    RECYCLE  "empty the recycle bin"
    NOTE     "take a note" ... (then say the note)   or   "take a note buy milk"
    NEXT/PREV "next song" / "previous song"          (Spotify, via the media keys)

Matching is deliberately strict: a command has to *sound like a command* (short, imperative,
nothing unknown in it), so ordinary chat like "what's the next song on that album?" or
"skip the intro" never fires a chore. Anything that merely *smells* like a command is handed to
the LLM as a fallback (see Brain.classify), which understands looser phrasing.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

RECYCLE, NOTE, NEXT, PREV = "recycle", "note", "next", "previous"
VOL_UP, VOL_DOWN, MUTE = "volume_up", "volume_down", "mute"
READ_NOTES, STATS, INTRO = "read_notes", "lazy_score", "intro"

# the JSON the LLM fallback fills in -> our kinds
ACTIONS = {
    "empty_recycle_bin": RECYCLE,
    "take_note": NOTE,
    "next_song": NEXT,
    "previous_song": PREV,
    "volume_up": VOL_UP,
    "volume_down": VOL_DOWN,
    "mute": MUTE,
    "read_notes": READ_NOTES,
    "lazy_score": STATS,
}
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["none", *ACTIONS]},
        "note": {"type": "string"},
        "amount": {"type": "string", "enum": ["small", "normal", "big"]},
    },
    "required": ["action"],
}
CLASSIFY_PROMPT = (
    "You route spoken commands for a desktop assistant. Decide whether the user is DIRECTLY ORDERING one of:\n"
    "- empty_recycle_bin: empty / clean / clear the recycle bin or trash\n"
    "- take_note: start a note. Put the note text in \"note\" only if they already said it in the same breath, else \"\"\n"
    "- next_song: skip to the next music track\n"
    "- previous_song: go back to the previous music track\n"
    "- volume_up / volume_down: make the sound louder / quieter. \"amount\" is small for \"a little\", big for \"a lot\", else normal\n"
    "- mute: mute or unmute the sound\n"
    "- read_notes: read back or summarise the notes they took today\n"
    "- lazy_score: tell them how many chores were done for them and how much time was saved\n"
    "If they are chatting, asking a question, or talking about something else (e.g. skipping a video intro), "
    "the action is \"none\". Reply with JSON only."
)


@dataclass(frozen=True)
class Intent:
    kind: str
    note: str = ""  # NOTE only: text said in the same breath as "take a note"
    amt: str = ""   # volume only: "small" | "" | "big"


# ---------------------------------------------------------------- helpers
_LEAD = re.compile(
    r"^\W*(?:(?:hey|ok|okay|yo|so|um|uh|and|then|alright)\W+)*"
    r"(?:(?:moss|moz|mos|mass)\b\W*)?"
    r"(?:(?:hey|ok|okay)\W+)*"
    r"(?:(?:please|can you|could you|would you|will you|can we|let['’]?s|i want you to|i need you to|go ahead and|just)\b\W*)*",
    re.I,
)
_TRAIL = re.compile(r"(?:\W+(?:please|for me|now|right now|moss|thanks|thank you))+\W*$", re.I)


def _strip(text: str) -> str:
    text = _LEAD.sub("", text.strip(), count=1)
    return _TRAIL.sub("", text).strip()


def _norm(text: str) -> str:
    t = text.lower().replace("'", "").replace("’", "")
    t = re.sub(r"\bre[\s-]+cycle", "recycle", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_QUESTION = {"what", "whats", "who", "whos", "which", "why", "how", "hows", "when", "where", "is", "are",
             "do", "does", "did", "was", "were", "should", "isnt", "arent"}

# ---------------------------------------------------------------- notes
_NOTE = re.compile(
    r"^(?:(?:take|make|write|jot|add|save|start|create|open)(?:\s+down)?\s+(?:me\s+)?(?:a\s+|an\s+|the\s+|new\s+)*"
    r"(?:quick\s+|short\s+|little\s+)?(?:note|notes|memo)\b"
    r"|note\s+to\s+self\b"
    r"|(?:write|jot|note)\s+(?:this|that|it)\s+down\b)"
    r"(?P<rest>.*)$",
    re.I | re.S,
)
_NOTE_JUNK = re.compile(
    r"^[\W_]*(?:(?:in|on|to|into|using|with)\s+(?:my\s+|the\s+)?(?:notepad|notes|note\s*pad)\b[\W_]*)?"
    r"(?:(?:for me|please|that says|which says|saying|says|that)\b[\W_]*)*",
    re.I,
)


def _note(text: str) -> Intent | None:
    m = _NOTE.match(text)
    if not m:
        return None
    rest = _NOTE_JUNK.sub("", m.group("rest"), count=1).strip()
    return Intent(NOTE, rest)


# ---------------------------------------------------------------- recycle bin
_BIN_VERBS = {"empty", "clean", "clear", "delete", "flush", "wipe", "purge", "dump", "erase", "tidy", "cleanup"}
_NEGATIVE = {"dont", "not", "never", "stop"}


def _recycle(words: list[str]) -> Intent | None:
    if not words or len(words) > 10 or words[0] not in _BIN_VERBS or _NEGATIVE & set(words):
        return None
    if any(w.startswith("recycl") for w in words) or "trash" in words:
        return Intent(RECYCLE)
    return None


# ---------------------------------------------------------------- media
_MEDIA_NOUN = {"song", "songs", "track", "tracks", "tune", "music", "spotify", "one"}
_FILLER = {"this", "the", "that", "current", "a", "to", "on", "song", "songs", "track", "tracks", "tune",
           "music", "spotify", "one", "it", "play", "go", "switch", "change", "put", "give", "me", "move",
           "for", "my", "another", "different", "in"}
_NEXT_WORDS = {"next", "skip"}
_NEXT_SOFT = {"change", "switch", "another", "different"}  # "change the song" (needs a noun)
_PREV_WORDS = {"previous", "prev", "last", "back", "before"}


def _media(words: list[str]) -> Intent | None:
    if not words or len(words) > 9:
        return None
    ws = set(words)
    nouns = bool(_MEDIA_NOUN & ws)
    nxt = bool(_NEXT_WORDS & ws) or (bool(_NEXT_SOFT & ws) and nouns)
    prv = bool(_PREV_WORDS & ws)
    if nxt == prv:  # neither, or contradictory
        return None
    allowed = _FILLER | _NEXT_WORDS | _PREV_WORDS  # anything else ("skip the INTRO") is not for us
    if not ws <= allowed:
        return None
    if prv:
        # "back"/"last"/"before" are too common on their own: need a noun or the phrase "go back"
        if not (nouns or words[0] in {"previous", "prev"} or " ".join(words).startswith("go back")):
            return None
        return Intent(PREV)
    return Intent(NEXT)



# ---------------------------------------------------------------- volume / mute
_UP = {"up", "increase", "raise", "louder", "higher", "boost"}
_DOWN = {"down", "decrease", "lower", "reduce", "quieter", "softer"}
_VOL_NOUN = {"volume", "sound", "audio", "louder", "quieter", "softer", "it", "music", "song", "speakers"}
_VOL_FILL = {"turn", "make", "set", "put", "the", "a", "bit", "little", "lot", "slightly", "way", "tad", "notch",
             "please", "can", "you", "my", "some", "just", "by", "to", "more", "even", "spotify", "all", "and"}
_SMALL = {"bit", "little", "slightly", "tad", "notch"}
_BIG = {"lot", "way", "max"}
_MUTE_FILL = {"the", "sound", "volume", "audio", "speakers", "please", "everything", "it", "music", "my"}


def _volume(words: list[str]) -> Intent | None:
    if not words or len(words) > 8:
        return None
    ws = set(words)
    up, down = bool(_UP & ws), bool(_DOWN & ws)
    if up == down or not (_VOL_NOUN & ws):
        return None
    if not ws <= (_UP | _DOWN | _VOL_NOUN | _VOL_FILL):  # anything else is not for us
        return None
    amt = "small" if _SMALL & ws else "big" if _BIG & ws else ""
    return Intent(VOL_UP if up else VOL_DOWN, "", amt)


def _mute(words: list[str]) -> Intent | None:
    ws = set(words)
    if words and len(words) <= 5 and ws & {"mute", "unmute"} and ws <= (_MUTE_FILL | {"mute", "unmute"}):
        return Intent(MUTE, "", "un" if "unmute" in ws else "")
    return None


# ---------------------------------------------------------------- notes read-back, lazy score, intro
_NOTE_W = {"note", "notes", "noted"}
_READ_V = {"read", "summarize", "summarise", "recap", "review", "show", "tell", "give"}


def _read_notes(n: str, words: list[str]) -> Intent | None:
    if not words or len(words) > 14:
        return None
    ws = set(words)
    if words[0] in _READ_V and ws & _NOTE_W and ("my" in ws or "the" in ws or "todays" in ws):
        return Intent(READ_NOTES)
    asks = ("did i", "have i", "in my notes", "in my note", "i noted", "do i have any note", "any notes")
    if words[0] in {"what", "whats", "do", "any"} and any(p in n for p in asks) and (ws & _NOTE_W):
        return Intent(READ_NOTES)
    if words[0] == "what" and {"write", "wrote", "jot", "jotted"} & ws and "down" in ws and "today" in ws:
        return Intent(READ_NOTES)
    return None


_STATS_P = ("lazy score", "laziness score", "how lazy", "how many chores", "chores today", "chores have you done",
            "what have you done for me", "what did you do for me", "how much time did you save",
            "time have you saved", "time have i saved", "time saved")


def _stats(n: str, words: list[str]) -> Intent | None:
    if words and len(words) <= 12 and any(p in n for p in _STATS_P):
        return Intent(STATS)
    return None


_INTRO_P = ("introduce yourself", "introduce your self", "start the demo", "demo time", "give us your intro",
            "say hello to everyone", "say hi to everyone", "say hello to the", "say hi to the")


def _intro(n: str, words: list[str]) -> Intent | None:
    if words and len(words) <= 10 and (any(p in n for p in _INTRO_P) or n in {"intro", "your intro", "do your intro"}):
        return Intent(INTRO)
    return None

# ---------------------------------------------------------------- public API
def parse(text: str) -> Intent | None:
    """Strict, instant matcher. Returns None for anything that isn't clearly a command."""
    t = _strip(text)
    if not t:
        return None
    hit = _note(t)
    if hit:
        return hit
    n = _norm(t)
    words = n.split()
    hit = _intro(n, words) or _stats(n, words) or _read_notes(n, words)  # these are phrased as questions too
    if hit:
        return hit
    if not words or words[0] in _QUESTION:
        return None
    return _recycle(words) or _media(words) or _volume(words) or _mute(words)


_HINT = re.compile(r"recycl|\btrash\b|\bnotes?\b|\bnotepad\b|\bjot|\bskip|\bnext\b|\bprevious\b|\bsongs?\b|\btrack\b|\bspotify\b"
                   r"|\bvolume\b|\blouder\b|\bquieter\b|\bsofter\b|\bmute\b|\bturn\b.*\b(?:up|down)\b|\blazy\b|\bchores?\b|\bscore\b", re.I)


def maybe_command(text: str) -> bool:
    """True if the (short) utterance mentions something we do. Used to decide whether to ask the LLM."""
    t = _strip(text)
    words = _norm(t).split()
    return bool(words) and len(words) <= 16 and words[0] not in _QUESTION and bool(_HINT.search(t))


def from_action(data) -> Intent | None:
    """Turn the LLM fallback's JSON ({"action": ..., "note": ...}) into an Intent."""
    if not isinstance(data, dict):
        return None
    kind = ACTIONS.get(str(data.get("action", "")).strip())
    if not kind:
        return None
    if kind in (VOL_UP, VOL_DOWN):
        amount = str(data.get("amount") or "")
        return Intent(kind, "", "" if amount == "normal" else amount if amount in ("small", "big") else "")
    return Intent(kind, str(data.get("note") or "").strip() if kind == NOTE else "")


# ---------------------------------------------------------------- answers to Moss's questions
_YES = {"yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "affirmative", "absolutely", "definitely",
        "okay", "ok", "please"}
_NO = {"no", "nope", "nah", "dont", "not", "cancel", "stop", "wait", "never", "negative"}


def is_yes(text: str) -> bool:
    n = _norm(text)
    ws = set(n.split())
    if ws & _NO:
        return False
    return bool(ws & _YES) or any(p in n for p in ("do it", "go ahead", "empty it", "go for it"))


def is_cancel(text: str) -> bool:
    n = _norm(text)
    return any(p in n for p in ("never mind", "nevermind", "cancel", "forget it", "scratch that", "scrap that"))


def human_size(n: int) -> str:
    """Spoken-friendly size: 'about 1.2 gigabytes' reads better aloud than 'GB'."""
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} gigabytes"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.0f} megabytes"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} kilobytes"
    return f"{n} bytes"
