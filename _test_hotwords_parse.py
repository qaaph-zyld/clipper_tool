import sys
from pathlib import Path
from transcribe_sr import load_hotwords_from_file

p = Path("hotwords_sr.txt")

all_words = load_hotwords_from_file(p)
print("ALL:", all_words)
assert "[boxing]" not in all_words, "section header leaked"
assert "[farming]" not in all_words, "section header leaked"
assert "[general]" not in all_words, "section header leaked"
assert "#" not in all_words, "comment leaked"
assert "бокс" in all_words
assert "подкаст" in all_words

boxing = load_hotwords_from_file(p, topic="boxing")
print("BOXING:", boxing)
assert "бокс" in boxing
assert "фарма" not in boxing, "farming word leaked into boxing"
assert "подкаст" not in boxing, "general word leaked into boxing"

farming = load_hotwords_from_file(p, topic="farming")
print("FARMING:", farming)
assert "фарма" in farming
assert "бокс" not in farming

general = load_hotwords_from_file(p, topic="general")
print("GENERAL:", general)
assert "подкаст" in general
assert "бокс" not in general

missing = load_hotwords_from_file(p, topic="nonexistent")
print("MISSING:", repr(missing))
assert missing == ""

print("ALL TESTS PASSED")
