"""Caption + render math tests — no ffmpeg/video needed."""
from clipai.captions import build_ass, build_srt, build_vtt, _group_lines
from clipai.render import remap_time, _shifted_transcript
from clipai.reframe import crop_geometry, smooth, x_expression
from clipai.types import Segment, Transcript, TranscriptMeta, Word


def _t():
    ws1 = [Word(w="ej", start=0, end=.4), Word(w="slušaj", start=.4, end=.9),
           Word(w="ovo", start=.9, end=1.2), Word(w="je", start=1.2, end=1.4),
           Word(w="najjači", start=1.4, end=1.9), Word(w="podkast.", start=1.9, end=2.4)]
    ws2 = [Word(w="Đe", start=5, end=5.3), Word(w="si", start=5.3, end=5.5),
           Word(w="bio?", start=5.5, end=5.9)]
    return Transcript(meta=TranscriptMeta(model="t"), segments=[
        Segment(id=0, start=0, end=2.4,
                text=" ".join(w.w for w in ws1), words=ws1),
        Segment(id=1, start=5, end=5.9,
                text=" ".join(w.w for w in ws2), words=ws2)])


def test_karaoke_ass_kf_and_grouping():
    ass = build_ass(_t(), 0, 10)
    assert "{\\kf40}ej" in ass            # 0.4s -> 40cs
    assert "Style: Karaoke,DejaVu Sans" in ass
    evts = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    # char limit splits "podkast." onto its own line; "Đe si bio?" is event 3
    assert len(evts) == 3
    assert "podkast." in evts[1] and "Đe" in evts[2]


def test_ass_clip_offset():
    ass = build_ass(_t(), clip_start=5, clip_end=10)
    evts = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert evts[0].split(",")[1] == "0:00:00.00"   # re-based to clip start


def test_srt_vtt():
    t = _t()
    srt = build_srt(t, 0, 10)
    assert "00:00:00,000 --> 00:00:01,900" in srt
    vtt = build_vtt(t, 0, 10)
    assert vtt.startswith("WEBVTT") and "00:00:00.000" in vtt


def test_group_lines_limits():
    words = [Word(w=f"w{i:02d}", start=i, end=i + .5) for i in range(8)]
    lines = _group_lines(words)
    assert len(lines) == 2 and len(lines[0]) == 6


def test_remap_time():
    cuts = [(10, 12), (20, 25)]
    assert remap_time(5, cuts) == 5
    assert remap_time(11, cuts) == 10       # inside cut -> boundary (10-2+... )
    assert remap_time(21, cuts) == 18       # inside 2nd cut -> out pos of t=20
    assert remap_time(30, cuts) == 23       # 30 - 2 - 5


def test_shifted_transcript():
    t = _shifted_transcript(_t(), [(2.5, 4.5)], clip_start=0)
    assert abs(t.segments[1].words[0].start - 3.0) < 1e-6   # 5 - 2 cut secs
    # word inside the deleted range is dropped entirely
    t2 = _shifted_transcript(_t(), [(4.5, 5.45)], clip_start=0)
    assert [w.w for w in t2.segments[-1].words] == ["bio?"]


def test_crop_geometry():
    cw, ch, cy = crop_geometry(1920, 1080)
    assert (cw, ch, cy) == (607, 1080, 0)          # wide -> center-ish w=607? int(1080*9/16)=607
    cw, ch, cy = crop_geometry(1080, 1920)
    assert (cw, ch) == (1080, 1920)


def test_smooth_resets_on_gap():
    tr = [(0, .3), (.5, .4), (1.0, .4), (10.0, .9), (10.5, .9)]
    out = smooth(tr, alpha=.35)
    assert out[3][1] == .9   # >2s gap -> re-init, not dragged from .4


def test_x_expression_static_and_track():
    assert x_expression({"mode": "static", "x": 100}, 0) == "100"
    expr = x_expression({"mode": "track", "steps": [
        {"t": 0, "x": 50}, {"t": 1, "x": 80}]}, 0)
    assert "if(lt(t" in expr and "80" in expr


def test_no_cyrillic_in_caption_output():
    """CONTRACTS #11: caption outputs must be Cyrillic-free."""
    import re
    from clipai.transcribe import _normalize, _to_transcript
    raw = {"language": "sr", "segments": [
        {"id": 0, "start": 0, "end": 2, "text": "Љубав је џаба.",
         "words": [{"word": "Љубав", "start": 0, "end": .8, "prob": .9},
                   {"word": "је", "start": .8, "end": 1.1, "prob": .9},
                   {"word": "џаба.", "start": 1.1, "end": 2, "prob": .9}]}]}
    t = _normalize(_to_transcript(raw, "sr-v3-ct2", None, None))
    cyr = re.compile(r"[Ѐ-ӿ]")
    for out in (build_ass(t, 0, 10), build_srt(t, 0, 10), build_vtt(t, 0, 10)):
        assert not cyr.search(out), out[:200]
