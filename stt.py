"""Ears: Whisper large-v3-turbo running on the same CUDA torch as everything else."""
import re

import numpy as np
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

# Whisper's classic hallucinations on near-silence
_JUNK = {"you", "thank you", "thanks for watching", "thanks", "bye", "the end", ""}


class Transcriber:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = WhisperProcessor.from_pretrained(cfg.stt_model)
        self.model = (
            WhisperForConditionalGeneration.from_pretrained(cfg.stt_model, dtype=torch.float16)
            .to("cuda").eval()
        )
        self.transcribe(np.zeros(16000, dtype=np.float32))  # warm-up

    @torch.inference_mode()
    def transcribe(self, audio: np.ndarray) -> str:
        feats = self.proc(audio, sampling_rate=16000, return_tensors="pt").input_features
        feats = feats.to("cuda", torch.float16)
        ids = self.model.generate(
            feats, language=self.cfg.stt_language, task="transcribe", max_new_tokens=128
        )
        text = self.proc.batch_decode(ids, skip_special_tokens=True)[0]
        text = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", text)  # [BLANK_AUDIO], (music)
        text = re.sub(r"\s+", " ", text).strip()
        return "" if text.lower().strip(" .!?,") in _JUNK and len(text) < 14 and text.lower().strip(" .!?,") != "bye" else text
