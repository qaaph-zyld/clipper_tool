"""Tier-0 correction cascade — non-LLM suggestions for flagged words.

Order per CONTRACTS: dict (hunspell suggest) -> fuzzy (rapidfuzz vs dictionary
stems) -> phonetic (abydos Beider-Morse / Daitch-Mokotoff) -> optional n-gram
context check. All local, all <50ms per word. Never mutates transcript text —
only fills `word.sugg`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from ..types import Suggestion, SuggestionSource, Word

logger = logging.getLogger("clipai.correct.tier0")

TOKEN_RE = re.compile(r"[^\w'čćđšžČĆĐŠŽ]+", re.UNICODE)
MAX_SUGGESTIONS = 5

_dict = None
_stems: Optional[List[str]] = None


def _dict_and_stems(dic_dir: Optional[Path] = None):
    global _dict, _stems
    if _dict is not None:
        return _dict, _stems
    from .flags import _load_dict  # reuse loader
    _load_dict(dic_dir)
    from . import flags
    _dict = flags._dict
    if _dict is not None:
        # raw stem list from .dic for fuzzy matching (unexpanded; affixes are
        # handled by hunspell.suggest for the dict tier)
        dic_path = Path(dic_dir or Path(__file__).resolve().parent.parent.parent
                        / "eval" / "hunspell") / "sr-Latn.dic"
        try:
            lines = dic_path.read_text(encoding="utf-8").splitlines()
            _stems = [ln.split("/")[0].strip() for ln in lines[1:]
                      if ln.strip()]
            _stems = [s for s in _stems if s]
        except Exception as e:
            logger.warning("stem list unavailable: %s", e)
            _stems = []
    return _dict, _stems


def _phonetic_candidates(word: str, stems: List[str], top: int = 3) -> List[str]:
    try:
        from abydos.phonetic import DaitchMokotoff, BMPM
        from rapidfuzz import process, fuzz
        dm = DaitchMokotoff()
        code = frozenset(dm.encode(word).split() if isinstance(dm.encode(word), str) else [])
        scored = process.extract(word, stems, scorer=fuzz.ratio, limit=top * 20)
        out = []
        for cand, _, _ in scored:
            try:
                cc = dm.encode(cand)
                if code and isinstance(cc, str) and code & frozenset(cc.split()):
                    out.append(cand)
            except Exception:
                continue
            if len(out) >= top:
                break
        return out
    except Exception as e:
        logger.debug("phonetic tier skipped: %s", e)
        return []


def suggest(word: Word, dic_dir: Optional[Path] = None) -> List[Suggestion]:
    """Tier-0 suggestions for one flagged word. Never raises."""
    w = TOKEN_RE.sub("", word.w)
    if len(w) < 2:
        return []
    out: List[Suggestion] = []
    try:
        d, stems = _dict_and_stems(dic_dir)
        if d is not None:
            for s in list(d.suggest(w))[:MAX_SUGGESTIONS]:
                out.append(Suggestion(text=s, source=SuggestionSource.DICT))
        if stems and len(out) < MAX_SUGGESTIONS:
            from rapidfuzz import fuzz, process
            for cand, score, _ in process.extract(w, stems, scorer=fuzz.ratio, limit=8):
                if score >= 80 and cand.lower() != w.lower() and \
                        all(s.text != cand for s in out):
                    out.append(Suggestion(text=cand, source=SuggestionSource.FUZZY,
                                          score=round(score, 1)))
                if len(out) >= MAX_SUGGESTIONS:
                    break
        if stems and len(out) < MAX_SUGGESTIONS:
            for cand in _phonetic_candidates(w, stems):
                if all(s.text != cand for s in out):
                    out.append(Suggestion(text=cand, source=SuggestionSource.PHONETIC))
                if len(out) >= MAX_SUGGESTIONS:
                    break
    except Exception as e:
        logger.warning("tier0 suggest failed for %r: %s", w, e)
    return out[:MAX_SUGGESTIONS]
