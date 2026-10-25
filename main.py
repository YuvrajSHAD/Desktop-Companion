"""Moss - a voice-first desktop sloth. Hear (Whisper) -> think (LLM via Ollama) -> speak (Kokoro),
with a 3D VRM body (Electron) that sits on your taskbar and windows.

    python main.py          # talk to it (hands-free)
    python main.py --text   # type instead of talking (handy for debugging the brain + voice)
    python main.py --no-body  # voice + brain only, no 3D character
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from pathlib import Path

import intents
from config import CFG

ROOT = Path(__file__).resolve().parent
EXIT_WORDS = {"goodbye", "good bye", "exit", "quit", "shut down", "go to sleep"}
RESET_WORDS = {"reset", "forget everything", "start over"}


def check_gpu():
    import torch

    print(f"torch {torch.__version__} | CUDA available: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        if CFG.allow_cpu:
            print("WARNING: running on CPU, expect it to be slow.")
            return
        sys.exit(
            "This torch build can't see the GPU (looks like the CPU wheel).\n"
            "Fix:  pip uninstall -y torch torchaudio torchvision\n"
            "      pip install -r requirements.txt"
        )
    print(f"GPU: {torch.cuda.get_device_name(0)}")


def launch_body():
    exe = ROOT / "body" / "node_modules" / "electron" / "dist" / "electron.exe"
    if not exe.exists():
        print("[body] Not installed yet. One-time setup:  cd body  &&  npm install")
        return None
    if not any((ROOT / "models").glob("*.vrm")):
        print("[body] No .vrm in the models folder (the sample ships as models\\character.vrm).")
    print("[body] starting the desktop companion...")
    return subprocess.Popen([str(exe), str(ROOT / "body")], cwd=str(ROOT / "body"))


def speak(speaker, sentences, mic=None, listener=None):
    """Play a sentence stream. Returns (playback, carried_frames) - carried_frames is set on barge-in."""
    from tts import Playback

    pb = Playback(speaker, sentences).start()
    cand: list = []
    carried = None
    while not pb.done.is_set():
        if mic is None:
            time.sleep(0.03)
            continue
        f = mic.read(0.03)  # also keeps the mic queue drained while we talk
        if f is None or not CFG.barge_in or carried is not None:
            continue
        if listener.voiced(f, CFG.barge_rms):
            cand.append(f)
            if len(cand) >= 10:  # ~300 ms of you talking over it
                pb.cancel()
                carried = cand
        else:
            cand = []
    pb.done.wait(1)
    if mic is not None and carried is None:
        time.sleep(0.2)  # let the tail of its own voice die out
        mic.drain()
    return pb, carried


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type instead of using the microphone")
    ap.add_argument("--no-body", action="store_true", help="skip the 3D desktop companion")
    ap.add_argument("--intro", action="store_true", help="start with the full introduction (for demo recordings)")
    args = ap.parse_args()

    check_gpu()
    from brain import Brain

    brain = Brain(CFG)
    brain.check()

    # --- desktop body link --------------------------------------------------
    bridge = watcher = body_proc = music = None
    if CFG.body_enabled and not args.no_body:
        from bridge import Bridge
        from winwatch import WindowWatcher

        bridge = Bridge(CFG.bridge_port, ROOT / ".bridge_token")
        try:
            bridge.start()
        except Exception as e:
            sys.exit(f"Couldn't open the body link on port {CFG.bridge_port}: {e}\n"
                     "Is another copy of Moss still running?")
        watcher = WindowWatcher(bridge, CFG.windows_poll_hz)

        def on_body_event(ev):
            kind = ev.get("type")
            if kind == "connected":
                watcher.own_hwnd = int(ev.get("hwnd") or 0)
                watcher.resend()
                print("[body] connected")
            elif kind == "touch":
                print(f"[body] you {ev.get('kind')}ed Moss")

        bridge.on_event = on_body_event
        watcher.start()
        if CFG.music_enabled:
            from music import MusicListener

            music = MusicListener(bridge, CFG)
            bridge.tap = music.note
            music.start()
        if CFG.launch_body:
            body_proc = launch_body()
    emit = bridge.emit if bridge else (lambda ev: None)

    print("Loading voice (first run downloads models, be patient)...")
    from tts import Speaker

    speaker = Speaker(CFG, bridge)
    mic = listener = stt = None
    if not args.text:
        from audio_io import Listener, Mic
        from stt import Transcriber

        stt = Transcriber(CFG)
        mic = Mic(CFG.mic_device)
        listener = Listener(mic, CFG)
        listener.on_speech_start = lambda: emit({"type": "state", "value": "listening"})
        mic.start()
    brain.warmup()

    # --- chores: recycle bin / notes / Spotify skip, as little spoken conversations --------
    skills = None
    if CFG.chores_enabled:
        from chores import Skills
        from stats import Tally

        def say(line):
            speak(speaker, iter([line]), mic, listener)

        def hear(timeout_s, patient=False):
            """Listen for one answer (a yes/no, or a note being dictated). '' if nothing was heard."""
            emit({"type": "state", "value": "listening"})
            if args.text:
                try:
                    return input("you: ").strip()
                except EOFError:
                    return ""
            audio = listener.listen(timeout=timeout_s,
                                    end_silence_ms=1400 if patient else None,  # let people pause mid-note
                                    max_s=60 if patient else None)
            if audio is None:
                return ""
            emit({"type": "state", "value": "thinking"})
            heard = stt.transcribe(audio)
            if heard:
                print(f"you: {heard}", flush=True)
                emit({"type": "heard", "text": heard})
            return heard

        tally = Tally(ROOT / CFG.stats_path)
        skills = Skills(CFG, say, hear, tally=tally, summarize=brain.summarize_notes)

    if skills and (args.intro or CFG.intro_on_start):
        skills.intro()  # demo mode: Moss introduces herself and says what she can do
    else:
        speak(speaker, iter([f"[happy] Hey {CFG.user_name}. I'm awake. Mostly."]), mic, listener)
    print("\nReady. Say 'goodbye' to quit, 'reset' to wipe its memory.")
    if skills:
        print("Chores: 'empty the recycle bin' | 'take a note' | 'what did I note today' | 'next song' / 'previous song'")
        print("        'volume up' / 'volume down' / 'mute' | 'lazy score' | 'introduce yourself'\n")

    carried = None
    try:
        while True:
            if args.text:
                text = input("you: ").strip()
                t_stt = 0.0
            else:
                audio = listener.listen(initial_frames=carried)
                carried = None
                if audio is None:
                    emit({"type": "state", "value": "idle"})
                    continue
                emit({"type": "state", "value": "thinking"})
                t0 = time.perf_counter()
                text = stt.transcribe(audio)
                t_stt = time.perf_counter() - t0
                if text:
                    print(f"you: {text}", flush=True)
            if not text:
                emit({"type": "state", "value": "idle"})
                continue
            emit({"type": "heard", "text": text})
            emit({"type": "state", "value": "thinking"})

            norm = text.lower().strip(" .!?,")
            if norm in EXIT_WORDS:
                if skills and skills.tally and skills.tally.today_stats()[0]:
                    speak(speaker, iter([skills.score_line()]), mic, listener)  # sign off with the day's score
                speak(speaker, iter(["[relaxed] Okay. Back to hanging around. See you."]), mic, listener)
                break
            if norm in RESET_WORDS:
                brain.reset()
                speak(speaker, iter(["[neutral] Done. Fresh slate."]), mic, listener)
                continue

            if skills:
                chore = intents.parse(text)
                if chore is None and CFG.llm_intent_fallback and intents.maybe_command(text):
                    chore = brain.classify(text)  # looser phrasing: let Gemma decide
                if chore:
                    print(f"  [chore: {chore.kind}]", flush=True)
                    skills.handle(chore)
                    brain.remember(text, " ".join(skills.said))
                    continue

            pb, carried = speak(speaker, brain.reply_stream(text), mic, listener)
            if pb.first_audio_at and not args.text:
                lag = pb.first_audio_at - listener.last_end
                print(f"  [stt {t_stt*1000:.0f} ms | you stopped -> first sound {lag*1000:.0f} ms]\n")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if mic:
            mic.stop()
        if watcher:
            watcher.stop()
        if music:
            music.stop()
        if body_proc:
            body_proc.terminate()


if __name__ == "__main__":
    main()
