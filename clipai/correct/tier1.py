"""Tier-1 correction — SRBerta masked-LM candidate generation.

JelenaTosic/SRBerta is RobertaForMaskedLM (verified); it produces top-k
fill-mask candidates for a <mask> placed at the flagged word. W0 spike: 3/8
top-5 on synthetic whole-word cloze — viable but unproven, hence OFF by
default and invoked per-request from the fix queue (never batch/silent).

BERTić (bcms-bertic) is an ELECTRA discriminator, not an MLM — it cannot
generate. Its optional role here is rescoring: a candidate replacing the mask
that the discriminator flags as "replaced" is demoted.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from ..types import Suggestion, SuggestionSource, Word

logger = logging.getLogger("clipai.correct.tier1")

SRBERTA = "JelenaTosic/SRBerta"
TOKEN_RE = re.compile(r"[^\w'čćđšžČĆĐŠŽ]+", re.UNICODE)

_pipe = None


def available() -> bool:
    try:
        import transformers, torch  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline("fill-mask", model=SRBERTA, device=-1)  # cpu
    return _pipe


def suggest(word: Word, context: str, top: int = 5) -> List[Suggestion]:
    """Context-masked suggestions for a flagged word. Never raises; returns []
    if model unavailable or mask token unsupported."""
    w = TOKEN_RE.sub("", word.w)
    if len(w) < 2 or not context.strip():
        return []
    try:
        pipe = _load()
        mask = pipe.tokenizer.mask_token
        masked = re.sub(rf"(?i)\b{re.escape(w)}\b", mask, context, count=1)
        if masked == context:
            masked = context.replace(w, mask, 1)
        if mask not in masked:
            return []
        out = []
        for r in pipe(masked, top_k=top):
            tok = r["token_str"].strip()
            if tok and tok.lower() != w.lower() and \
                    all(s.text != tok for s in out):
                out.append(Suggestion(text=tok, source=SuggestionSource.SRBERTA,
                                      score=round(r["score"], 4)))
        return out
    except Exception as e:
        logger.warning("srberta suggest failed for %r: %s", w, e)
        return []
