---
title: "Moss: a voice-first desktop sloth that rewards you for being lazy"
published: false
tags: devchallenge, ai, gemma, productivity
---
<!-- Fill every [BRACKET]. Check the challenge page for its required headings and paste them in if they differ. -->

*This is a submission for [CHALLENGE NAME / WEEK].*

## What I Built
Moss is a small 3D sloth who lives on my taskbar and does my boring chores when I ask out loud. Slow and steady is her whole philosophy: she does the little things so I can stay lazy, and she keeps score.

What she does (all by voice, all on my own PC):
- **Empties the recycle bin**, but tells me how many items and how much space first and only does it after I say yes, because it's permanent.
- **Takes notes** into a text file, and **reads them back**: "What did I note today?" Gemma summarises today's notes and Moss says it.
- **Skips songs** (next / previous on Spotify) and **changes the volume** (up, down, a little, a lot, mute).
- **Lazy score**: she keeps a tally and an estimate of the time saved, and brags: "That's [N] chores and about [M] minutes today. I'm proud of us."
- She sits on my windows, follows my cursor with her eyes, naps when I'm quiet, and dances when music plays.

## Demo
[VIDEO EMBED: {% embed https://... %}]

[1-2 screenshots]

## Code
[GitHub repo link]

## How I Built It
- **Ears:** Whisper large-v3-turbo. **Mouth:** Kokoro-82M (Japanese girl voice speaking English). **Brain:** [MODEL, e.g. Gemma 4 e4b] through Ollama. Nothing leaves the machine.
- **Body:** Electron + three.js + three-vrm, a transparent always-on-top window that is click-through everywhere except the character.
- **Two-step understanding (where Gemma earns its place):** a strict matcher handles clear commands instantly. Anything that only *sounds* like a command ("flip to the following song") goes to Gemma, which must answer with a JSON verdict (Ollama structured output). Ordinary chat like "skip the intro" is never treated as a command.
- **Safety by design:** the recycle bin always asks first; media keys only fire while Spotify is running, so she can't skip my YouTube; the body link is localhost-only with a random token.

### Measured accuracy
I wrote a script that runs [N] phrasings of each command, plus [N] ordinary sentences that must *not* trigger anything.

[PASTE THE TABLE FROM ACCURACY.md AFTER `python eval_accuracy.py --gemma`]

What the numbers say: [1-2 sentences, e.g. what Gemma fixed and what it still misses. Quote the sample misses honestly.]
The time-saved figure is an estimate of how long each chore takes by hand, not a stopwatch measurement.

## What I Learned
- [e.g. a deterministic matcher first, an LLM only for the fuzzy rest, is faster and safer than letting the LLM decide everything]
- [e.g. something that surprised you building the body / voice]

## What's Next
- [1-2 honest items]

<!-- Team: [solo, @your-dev-username]. Prize categories: [if the challenge has them, say which and why]. -->
