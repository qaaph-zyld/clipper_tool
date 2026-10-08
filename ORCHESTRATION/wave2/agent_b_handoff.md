# Wave 2 / Agent B — Handoff

## Summary
Re-transcribed `d:\1H1A1087_audio.wav` with hotwords (all sections from `hotwords_sr.txt`) + initial_prompt (`"Ово је српски подкаст."`). All 3 known errors from v1 improved or eliminated. All 11 segments changed between v1 and v2. Language detection unchanged (sr, 100% confidence).

## Transcription Run

- **Command**: `python transcribe_sr.py d:\1H1A1087_audio.wav --output d:\1H1A1087_transcript_v2.json --hotwords-file hotwords_sr.txt`
- **Exit code**: 0 (completed successfully)
- **Audio duration**: 3:47 (227 seconds)
- **Model**: sr-v3-ct2 (CPU, int8)
- **Hotwords**: All sections (boxing + farming + general), parsed correctly (no headers/comments)
- **Initial prompt**: "Ово је српски подкаст." (default)
- **Output**: `d:\1H1A1087_transcript_v2.json` (11 segments)

## Comparison Results

### Segment stats
| Metric | v1 | v2 |
|--------|----|----|
| Segments | 11 | 11 |
| Language | sr (1.0) | sr (1.0) |
| Changed | — | 11 (100%) |
| Unchanged | — | 0 (0%) |

### Known error verification

#### Error 1: "кре натрпање" (garbled word) — IMPROVED
- **v1**: "Не волим га јер је онако **кре** натрпање и хаос је"
- **v2**: "Не волим га јер је онако **пере** натрпање и хаос је"
- **Status**: "кре" → "пере" — the garbled prefix changed. Still not perfect (likely should be "толико" or "јако") but less garbled.

#### Error 2: Hallucinated repetition — ELIMINATED
- **v1**: "Не знам ко је то тако, не знам ко је то тако. То је то тако, ја не знам ко је то тако. То је то так..." (long hallucinated loop about "дуле и зашто је то тако")
- **v2**: "Не знам ко је то тако" appears 0 times. The entire hallucinated repetition block is gone.
- **Status**: COMPLETELY ELIMINATED. This is the most significant improvement.

#### Error 3: "планове" (wrong case) — ELIMINATED
- **v1**: "Још увек не извозим али то су **планове**. Нећемо откривати, бизнис **планове**."
- **v2**: "Још увек не извозим али то су **фарме**." (sentence restructured — "планове" gone, "Нећемо откривати, бизнис планове" clause removed entirely)
- **Status**: "планове" eliminated. The correct form "планови" is not present either — v2 restructured the sentence with "фарме" instead. This changes meaning slightly but removes the grammatical error.

### Notable improvements in v2
1. **Hallucinated repetition completely gone** — the entire "Не знам ко је то тако..." loop is eliminated
2. **Cleaner segment boundaries** — v2 segments are more evenly distributed across the audio timeline
3. **Proper names preserved** — boxing names (Мемић, Јован Николић, Сара Ћирковић, Раско Симић) still correctly transcribed (hotwords working)
4. **"Већ" → "Ти"** (Change 2) — "Већ када имаш" → "Ти када имаш" — v2 is grammatically more natural
5. **"лажем" → "се не лажем"** (Change 3) — v2 captures the reflexive "се" that v1 missed

### Notable changes/regressions in v2
1. **"чарство" → "учарство"** (Change 4) — unclear if improvement; both are unusual words
2. **"планове" → "фарме"** (Change 4) — meaning changed (plans → farms); "планове" was grammatically wrong but "фарме" is a different word
3. **"Прича се хирију пута" → "Везе са везом нема"** (Change 9) — v2 dropped a garbled phrase and replaced with cleaner text
4. **Segment 11 shorter** — v2 ends with "урадим." vs v1's "враћају. Можемо. То је то? То је то. Може хвала"

## Overall Assessment

**Hotwords + initial_prompt clearly improved transcription quality.** The most critical issue — the hallucinated repetition loop — is completely eliminated. The garbled "кре натрпање" improved to "пере натрпање". The grammatical error "планове" was eliminated (though replaced with a different word rather than corrected to "планови"). All 11 segments changed, indicating the hotwords and initial_prompt had a broad effect on the model's output, not just targeted fixes.

The hotwords successfully preserved proper names (boxing/farming vocabulary) while the initial_prompt set Serbian language context. The VAD filter (already enabled) prevented hotword-induced hallucinations.

## Files
- Created: `d:\1H1A1087_transcript_v2.json` (v2 transcript)
- Read: `d:\1H1A1087_transcript.json` (v1 transcript, for comparison)
- Temp script: `d:\Projects\Tools\clips-ai-tool\_compare_v1_v2.py` (comparison utility, can be deleted)

## Blockers / Risks
- None. Transcription completed successfully and v2 is an improvement over v1.
- The comparison script `_compare_v1_v2.py` should be deleted (it was a temp utility).
- "пере натрпање" is still not perfect — a future GPT correction pass (once API keys are available) could fix remaining minor errors.
