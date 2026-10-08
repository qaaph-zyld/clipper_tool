"""Serbian script normalization: Cyrillic -> Latin via cyrtranslit.

cyrtranslit is word-preserving for Serbian (digraphs lj/nj/dž count as one
orthographic letter but map to 2 ASCII chars inside the same token), so word
indices are stable across transliteration — which is what makes
align-then-display-map possible (CONTRACTS.md #9, #10).
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Tuple

import cyrtranslit

CYR_RE = re.compile(r"[Ѐ-ӿ]")
PUNCT_RE = re.compile(r"[^\w\sčćđšžČĆĐŠŽ]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")

# cyrtranslit maps uppercase Љ/Њ/Џ to titlecase Lj/Nj/Dž even inside all-caps
# words ("ЉУБАВ" -> "LjUBAV"). Inside an all-caps context the correct Serbian
# Latin form is LJ/NJ/DŽ. A digraph is "inside all-caps" if either neighbour
# is an uppercase letter.
_UP = r"A-ZČĆĐŠŽ"
CAP_DIGRAPH_RE = re.compile(
    rf"(?<=[{_UP}])Lj|Lj(?=[{_UP}])|(?<=[{_UP}])Nj|Nj(?=[{_UP}])|"
    rf"(?<=[{_UP}])Dž|Dž(?=[{_UP}])")
_CAP_FIX = {"Lj": "LJ", "Nj": "NJ", "Dž": "DŽ"}


def has_cyrillic(text: str) -> bool:
    return bool(CYR_RE.search(text))


def to_latin(text: str) -> str:
    """Cyrillic -> Serbian Latin. No-op for pure-Latin input."""
    if not text:
        return text
    t = cyrtranslit.to_latin(text)
    return CAP_DIGRAPH_RE.sub(lambda m: _CAP_FIX[m.group(0)], t)


def normalize_display(text: str) -> str:
    """Latin + NFC + whitespace collapse. Keeps punctuation (display text)."""
    t = unicodedata.normalize("NFC", to_latin(text))
    return SPACE_RE.sub(" ", t).strip()


def align_token(word: str) -> str:
    """Lowercase, punctuation-free token for the wav2vec2 aligner.

    Used for aligner INPUT only — timings map back to display words by index.
    """
    return PUNCT_RE.sub("", word.lower())


def split_words(text: str) -> List[str]:
    return text.split()


def transliterate_words(words: List[str]) -> Tuple[List[str], List[str]]:
    """Return (latin_words, cyr_originals) with identical list lengths."""
    lat = [normalize_display(w) for w in words]
    cyr = [w if has_cyrillic(w) else None for w in words]
    return lat, cyr
