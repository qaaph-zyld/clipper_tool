import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

V1_PATH = r'd:\1H1A1087_transcript.json'
V2_PATH = r'd:\1H1A1087_transcript_v2.json'

with open(V1_PATH, 'r', encoding='utf-8') as f:
    v1 = json.load(f)
with open(V2_PATH, 'r', encoding='utf-8') as f:
    v2 = json.load(f)

ft1 = v1['full_text']
ft2 = v2['full_text']
segs1 = v1['segments']
segs2 = v2['segments']

print("=" * 70)
print("TRANSCRIPTION COMPARISON: v1 (baseline) vs v2 (hotwords + initial_prompt)")
print("=" * 70)

print()
print("### LANGUAGE DETECTION ###")
print(f"v1: language={v1['language']}  probability={v1['language_probability']}")
print(f"v2: language={v2['language']}  probability={v2['language_probability']}")

print()
print("### SEGMENT COUNTS ###")
print(f"v1 segments: {len(segs1)}")
print(f"v2 segments: {len(segs2)}")

print()
print("### FULL_TEXT LENGTHS ###")
print(f"v1 full_text chars: {len(ft1)}")
print(f"v2 full_text chars: {len(ft2)}")

# Match segments by closest start timestamp
def match_segments(a_segs, b_segs):
    matches = []
    used_b = set()
    for sa in a_segs:
        best_j = None
        best_d = None
        for j, sb in enumerate(b_segs):
            if j in used_b:
                continue
            d = abs(sa['start'] - sb['start'])
            if best_d is None or d < best_d:
                best_d = d
                best_j = j
        if best_j is not None and best_d is not None and best_d <= 3.0:
            used_b.add(best_j)
            matches.append((sa, b_segs[best_j], best_d))
        else:
            matches.append((sa, None, None))
    return matches

matches = match_segments(segs1, segs2)
changed = []
identical = 0
unmatched_v1 = 0
for sa, sb, d in matches:
    if sb is None:
        unmatched_v1 += 1
        continue
    if sa['text'].strip() == sb['text'].strip():
        identical += 1
    else:
        changed.append((sa, sb, d))

print()
print("### SEGMENT-BY-SEGMENT COMPARISON (matched by closest start time, <=3s) ###")
print(f"Identical segments: {identical}")
print(f"Changed segments:   {len(changed)}")
print(f"Unmatched v1 segments: {unmatched_v1}")
print(f"v2 segments not matched to any v1: {len(segs2) - sum(1 for m in matches if m[1] is not None)}")

print()
print("### CHANGED SEGMENTS (first 20) ###")
for idx, (sa, sb, d) in enumerate(changed[:20]):
    print(f"\n--- change {idx+1} | time_delta={d:.2f}s | v1_id={sa['id']} v2_id={sb['id']} | start={sa['start']:.2f} ---")
    print(f"v1 [{sa['start']:.2f}-{sa['end']:.2f}]: {sa['text']}")
    print(f"v2 [{sb['start']:.2f}-{sb['end']:.2f}]: {sb['text']}")

print()
print("=" * 70)
print("### KNOWN ERROR VERIFICATION ###")
print("=" * 70)

def ctx(s, needle, before=80, after=120):
    i = s.find(needle)
    if i < 0:
        return None
    return s[max(0, i-before):i+len(needle)+after]

print()
print("--- ERROR 1: 'кре натрпање' (garbled word) ---")
c1v1 = ctx(ft1, 'кре натрпање')
c1v2 = ctx(ft2, 'кре натрпање')
print(f"v1: {repr(c1v1)}")
print(f"v2 contains 'кре натрпање'? {'YES' if c1v2 else 'NO'}")
if c1v2:
    print(f"v2: {repr(c1v2)}")
else:
    # show context around the same area using a nearby stable phrase
    anchor = 'Не волим га јер је онако'
    print(f"v2 around '{anchor}': {repr(ctx(ft2, anchor))}")
    print("NOTE: 'кре натрпање' NOT present in v2 -> likely fixed/improved")

print()
print("--- ERROR 2: hallucinated repetition 'Не знам ко је то тако' ---")
c2v1 = ctx(ft1, 'Не знам ко је то тако')
c2v2 = ctx(ft2, 'Не знам ко је то тако')
print(f"v1: {repr(c2v1)}")
print(f"v2 contains 'Не знам ко је то тако'? {'YES' if c2v2 else 'NO'}")
if c2v2:
    print(f"v2: {repr(c2v2)}")
else:
    anchor = 'Раско Симић'
    print(f"v2 around '{anchor}': {repr(ctx(ft2, anchor))}")
    print("NOTE: repetition phrase NOT present in v2 -> likely reduced/eliminated")

print()
print("--- ERROR 3: 'планове' (wrong case, should be 'планови') ---")
c3v1 = ctx(ft1, 'планове')
c3v2 = ctx(ft2, 'планове')
c3v2_correct = ctx(ft2, 'планови')
print(f"v1: {repr(c3v1)}")
print(f"v2 contains 'планове' (wrong)? {'YES' if c3v2 else 'NO'}")
if c3v2:
    print(f"v2 (планове): {repr(c3v2)}")
print(f"v2 contains 'планови' (correct)? {'YES' if c3v2_correct else 'NO'}")
if c3v2_correct:
    print(f"v2 (планови): {repr(c3v2_correct)}")

print()
print("=" * 70)
print("### SUMMARY ###")
print("=" * 70)
print(f"v1: {len(segs1)} segments, {len(ft1)} chars, lang={v1['language']}({v1['language_probability']})")
print(f"v2: {len(segs2)} segments, {len(ft2)} chars, lang={v2['language']}({v2['language_probability']})")
print(f"Identical: {identical}, Changed: {len(changed)}, Unmatched v1: {unmatched_v1}")
