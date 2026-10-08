"""normalize.py — Cyrillic->Latin correctness incl. digraphs (CONTRACTS #9)."""
import re

from clipai.normalize import (
    align_token, has_cyrillic, normalize_display, to_latin, transliterate_words,
)

CYR_RE = re.compile(r"[Ѐ-ӿ]")


def test_digraphs():
    assert to_latin("Љубав") == "Ljubav"
    assert to_latin("њега") == "njega"
    assert to_latin("џапа") == "džapa"
    assert to_latin("Ђорђе") == "Đorđe"
    assert to_latin("Ћирило") == "Ćirilo"


def test_full_sentence():
    out = to_latin("Мој ховеркрафт је пун јегуља.")
    assert out == "Moj hoverkraft je pun jegulja."
    assert not CYR_RE.search(out)


def test_mixed_and_latin_passthrough():
    assert to_latin("ovo je latinica") == "ovo je latinica"
    assert to_latin("") == ""


def test_word_count_preserved():
    cyr = "Ово јe српски тест са десет речи укупно број"
    lat = " ".join(transliterate_words(cyr.split())[0])
    assert len(cyr.split()) == len(lat.split())


def test_align_token_strips_punct():
    assert align_token("Odlazio,") == "odlazio"
    assert align_token("Šta?!") == "šta"
    assert align_token("đura") == "đura"


def test_normalize_display():
    assert normalize_display("  Ово   је  тест  ") == "Ovo je test"
