"""Brain: local LLM via Ollama, streamed out as speakable sentences."""
from __future__ import annotations
import sys

import json

import intents
from persona import system_prompt
from textutil import pop_sentence, split_emotion


class Brain:
    def __init__(self, cfg):
        import ollama  # imported here so textutil/persona stay testable without it

        self.cfg = cfg
        self.client = ollama.Client(host=cfg.ollama_host)
        self.system = system_prompt(cfg)
        self.history: list[dict] = []
        self.options = {
            "num_ctx": cfg.llm_num_ctx,
            "num_predict": cfg.llm_max_tokens,
            "temperature": cfg.llm_temperature,
            "top_p": 0.8,
            "top_k": 20,
        }

    def check(self):
        try:
            names = [m.model for m in self.client.list().models]
        except Exception:
            sys.exit(f"Can't reach Ollama at {self.cfg.ollama_host}. Start the Ollama app/service first.")
        m = self.cfg.llm_model
        if m not in names and f"{m}:latest" not in names:
            sys.exit(f"Model '{m}' isn't pulled yet. Run:  ollama pull {m}")

    def warmup(self):
        self.client.chat(
            model=self.cfg.llm_model,
            messages=[{"role": "user", "content": "hi"}],
            think=False, keep_alive=self.cfg.llm_keep_alive,
            options={**self.options, "num_predict": 1},
        )

    def reset(self):
        self.history.clear()

    def _trim(self):
        self.history = self.history[-self.cfg.history_turns * 2:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

    def remember(self, user_text: str, reply: str):
        """Record an exchange that didn't go through the LLM (a chore), so Moss remembers doing it."""
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}]
        self._trim()

    def classify(self, text: str):
        """Fallback for phrasing the strict matcher missed: ask Gemma for a JSON verdict. None on any doubt."""
        try:
            r = self.client.chat(
                model=self.cfg.llm_model, think=False, keep_alive=self.cfg.llm_keep_alive,
                messages=[{"role": "system", "content": intents.CLASSIFY_PROMPT}, {"role": "user", "content": text}],
                format=intents.CLASSIFY_SCHEMA,
                # same num_ctx as chat, otherwise Ollama reloads the model between calls
                options={**self.options, "temperature": 0, "num_predict": 80},
            )
            return intents.from_action(json.loads(r.message.content))
        except Exception as e:
            print(f"[brain] intent check failed: {e}", flush=True)
            return None

    def summarize_notes(self, notes: list[str]) -> str:
        """Gemma turns today's notes into one or two spoken sentences."""
        numbered = "\n".join(f"{i}. {n}" for i, n in enumerate(notes[-30:], 1))
        r = self.client.chat(
            model=self.cfg.llm_model, think=False, keep_alive=self.cfg.llm_keep_alive,
            messages=[{"role": "system", "content": (
                "You summarise a person's notes from today so they can be read aloud. Reply with at most two short "
                "spoken sentences in plain text: no lists, markdown, emojis or tags. Mention every distinct item "
                "and never invent anything that is not in the notes.")},
                {"role": "user", "content": numbered}],
            options={**self.options, "temperature": 0.2, "num_predict": 120},
        )
        return split_emotion(r.message.content or "")[1]

    def reply_stream(self, user_text: str):
        """Generator of sentences. Closing it early (interruption) keeps only what was said."""
        self.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self.system}] + self.history
        spoken: list[str] = []
        buf, first = "", True
        try:
            stream = self.client.chat(
                model=self.cfg.llm_model, messages=messages, stream=True, think=False,
                keep_alive=self.cfg.llm_keep_alive, options=self.options,
            )
            for chunk in stream:
                tok = chunk.message.content or ""
                if not tok:
                    continue
                buf += tok.replace("\n", " ")
                while True:
                    sentence, buf = pop_sentence(buf, first)
                    if sentence is None:
                        break
                    first = False
                    spoken.append(sentence)
                    yield sentence
            tail = buf.strip()
            if tail:
                spoken.append(tail)
                yield tail
        finally:
            if spoken:
                self.history.append({"role": "assistant", "content": " ".join(spoken)})
            else:
                self.history.pop()  # keep user/assistant alternation intact
            self._trim()
