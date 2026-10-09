"""Transcript data contracts — the single source of truth for the schema.

Every module that touches transcript.json MUST use these models (import, never
re-declare). Contract tests in tests/test_contracts.py enforce the invariants;
transcript.schema.json mirrors this for non-Python consumers (UI, tooling).

pydantic v1 API (installed: 1.10.5).
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, root_validator, validator

SCHEMA_VERSION = "1.0"


class Script(str, Enum):
    LATIN = "latin"
    CYRILLIC = "cyrillic"


class SuggestionSource(str, Enum):
    DICT = "dict"        # hunspell-sr exact/alternate
    FUZZY = "fuzzy"      # rapidfuzz Levenshtein vs dictionary
    PHONETIC = "phonetic"  # abydos phonetic match
    BERTIC = "bertic"    # classla/bcms-bertic fill-mask
    SRBERTA = "srberta"  # JelenaTosic/SRBerta fill-mask
    LLM = "llm"          # optional future tier-2
    USER = "user"        # operator-provided


class Suggestion(BaseModel):
    text: str
    source: SuggestionSource
    score: Optional[float] = None  # provider-specific confidence/rank score


class Word(BaseModel):
    w: str                       # working display text (Latin after normalize)
    start: float                 # seconds, relative to media timeline
    end: float
    prob: Optional[float] = None          # ASR confidence, 0..1
    edited: bool = False                  # operator touched it
    cyr: Optional[str] = None             # original Cyrillic form (provenance)
    sugg: List[Suggestion] = Field(default_factory=list)
    flags: List[str] = Field(default_factory=list)  # low_prob | dict_miss | align_weak

    @validator("end")
    def _end_after_start(cls, v, values):
        if "start" in values and v < values["start"]:
            raise ValueError("word end < start")
        return v


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str                            # display text (join of word.w)
    words: List[Word] = Field(default_factory=list)
    align_quality: Optional[float] = None  # 0..1 alignment health metric

    @root_validator
    def _words_within_bounds(cls, values):
        s, e = values.get("start"), values.get("end")
        if e is not None and s is not None and e < s:
            raise ValueError("segment end < start")
        prev_end = None
        for w in values.get("words") or []:
            if prev_end is not None and w.start < prev_end - 1e-6:
                raise ValueError("words out of order")
            prev_end = w.end
        return values


class TranscriptMeta(BaseModel):
    model: str                           # ASR engine id, e.g. "sr-v3-ct2"
    hotwords_topic: Optional[str] = None
    align_method: Optional[str] = None   # primary: wav2vec2-sr | stable-ts | fw-word-ts | segment
    align_detail: Optional[str] = None   # e.g. "stable-ts fallback on 2/10 segs"
    source_video: Optional[str] = None
    created: Optional[str] = None        # ISO8601
    schema_version: str = SCHEMA_VERSION


class Transcript(BaseModel):
    lang: str = "sr"
    script: Script = Script.LATIN
    segments: List[Segment] = Field(default_factory=list)
    meta: TranscriptMeta

    @root_validator
    def _segments_in_order(cls, values):
        prev_end = None
        for s in values.get("segments") or []:
            if prev_end is not None and s.start < prev_end - 1e-6:
                raise ValueError("segments out of order")
            prev_end = s.end
        return values

    # ---- io ----
    def save(self, path: Path) -> None:
        Path(path).write_text(
            self.json(ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        return cls.parse_obj(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- helpers ----
    def iter_words(self):
        for s in self.segments:
            for w in s.words:
                yield s, w

    def flagged_words(self, prob_below: float = 0.65) -> List[Word]:
        """Fix-queue membership: explicit flags OR low prob (pre-flags stage)."""
        return [w for _, w in self.iter_words()
                if w.flags or (w.prob is not None and w.prob < prob_below)]
