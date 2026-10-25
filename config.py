"""All the knobs in one place."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    # --- identity ---------------------------------------------------------
    name: str = "Moss"          # the companion's name
    user_name: str = "Zoro"     # what it calls you

    # --- brain (Ollama) ---------------------------------------------------
    ollama_host: str = "http://127.0.0.1:11434"
    llm_model: str = "gemma4:e4b"   # fallback if you want it snappier: "qwen3.5:4b"
    llm_keep_alive: str = "30m"
    llm_num_ctx: int = 4096
    llm_max_tokens: int = 160       # voice replies should be short
    llm_temperature: float = 0.7
    history_turns: int = 12         # remembered user/assistant exchanges

    # --- ears -------------------------------------------------------------
    stt_model: str = "openai/whisper-large-v3-turbo"
    stt_language: str = "en"
    mic_device: int | str | None = None   # None = system default
    vad_aggressiveness: int = 2           # 0-3, higher = stricter
    min_rms: int = 150                    # raise if background noise triggers it
    end_silence_ms: int = 600             # pause that ends your sentence
    max_utterance_s: float = 20.0

    # --- mouth ------------------------------------------------------------
    tts_voice: str = "jf_alpha"    # Japanese girl voice speaking English. Audition: python voice_test.py
    # other cute options: "jf_tebukuro", "jf_nezumi", "jf_gongitsune", or a blend like "jf_alpha,af_bella"
    # (a comma blends voices evenly). Old default: "af_heart"
    tts_speed: float = 0.92
    tts_pitch: float = 1.05        # >1 = higher and cuter (plays the audio slightly faster); 1.0 = off
    output_device: int | str | None = None

    # --- interruption -----------------------------------------------------
    # Talk over it to make it stop. Needs HEADPHONES, otherwise it hears itself.
    barge_in: bool = False
    barge_rms: int = 500

    # --- desktop body (Electron) -------------------------------------------
    body_enabled: bool = True      # run the 3D desktop companion
    launch_body: bool = True       # start/stop the Electron body from main.py
    bridge_port: int = 8765
    windows_poll_hz: float = 15.0  # how often to look for windows to sit on

    # --- music dancing (Windows: listens to your speakers, never the mic) -----
    music_enabled: bool = True
    music_threshold: float = 0.02   # loudness (0-1) that counts as "music is playing"; raise if it dances to noise
    music_min_seconds: float = 1.0  # must stay that loud this long before it starts dancing
    music_hold_seconds: float = 3.0 # silence this long before it stops

    # --- chores (voice commands) ------------------------------------------
    chores_enabled: bool = True
    llm_intent_fallback: bool = True   # let Gemma catch looser phrasing ("flip to the following song")
    notes_path: str = r"E:\DEV Challenges\Week 3\Moss Notes.txt"
    notes_open: str = "first"          # open Notepad on the "first" note of a session, "always", or "never"
    confirm_timeout_s: float = 8.0     # how long it waits for your yes/no before the recycle bin
    note_timeout_s: float = 12.0       # how long it waits for you to start dictating a note
    media_require_spotify: bool = True # only touch the media keys while Spotify.exe is running
    media_prev_twice: bool = True      # "previous" = restart + previous, so it really goes back a track

    # --- lazy score, volume, intro ----------------------------------------
    stats_path: str = "moss_stats.json"  # the lazy score is kept here (relative to the project folder)
    lazy_brag_every: int = 5           # Moss brags about the score after every Nth chore (0 = only when asked)
    volume_presses: int = 5            # volume keys per request (about 2 percent each on Windows)
    intro_on_start: bool = False       # True = give the full introduction when Moss starts (or run: python main.py --intro)

    # --- safety -----------------------------------------------------------
    allow_cpu: bool = False        # refuse to run on CPU-only torch unless True


CFG = Config()
