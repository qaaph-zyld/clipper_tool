import pytest
import math
from unittest.mock import patch, MagicMock
from main import (
    _score_hook_words,
    _sentence_boundary_bonus,
    _sentiment_score,
    _keyword_boost,
    _scene_cut_density,
    find_clips,
)


class TestScoreHookWords:
    def test_no_matches_returns_1(self):
        assert _score_hook_words("hello world") == 1.0

    def test_single_match(self):
        assert _score_hook_words("nobody knows") == 1.5

    def test_multiple_matches(self):
        result = _score_hook_words("nobody knows the secret")
        assert result == 2.0

    def test_cap_at_3(self):
        text = "nobody secret hidden revealed shocking incredible unbelievable"
        assert _score_hook_words(text) == 3.0

    def test_case_insensitive(self):
        assert _score_hook_words("NOBODY knows") == 1.5


class TestSentenceBoundaryBonus:
    def test_empty_window(self):
        words = []
        assert _sentence_boundary_bonus(words, 0, 10) == 0.5

    def test_capital_start_punct_end(self):
        words = [
            {"start": 0, "end": 1, "word": "Hello"},
            {"start": 1, "end": 2, "word": "world!"},
        ]
        bonus = _sentence_boundary_bonus(words, 0, 2)
        assert bonus == 1.8  # 1.0 + 0.3 + 0.5

    def test_no_capital_no_punct(self):
        words = [
            {"start": 0, "end": 1, "word": "hello"},
            {"start": 1, "end": 2, "word": "world"},
        ]
        bonus = _sentence_boundary_bonus(words, 0, 2)
        assert bonus == 1.0


class TestSentimentScore:
    def test_neutral_returns_1(self):
        assert _sentiment_score("the table is there") == 1.0

    def test_positive_words(self):
        result = _sentiment_score("this is amazing and great")
        assert result > 1.0
        assert result <= 1.2

    def test_negative_words(self):
        result = _sentiment_score("this is terrible and awful")
        assert result > 1.0
        assert result <= 1.2

    def test_cap_at_1_2(self):
        text = "good great amazing love best awesome beautiful happy perfect incredible"
        assert _sentiment_score(text) == 1.2


class TestKeywordBoost:
    def test_no_keywords_returns_1(self):
        # Reset global
        import main
        main.KEYWORD_BOOST_LIST = set()
        assert _keyword_boost("hello world") == 1.0

    def test_with_keywords(self):
        import main
        main.KEYWORD_BOOST_LIST = {"drill", "trap", "serbian"}
        result = _keyword_boost("this is a drill track")
        assert result > 1.0
        assert result <= 1.5

    def test_cap_at_1_5(self):
        import main
        main.KEYWORD_BOOST_LIST = {"a", "b", "c", "d", "e"}
        result = _keyword_boost("a b c d e")
        assert result == 1.5

    def teardown_method(self):
        import main
        main.KEYWORD_BOOST_LIST = set()


class TestSceneCutDensity:
    def test_no_cuts(self):
        assert _scene_cut_density([], 0, 30) == 0.8

    def test_one_cut(self):
        assert _scene_cut_density([15.0], 0, 30) == pytest.approx(0.95)

    def test_multiple_cuts(self):
        cuts = [5.0, 10.0, 15.0, 20.0]
        assert _scene_cut_density(cuts, 0, 30) == 1.3  # capped

    def test_cuts_outside_range(self):
        assert _scene_cut_density([100.0], 0, 30) == 0.8


class TestFindClips:
    def _make_result(self, segments):
        """Build a WhisperX-like result dict from segment specs."""
        result_segments = []
        for seg in segments:
            words = []
            for i, (w_start, w_end, w_text) in enumerate(seg["words"]):
                words.append({"start": w_start, "end": w_end, "word": w_text})
            result_segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "words": words,
            })
        return {"segments": result_segments, "language": "en"}

    def test_finds_clips_from_mock_data(self):
        # Create 60 seconds of word-level data
        words = []
        for i in range(120):
            t = i * 0.5
            words.append((t, t + 0.4, f"word{i}"))
        result = self._make_result([{
            "start": 0,
            "end": 60,
            "text": " ".join(w[2] for w in words),
            "words": words,
        }])

        clips = find_clips(result, num_clips=3, min_duration=15.0, max_duration=30.0)
        assert len(clips) <= 3
        assert len(clips) > 0
        for clip in clips:
            assert clip["start"] < clip["end"]
            assert clip["score"] > 0

    def test_no_overlapping_clips(self):
        words = []
        for i in range(200):
            t = i * 0.5
            words.append((t, t + 0.4, f"word{i}"))
        result = self._make_result([{
            "start": 0,
            "end": 100,
            "text": " ".join(w[2] for w in words),
            "words": words,
        }])

        clips = find_clips(result, num_clips=5, min_duration=15.0, max_duration=30.0)
        for i in range(len(clips)):
            for j in range(i + 1, len(clips)):
                assert clips[i]["end"] <= clips[j]["start"] or clips[i]["start"] >= clips[j]["end"]

    def test_empty_result_raises(self):
        with pytest.raises(ValueError):
            find_clips({"segments": [], "language": "en"})

    def test_segment_level_timestamps(self):
        # No word-level timestamps, only segment-level
        result = {
            "segments": [
                {"start": 0, "end": 20, "text": "This is a test segment with some words in it."},
                {"start": 20, "end": 40, "text": "Another segment here with more words to test."},
                {"start": 40, "end": 60, "text": "Final segment with enough words for a clip."},
            ],
            "language": "en",
        }
        clips = find_clips(result, num_clips=2, min_duration=15.0, max_duration=30.0)
        assert len(clips) > 0
