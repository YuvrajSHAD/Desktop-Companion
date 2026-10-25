# 🦥 Moss: a voice-first desktop sloth who does your chores

Moss is a tiny 3D sloth who lives on your taskbar. Talk to her, and she does your boring little chores:
empties the recycle bin, takes notes, skips songs, changes the volume, and keeps a **lazy score** of how much
time she saved you.

Why build a little workflow for every tedious task when you can just *talk to a sloth*?

Everything runs **locally on your own PC**. No cloud, no API keys, no accounts.

> Built for the Hacktoberfest Open-Source AI Challenge, Week 3: *Slow and Steady*.

**Character:** the 3D model is "Zainab-Chan" by mimenn_ ([VRoid Hub](https://hub.vroid.com/en/characters/542563936448829639/models/1717281170322434139)), used with credit. It is not my work and it is not included in this repo, see [Add a character](#add-a-character) and [Credits](#credits).

**Demo:** the video is in my DEV submission post for the challenge.

---

## What she can do

Just say these out loud (saying "Moss" first is optional):

| You say | What happens |
|---|---|
| "Empty the recycle bin" | Tells you how many items and how much space, asks you to say **yes** (it's permanent), then empties it silently. Say no, or nothing, and she leaves it alone. An already-empty bin is never touched. |
| "Take a note" / "Take a note buy milk" | Appends `[date time] your note` to a notes file and opens it in Notepad. Pauses while dictating are fine, and "never mind" scraps it. |
| "What did I note today?" / "Read my notes" | Reads today's notes, Gemma summarises them in a sentence or two, and Moss says it back. |
| "Next song" / "Previous song" | Presses the media keys, so it works with Spotify in the background. Only while `Spotify.exe` is running, so she can't skip your YouTube by accident. |
| "Volume up" / "Turn it down" / "A little quieter" / "A lot louder" / "Mute" | Presses the system volume keys. |
| "Lazy score" / "How lazy was I today?" | She tells you how many chores she did today and about how many minutes that saved. She also brags after every 5th chore and when you say goodbye. |
| "Introduce yourself" / "Start the demo" | A scripted intro for demo recordings. |
| Anything else | Normal chat with her sloth personality, powered by a local LLM. |

Plus the pet stuff:

- Stands or sits on your taskbar and the top edge of your windows, rides them when you drag them, and falls when they close.
- Eyes and head follow your cursor (and she looks at **you** while she talks).
- Drag her, pat her head, poke her. She naps when you've been quiet for a while.
- **Dances to your music** (beat detection from your speakers, never your mic) and jumps between windows now and then.
- Lip-sync from the real voice audio, mood faces from the LLM, and subtitles in a speech bubble.
- **Interrupt her mid-sentence**: talk over her and she stops and listens.

### Lazy score, honestly
The time saved is an **estimate** of how long each chore takes by hand (about 45 s for the recycle bin, 30 s
for a note, 10 s for a song skip, 8 s for volume). It's a tally with a sense of humour, not a stopwatch.
The numbers are in `stats.py` if you want to change them.

### How she understands you
Letting an LLM decide everything would be slow and a bit scary. So there are two steps:

1. A **strict matcher** handles clear commands instantly ("next song", "empty the recycle bin").
2. Anything that only *sounds* like a command ("flip to the following song") is checked by **Gemma**, which must
   answer with a JSON verdict (Ollama structured output). Ordinary chat like "skip the intro" or "what's the next
   song on that album?" is never treated as a command.

You can turn the Gemma check off with `llm_intent_fallback = False` in `config.py`.

### Measured accuracy
`python eval_accuracy.py --gemma` runs 60 different phrasings of each of 9 commands (540 total), plus 60 normal
sentences that must *not* trigger anything. My results on my machine (Gemma 4 e4b):

| Command | Strict matcher | Strict + Gemma |
|---|---|---|
| recycle bin | 57% | 98% |
| take a note | 67% | 92% |
| next song | 57% | 98% |
| previous song | 58% | 100% |
| volume up | 70% | 85% |
| volume down | 68% | 83% |
| mute | 72% | 87% |
| read my notes | 85% | 93% |
| lazy score | 92% | 92% |
| **All commands (540)** | **69%** | **92%** |
| False triggers on 60 normal sentences | 0 | 1 |

Honest weak spots: volume and mute are the weakest, and Gemma let one normal sentence through as a command.
Run the script yourself; your numbers will depend on your model.

---

## How it works

```
 mic ──> Whisper large-v3-turbo ──> strict matcher ──> chore ──┐
                                        │ (not sure)           │
                                        v                      v
                                  Gemma (JSON verdict)     Kokoro voice ──> speakers
                                        │ (just chatting)      ^
                                        └──> Gemma chat ───────┘
                                                                │ audio level, mood, subtitles
                              Electron + three.js body <────────┘ (localhost WebSocket)
```

| Part | What | Notes |
|---|---|---|
| Ears | Whisper large-v3-turbo (transformers, CUDA) | |
| Brain | Gemma 4 e4b via [Ollama](https://ollama.com) | Chat, command fallback, note summaries |
| Mouth | Kokoro-82M | Default voice `jf_alpha` (a Japanese girl voice speaking English) |
| Body | Electron + three.js + three-vrm | Transparent, always-on-top, click-through everywhere except the character |

**Security:** the link between her brain and body is localhost-only and needs a random token from `.bridge_token`
(a web page can't read it), so websites can't listen to your conversation. Only window geometry is read, never
window titles or contents. Chores that change things ask first or only run in safe conditions (see above).

---

## Setup (Windows)

### You need
- **Windows 10/11.** The chores and the body are Windows-only. The voice + brain run elsewhere with `--no-body`, but chores need Windows.
- **An NVIDIA GPU** with a recent driver. It was built on an RTX 4090 laptop (16 GB VRAM). Other GPUs may work; CPU-only is blocked by default (`allow_cpu` in `config.py`).
- **Python 3.11 or 3.12** and **Node.js 20+**.
- **[Ollama](https://ollama.com)** installed and running.
- A microphone. Headphones are best (see *Interrupting her*).

### Steps
```bat
git clone https://github.com/YuvrajSHAD/Desktop-Companion
cd Desktop-Companion

:: 1. Python environment
python -m venv venv
venv\Scripts\activate
pip uninstall -y torch torchaudio torchvision
pip install -r requirements.txt

:: 2. The body (downloads Electron and builds the renderer)
cd body
npm install
cd ..

:: 3. The brain
ollama pull gemma4:e4b
```

> `requirements.txt` pins CUDA 13 PyTorch (`torch==2.14.1+cu130`) so pip can't silently pick the CPU build.
> If your driver doesn't support CUDA 13, change the index URL and version in that file to match your setup.

The first run downloads Whisper and Kokoro models, so be patient.

### Add a character
Moss needs a `.vrm` file in `models/` (VRM 0.x or 1.0). If several are present, `character.vrm` wins.

**The character is not included in this repo.** The one in my demo is **"Zainab-Chan" by mimenn_** (VRoid Hub, VRM 1.0).
Its license requires credit and does not allow redistribution, so please download it yourself:

1. Open https://hub.vroid.com/en/characters/542563936448829639/models/1717281170322434139
2. Download the VRM file (VRoid Hub may ask you to log in and accept the usage terms).
3. Save it as `models\character.vrm`.

You can also use any other character:
- Make your own with **VRoid Studio** (free, exports VRM), or find models on VRoid Hub or Booth.
- **Always check a model's own license** (commercial use, credit, redistribution) before using or sharing it.
- `models/*.vrm` is in `.gitignore` so a downloaded model never ends up in a commit by accident.

### Run
```bat
python main.py
```
- `python main.py --text` type instead of talk (handy for debugging)
- `python main.py --no-body` voice + brain only
- `python main.py --intro` start with the full introduction (for demos)

Say **"goodbye"** to quit and **"reset"** to wipe her chat memory. Right-click Moss (or use the tray icon) for:
sit / nap / wake, jump to another window, dance now, size (normal / chibi / big screen), drop from the top, hide, quit.

After changing anything in `body/src`, run `cd body && npm run build` once (the renderer is bundled).

---

## Settings you'll actually want

All in `config.py` unless noted.

| Setting | What it does |
|---|---|
| `user_name` | What she calls you |
| `llm_model` | Ollama model (try `qwen3.5:4b` if you want it snappier) |
| `tts_voice`, `tts_pitch`, `tts_speed` | Her voice. Audition options with `python voice_test.py` |
| `notes_path` | Where `Moss Notes.txt` lives |
| `notes_open` | Open Notepad on the `first` note of a session, `always`, or `never` |
| `lazy_brag_every` | Brag after every Nth chore (`0` = only when asked) |
| `volume_presses` | Volume key presses per request (about 2% each) |
| `llm_intent_fallback` | Let Gemma catch looser phrasing |
| `intro_on_start` | Give the full intro every start |
| `music_threshold` | Raise it if she dances to background noise, lower it if she ignores quiet music |
| `barge_in`, `barge_margin`, `barge_rms`, `barge_ms` | Interrupting her (below) |
| `min_rms` | Raise if background noise triggers the mic |
| `body/config.json` | Size, headroom, nap timer, walk speed |

### Interrupting her
Talk over her for about 0.4 s and she stops and listens. Her own voice leaks into your mic on speakers, so she
measures how loud it is and only counts you when you're clearly louder (the first sentence after start-up is used
for that measurement). If she cuts herself off, raise `barge_margin`; if she ignores you, lower it. Headphones
make it most reliable.

### Troubleshooting
- **"This torch build can't see the GPU"**: you have the CPU wheel. Run the `pip uninstall` / `pip install -r requirements.txt` steps again.
- **"Can't reach Ollama"**: start the Ollama app, and check `ollama list` shows `gemma4:e4b`.
- **No body appears**: run `npm install` in `body/`, and check there's a `.vrm` in `models/`.
- **She won't skip songs**: Spotify must be running (`media_require_spotify`).
- **Port in use**: another Moss is still running (`bridge_port`).
- **Check the Windows parts alone**: `python winops.py` (read-only), `python winops.py --next`, `python winops.py --volume`.

### Tests
```bat
python tests_skills.py        :: parser, chores, lazy score, notes (no GPU or Windows needed)
python tests_py.py
node body/test/behavior.test.js
python eval_accuracy.py       :: add --gemma to include the LLM fallback
```

---

## What's coming

Right now every chore is hand-coded: a bit of code for the recycle bin, another for Spotify, and so on. That's
not very lazy, is it?

The big idea is to **stop coding features one at a time**. A framework that lets Moss work with software and
tasks on her own, so a new chore is something she *figures out* instead of something someone writes at 2 a.m.:

- [ ] A chore framework: describe what a tool can do, and Moss plans and runs it (think "rename these screenshots" or "clean up my Downloads")
- [ ] Safety by default: always ask before anything permanent, and tell you what she did afterwards
- [ ] Better understanding of loose phrasing (volume/mute are the weakest spots right now)
- [ ] More players than Spotify
- [ ] macOS / Linux support for the chores
- [ ] Wake word, so she doesn't need to listen all the time
- [ ] Easy outfit and character swapping

These are plans, not features. None of the framework exists yet.

---

## Contributing

Contributions are very welcome, whether it's a new chore, a bug fix, a better phrasing list, or a character.

1. Fork the repo and create a branch.
2. Make your change. A new voice command usually means a matcher in `intents.py`, a flow in `chores.py`, and (if it touches Windows) a function in `winops.py`.
3. **Add tests.** `tests_skills.py` runs without a GPU or Windows. Chores use a fake `winops`, so you can test flows safely.
4. Run the tests above, and `python eval_accuracy.py` to check you haven't made her understand worse. Add your phrasings to `CORES` / `NEGATIVE`.
5. Open a pull request and say what you changed and why.

Good first issues: more phrasing variants, new chores that are *reversible*, translations, docs, and screenshots.
Please keep dangerous chores behind a "say yes" step.

---

## Credits

- [Whisper](https://github.com/openai/whisper), [Kokoro](https://github.com/hexgrad/kokoro), [Gemma](https://ai.google.dev/gemma), [Ollama](https://ollama.com)
- [three.js](https://threejs.org), [three-vrm](https://github.com/pixiv/three-vrm), [Electron](https://www.electronjs.org)
- Idea inspired by [Mate-Engine](https://github.com/shinyflvre/Mate-Engine)
- **Character model:** "Zainab-Chan" by **mimenn_**, from [VRoid Hub](https://hub.vroid.com/en/characters/542563936448829639/models/1717281170322434139) (VRM 1.0). Not my work. As shown on its page:
  avatar use, corporate use and personal commercial use are allowed and credit is required; redistribution, modification
  and redistribution of modified versions are not allowed; no sexual, religious/political or hateful use. That is why the
  model file is not in this repo. Moss only poses and renders it at run time and never edits or ships the file.
  Check the model page for its current terms.

## License

The code in this repo is released under the [MIT License](LICENSE). Models and characters keep their own licenses (see Credits).