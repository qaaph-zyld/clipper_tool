import pytest
from main import (
    _sec_to_ass,
    _escape_ass,
    build_ass_captions,
    ASS_HEADER,
)


class TestSecToAss:
    def test_zero(self):
        assert _sec_to_ass(0.0) == "0:00:00.00"

    def test_one_minute(self):
        assert _sec_to_ass(60.0) == "0:01:00.00"

    def test_with_decimals(self):
        assert _sec_to_ass(36.5) == "0:00:36.50"

    def test_over_hour(self):
        assert _sec_to_ass(3723.0) == "1:02:03.00"


class TestEscapeAss:
    def test_plain_text(self):
        assert _escape_ass("hello world") == "hello world"

    def test_backslash(self):
        assert _escape_ass("test\\path") == "test\\\\path"

    def test_braces(self):
        assert _escape_ass("{bold}") == "\\{bold\\}"


class TestBuildAssCaptions:
    def _make_result(self, words_list):
        """Build a result with word-level timestamps."""
        words = []
        for i, (start, end, text) in enumerate(words_list):
            words.append({"start": start, "end": end, "word": text})
        return {
            "segments": [{
                "start": words_list[0][0] if words_list else 0,
                "end": words_list[-1][1] if words_list else 0,
                "text": " ".join(w[2] for w in words_list),
                "words": words,
            }],
            "language": "en",
        }

    def test_empty_result_returns_header(self):
        result = {"segments": [], "language": "en"}
        ass = build_ass_captions(result)
        assert ass == ASS_HEADER

    def test_basic_captions(self):
        result = self._make_result([
            (0.0, 0.5, "Hello"),
            (0.5, 1.0, "world"),
            (1.0, 1.5, "this"),
            (1.5, 2.0, "is"),
            (2.0, 2.5, "a"),
            (2.5, 3.0, "test"),
            (3.0, 3.5, "of"),
            (3.5, 4.0, "captions"),
        ])
        ass = build_ass_captions(result)
        assert "Dialogue:" in ass
        assert "Hello" in ass
        assert "captions" in ass

    def test_clip_range_filter(self):
        result = self._make_result([
            (0.0, 0.5, "outside"),
            (10.0, 10.5, "inside"),
            (11.0, 11.5, "clip"),
            (20.0, 20.5, "outside"),
        ])
        ass = build_ass_captions(result, clip_start=10.0, clip_end=12.0)
        assert "inside" in ass
        assert "clip" in ass
        assert "outside" not in ass

    def test_time_offset(self):
        result = self._make_result([
            (30.0, 30.5, "word1"),
            (31.0, 31.5, "word2"),
        ])
        ass = build_ass_captions(result, clip_start=30.0, clip_end=32.0)
        # Times should be offset by clip_start (30s)
        assert "0:00:00.00" in ass  # 30 - 30 = 0
        assert "0:00:01.50" in ass  # 31.5 - 30 = 1.50 (end of word2)

    def test_segment_level_fallback(self):
        result = {
            "segments": [
                {"start": 0, "end": 5, "text": "A segment without words"},
            ],
            "language": "en",
        }
        ass = build_ass_captions(result)
        assert "Dialogue:" in ass
        assert "A segment without words" in ass
