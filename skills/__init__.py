"""A tiny skill framework: spoken command -> real action, decided BEFORE the LLM sees the text.

Why not an LLM tool-call / MCP layer for this?  For "next song" and "take a note" a regex fast-path is
instant (no extra model round-trip), never hallucinates a tool call, and works with a small local model.
The Skill shape below (name / description / handle) is deliberately MCP-tool-shaped, so a skill can later
be exposed over MCP or Ollama tool-calling without rewriting it.

Adding a skill = subclass Skill, implement handle(), register it in build_router().
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Result:
    say: str = ""     # what Moss says back out loud ("" = stay quiet)
    toast: str = ""   # optional short text for the speech bubble (shown without speaking)


class Skill:
    name = "skill"
    description = ""
    active = False  # a skill with an open session (e.g. note-taking) sees every utterance first

    def handle(self, text: str, body: str) -> Result | None:
        """text = lowercase, no punctuation, wake word removed.  body = same but original case/punctuation."""
        raise NotImplementedError

    def handle_active(self, text: str, body: str) -> Result | None:
        return None

    def close(self) -> None:
        pass


# Whisper often mishears the name, so a greeting + a near-miss is accepted ("hey mass", "ok mos").
_GREET = r"(?:hey|hi|hello|ok|okay|yo)"
_NEAR = r"(?:moss|mos|mass|moth|boss|morse|mauss|moss's)"


def strip_wake(raw: str, name: str = "moss") -> str:
    """'Hey Moss, take a note.' -> 'take a note.'  Also drops a trailing ', moss'."""
    s = raw.strip()
    s = re.sub(rf"^\W*(?:{_GREET}\W+{_NEAR}|{re.escape(name)})\b\W*", "", s, flags=re.I)
    s = re.sub(rf"[,\s]+{re.escape(name)}\W*$", "", s, flags=re.I)
    return s.strip()


def normalize(body: str) -> str:
    t = body.lower().replace("’", "'")
    t = re.sub(r"[^\w\s']", " ", t)
    t = re.sub(r"\b(please|kindly)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class Router:
    def __init__(self, name: str = "moss"):
        self.name = name
        self.skills: list[Skill] = []

    def add(self, skill: Skill) -> "Router":
        self.skills.append(skill)
        return self

    def route(self, raw: str) -> Result | None:
        body = strip_wake(raw, self.name)
        text = normalize(body)
        if not text:
            return None
        for s in self.skills:
            if s.active:
                try:
                    r = s.handle_active(text, body)
                except Exception as e:
                    print(f"[skill:{s.name}] {e}")
                    r = Result("[sad] Sorry, I lost my pen for a second.")
                if r:
                    return r
        for s in self.skills:
            try:
                r = s.handle(text, body)
            except Exception as e:
                print(f"[skill:{s.name}] {e}")
                r = Result("[sad] Something went wrong with that one.")
            if r:
                return r
        return None

    def close(self) -> None:
        for s in self.skills:
            try:
                s.close()
            except Exception:
                pass


def build_router(cfg, media=None) -> Router:
    from .media import MediaSkill
    from .notes import NotesSkill

    r = Router(cfg.name)
    r.add(NotesSkill(cfg))  # first: an open note session must swallow everything, even "next song"
    if media is not None:
        r.add(MediaSkill(media))
    return r
