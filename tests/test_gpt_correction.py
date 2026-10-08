import pytest
import re
from unittest.mock import patch, MagicMock
from main import correct_segments_with_gpt4o


class TestCorrectSegmentsWithGpt4o:
    def test_no_api_key_returns_original(self):
        with patch("os.getenv", return_value=None):
            segments = [{"text": "hello world"}, {"text": "test"}]
            result = correct_segments_with_gpt4o(segments)
            assert result == segments

    def test_corrects_segments(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "[0] Hello world!\n[1] This is a test."
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_client.api_key = "fake-key"

        segments = [
            {"text": "helo wrld"},
            {"text": "tis is a tst"},
        ]

        with patch("os.getenv", return_value="fake-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                with patch("dotenv.load_dotenv"):
                    result = correct_segments_with_gpt4o(segments)

        assert result[0]["text"] == "Hello world!"
        assert result[1]["text"] == "This is a test."

    def test_api_error_keeps_original(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        mock_client.api_key = "fake-key"

        segments = [{"text": "original text"}]

        with patch("os.getenv", return_value="fake-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                with patch("dotenv.load_dotenv"):
                    result = correct_segments_with_gpt4o(segments)

        assert result[0]["text"] == "original text"

    def test_batch_processing(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "[0] Corrected one\n[1] Corrected two\n[2] Corrected three\n[3] Corrected four"
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_client.api_key = "fake-key"

        segments = [
            {"text": f"segment {i}"} for i in range(8)
        ]

        with patch("os.getenv", return_value="fake-key"):
            with patch("openai.OpenAI", return_value=mock_client):
                with patch("dotenv.load_dotenv"):
                    result = correct_segments_with_gpt4o(segments, batch_size=4)

        # Should have made 2 API calls for 8 segments with batch_size=4
        assert mock_client.chat.completions.create.call_count == 2
        assert len(result) == 8
