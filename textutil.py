"""Pure-python text helpers (no heavy imports, easy to test)."""
import re

_ABBR = {"mr", "mrs", "ms", "dr", "vs", "st", "sr", "jr", "etc", "e.g", "i.e", "prof"}
_END = re.compile(r"([.!?…]+[\"')\]]*)\s+")
_CLAUSE = re.compile(r"[,;:—–]\s+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")
_TAG = re.compile(r"\[\s*([A-Za-z]{3,12})\s*\]")
EMOTIONS = {"neutral", "happy", "sad", "angry", "surprised", "relaxed", "sleepy"}


def pop_sentence(buf: str, first: bool):
    """Return (sentence, rest) or (None, buf) if no complete sentence yet.

    A sentence only ends when punctuation is followed by whitespace, so we never
    cut "3.14" or a half-streamed token. When `first` is True we also allow an
    early split at a comma/colon so the voice starts talking sooner.
    """
    for m in _END.finditer(buf):
        punct = m.group(1)
        words = buf[: m.start(1)].split()
        last = words[-1].lower().strip("\"'(") if words else ""
        if punct == "." and (last in _ABBR or last.isdigit()):
            continue
        return buf[: m.end(1)].strip(), buf[m.end():]
    if first:
        for m in _CLAUSE.finditer(buf):
            if m.start() >= 40:
                return buf[: m.start() + 1].strip(), buf[m.end():]
    return None, buf


def split_emotion(text: str):
    """'[happy] Hi there.' -> ('happy', 'Hi there.'). Unknown [tags] are left for clean_for_tts to drop."""
    found = []

    def repl(m):
        w = m.group(1).lower()
        if w in EMOTIONS:
            found.append(w)
            return " "
        return m.group(0)

    out = _TAG.sub(repl, text)
    return (found[0] if found else None), out.strip()


def clean_for_tts(text: str) -> str:
    """Strip things a voice engine would read out loud as noise."""
    text = re.sub(r"\[[^\]]{1,20}\]", " ", text)  # any leftover [tag]
    text = re.sub(r"\*[^*]{1,60}\*", " ", text)      # *giggles*
    text = re.sub(r"\([^)]{1,40}\)", " ", text) if re.search(r"\((sigh|laugh|yawn|smile)", text, re.I) else text
    text = text.replace("*", " ")
    text = re.sub(r"[`#_>~|]", " ", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if re.search(r"[A-Za-z0-9]", text) else ""
