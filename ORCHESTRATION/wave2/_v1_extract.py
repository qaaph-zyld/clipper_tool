import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open(r'd:\1H1A1087_transcript.json', 'r', encoding='utf-8') as f:
    v1 = json.load(f)

ft = v1['full_text']
print("=== V1 FULL_TEXT LENGTH:", len(ft), "===")
print("=== V1 SEGMENTS:", len(v1['segments']), "===")
print("=== V1 LANGUAGE:", v1['language'], "PROB:", v1['language_probability'], "===")
print()
print("=== FULL TEXT ===")
print(ft)
print()
print("=== KNOWN ERROR 1: 'кре натрпање' context ===")
i = ft.find('кре натрпање')
print(repr(ft[max(0,i-80):i+80]) if i>=0 else "NOT FOUND")
print()
print("=== KNOWN ERROR 2: hallucinated repetition 'Не знам ко је то тако' ===")
i = ft.find('Не знам ко је то тако')
print(repr(ft[max(0,i-60):i+300]) if i>=0 else "NOT FOUND")
print()
print("=== KNOWN ERROR 3: 'планове' context ===")
i = ft.find('планове')
print(repr(ft[max(0,i-80):i+80]) if i>=0 else "NOT FOUND")
