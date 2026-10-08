"""Contract tests — cross-wave enforcement (CONTRACTS.md invariants).

These run in every wave; breaking them means a wave regressed the schema.
"""
import json
from pathlib import Path

import pytest

from clipai.types import Transcript, Segment, Word, TranscriptMeta, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "clipai" / "contracts" / "transcript.schema.json"

CYR_RE = __import__("re").compile(r"[Ѐ-ӿ]")


def sample_transcript() -> Transcript:
    return Transcript(
        meta=TranscriptMeta(model="sr-v3-ct2", align_method="wav2vec2-sr"),
        segments=[
            Segment(id=0, start=0.0, end=1.5, text="Ovo je test",
                    words=[
                        Word(w="Ovo", start=0.0, end=0.4, prob=0.99, cyr="Ово"),
                        Word(w="je", start=0.5, end=0.7, prob=0.98, cyr="је"),
                        Word(w="test", start=0.8, end=1.5, prob=0.9),
                    ]),
            Segment(id=1, start=2.0, end=3.0, text="slova š đ č",
                    words=[
                        Word(w="slova", start=2.0, end=2.4, prob=0.9, cyr="слова"),
                        Word(w="š", start=2.5, end=2.6, prob=0.8, cyr="ш"),
                        Word(w="đ", start=2.6, end=2.7, prob=0.8, cyr="ђ"),
                        Word(w="č", start=2.7, end=3.0, prob=0.8, cyr="ч"),
                    ]),
        ],
    )


def test_roundtrip(tmp_path):
    t = sample_transcript()
    p = tmp_path / "t.json"
    t.save(p)
    t2 = Transcript.load(p)
    assert t2 == t
    raw = p.read_text(encoding="utf-8")
    assert "Ово" in raw  # provenance preserved


def test_json_schema_match():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(json.loads(sample_transcript().json()), schema)


def test_word_end_before_start_rejected():
    with pytest.raises(Exception):
        Word(w="x", start=1.0, end=0.5)


def test_words_out_of_order_rejected():
    with pytest.raises(Exception):
        Segment(id=0, start=0, end=2, text="a b", words=[
            Word(w="a", start=1.0, end=1.5),
            Word(w="b", start=0.2, end=0.4),
        ])


def test_segments_out_of_order_rejected():
    with pytest.raises(Exception):
        Transcript(meta=TranscriptMeta(model="x"), segments=[
            Segment(id=0, start=5, end=6, text="b"),
            Segment(id=1, start=0, end=1, text="a"),
        ])


def test_flagged_words():
    t = sample_transcript()
    flagged = t.flagged_words(0.9)
    assert {w.w for w in flagged} == {"š", "đ", "č"}
