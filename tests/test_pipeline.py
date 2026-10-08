"""Unit tests for score/smartcut/splice/transcribe internals — synthetic data,
no model loading."""
import json
from pathlib import Path

from clipai.score import find_clips, HOOKS, POSITIVE, NEGATIVE
from clipai.smartcut import snap_cut_edge, propose_cuts, Strength, detect_silences
from clipai.splice import invert_ranges, audio_filtergraph, crossfade_filtergraph
from clipai.transcribe import _to_transcript, _normalize
from clipai.types import Segment, Transcript, TranscriptMeta, Word


def _t(words_per_seg):
    segs = []
    for i, ws in enumerate(words_per_seg):
        words = [Word(w=w, start=s, end=e, prob=p) for w, s, e, p in ws]
        segs.append(Segment(id=i, start=words[0].start, end=words[-1].end,
                            text=" ".join(w.w for w in words), words=words))
    return Transcript(segments=segs, meta=TranscriptMeta(model="test"))


# ---- score ----

def test_lexicons_loaded():
    assert HOOKS and POSITIVE and NEGATIVE


def test_find_clips_prefers_hooky_dense_window():
    # segment A: dense + hook words; segment B: sparse filler
    a = []
    for i in range(5):
        o = i * 3.0
        a += [("slušaj", o, o+.4, .9), ("ovo", o+.4, o+.7, .9), ("je", o+.7, o+.9, .9),
              ("najjači", o+.9, o+1.3, .9), ("podkast", o+1.3, o+1.8, .9),
              ("ikada", o+1.8, o+2.2, .9)]
    b = [("pa", 40, 41, .9), ("eto", 43, 44, .9)]
    t = _t([a, b])
    clips = find_clips(t, num_clips=1, min_duration=15, max_duration=60)
    assert clips and clips[0]["start"] < 30


def test_find_clips_empty_transcript():
    t = Transcript(segments=[], meta=TranscriptMeta(model="test"))
    try:
        find_clips(t)
        assert False
    except ValueError:
        pass


# ---- smartcut ----

def test_snap_ladder_clean_then_snapped_then_none():
    sils = [(10.0, 10.4), (20.0, 20.2)]
    t, q = snap_cut_edge(10.1, sils)
    assert q == "clean" and abs(t - 10.2) < 1e-6
    t, q = snap_cut_edge(20.9, sils)
    assert q == "snapped" and abs(t - 20.1) < 1e-6
    t, q = snap_cut_edge(50.0, sils)
    assert q == "no-clean-cut" and t == 50.0


def test_propose_cuts_gentle_vs_aggressive(tmp_path):
    # no audio file needed if we stub detect_silences
    import clipai.smartcut as sc
    ws = [("znaš", 5.0, 5.3, .9), ("šta", 5.4, 5.7, .9)]
    t = _t([ws])
    sc.detect_silences_orig = sc.detect_silences
    try:
        sc.detect_silences = lambda p, **k: [(5.31, 5.39)]
        props = propose_cuts(t, tmp_path / "x.wav", Strength.GENTLE)
        assert len(props) == 1 and props[0].reason == "filler"
        assert props[0].words == ["znaš"]
    finally:
        sc.detect_silences = sc.detect_silences_orig


# ---- splice ----

def test_invert_ranges():
    assert invert_ranges([(2, 3), (5, 6)], 10) == [(0.0, 2), (3, 5), (6, 10)]
    assert invert_ranges([], 4) == [(0.0, 4)]


def test_filtergraphs():
    fg = audio_filtergraph([(1.0, 2.0)])
    assert "atrim" in fg and "concat" not in fg
    fg = audio_filtergraph([(0, 1), (2, 3), (4, 5)])
    assert "concat=n=3" in fg
    fg = crossfade_filtergraph([(0, 1), (2, 3)])
    assert "acrossfade" in fg


# ---- transcribe internals ----

def test_to_transcript_and_normalize(tmp_path):
    raw = {"language": "sr", "segments": [
        {"id": 0, "start": 0, "end": 2, "text": " ЉУБАВ њега ",
         "words": [{"word": "ЉУБАВ", "start": 0, "end": 1, "prob": .9},
                   {"word": "њега", "start": 1, "end": 2, "prob": .8}]}]}
    t = _to_transcript(raw, "sr-v3-ct2", None, "v.mp4")
    assert t.script == "cyrillic"
    t = _normalize(t)
    assert t.script == "latin"
    w = t.segments[0].words
    assert w[0].w == "LJUBAV" and w[0].cyr == "ЉУБАВ"  # all-caps digraph fix
    assert w[1].w == "njega" and w[1].cyr == "њега"
    assert t.segments[0].text == "LJUBAV njega"


def test_to_transcript_no_words():
    raw = {"language": "sr", "segments": [
        {"id": 0, "start": 0, "end": 5, "text": "hello", "words": []}]}
    t = _to_transcript(raw, "medium", None, None)
    assert t.segments[0].words == [] and t.segments[0].text == "hello"
