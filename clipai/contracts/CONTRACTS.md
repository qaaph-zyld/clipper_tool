# transcript.json contracts — invariants

These invariants are enforced by `clipai/types.py` validators and
`tests/test_contracts.py`. Any wave that breaks them fails the gate.

## Schema invariants

1. `script` is `"latin"` or `"cyrillic"`. The pipeline product contract is
   `latin`; `cyrillic` exists only as an intermediate artifact class.
2. Every word has `w` (display text), `start`, `end`. `start <= end` per word,
   per segment, and segment order is non-decreasing.
3. `words[].start/end` are seconds on the media timeline, monotonically
   non-decreasing within a segment.
4. `cyr` is provenance only — never written after normalization, never
   reverse-transliterated. Edits update `w` and set `edited: true`.
5. `sugg[].source` ∈ {dict, fuzzy, phonetic, bertic, srberta, llm, user}.
6. `align_quality` ∈ [0,1] per segment; absent means "not measured".
7. `meta.align_method` ∈ {wav2vec2-sr, stable-ts, fw-word-ts, segment} — the
   method that produced word timestamps, for audit/debug.
8. UTF-8 everywhere; `json.dump(..., ensure_ascii=False)` on every write.

## Pipeline invariants

9. Transliteration happens ONCE, after ASR and before alignment. Word count
   must not change (cyrtranslit is word-preserving for Serbian).
10. Alignment operates on normalized Latin tokens (lowercase, punctuation
    stripped); timings map back to display words **by index** — display text is
    never rewritten by the aligner.
11. Caption/ASS/SRT/VTT output must contain zero Cyrillic codepoints
    (enforced by `test_no_cyrillic_in_caption_output`).
12. Smart-cut and delete-range operations never produce sub-word splices:
    cut boundaries snap to word boundaries, then to nearest VAD silence.
13. Crop trajectories never interpolate across a cut boundary — each output
    segment owns an independent crop track.
14. Render consumes only approved clip windows; the full source is never
    re-encoded except on explicit operator request.
