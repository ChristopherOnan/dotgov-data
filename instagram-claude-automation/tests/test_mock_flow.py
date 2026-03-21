"""
Test stubs using mock mode — verifies the full flow without real API calls.

Run: python -m pytest tests/ -v
"""

import os
import sys
from unittest.mock import patch

import pytest

# Ensure mock mode is set BEFORE importing modules that read config
os.environ["MOCK_MODE"] = "true"
os.environ["IG_USER_ID"] = "test_ig_user_123"
os.environ["ACCESS_TOKEN"] = "test_access_token"
os.environ["ANTHROPIC_API_KEY"] = "test_anthropic_key"

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import utils
import claude_helper
import instagram_poster


class TestConfig:
    def test_mock_mode_enabled(self):
        assert config.MOCK_MODE is True

    def test_base_url_format(self):
        assert config.BASE_URL.startswith("https://graph.facebook.com/v")

    def test_constants(self):
        assert config.MAX_CAPTION_LENGTH == 2200
        assert config.MAX_HASHTAGS == 30


class TestUtils:
    def test_validate_caption_short(self):
        result = utils.validate_caption("Hello world")
        assert result == "Hello world"

    def test_validate_caption_truncates(self):
        long = "x" * 3000
        result = utils.validate_caption(long)
        assert len(result) == config.MAX_CAPTION_LENGTH

    def test_validate_url_valid(self):
        assert utils.validate_url("https://example.com/video.mp4") is True

    def test_validate_url_invalid(self):
        assert utils.validate_url("not-a-url") is False

    def test_graph_get_mock(self):
        result = utils.graph_get("test_endpoint")
        assert result["id"] == "mock_id"

    def test_graph_post_mock(self):
        result = utils.graph_post("test_endpoint", data={"key": "value"})
        assert "id" in result


class TestClaudeHelper:
    def test_generate_caption_mock(self):
        result = claude_helper.generate_caption(topic="test")
        assert "[MOCK]" in result

    def test_generate_hashtags_mock(self):
        result = claude_helper.generate_hashtags(topic="test")
        assert "[MOCK]" in result

    def test_generate_reel_script_mock(self):
        result = claude_helper.generate_reel_script(topic="test")
        assert "[MOCK]" in result

    def test_generate_story_text_mock(self):
        result = claude_helper.generate_story_text(topic="test")
        assert "[MOCK]" in result

    def test_generate_alt_text_mock(self):
        result = claude_helper.generate_alt_text(topic="test")
        assert "[MOCK]" in result

    def test_interactive_mock(self):
        result = claude_helper.interactive_prompt("Hello")
        assert "[MOCK]" in result


class TestInstagramPoster:
    def test_create_reel_container_mock(self):
        container_id = instagram_poster.create_reel_container(
            video_url="https://example.com/video.mp4",
            caption="Test caption",
        )
        assert container_id is not None

    def test_create_story_container_mock(self):
        container_id = instagram_poster.create_story_container(
            media_url="https://example.com/photo.jpg",
            media_type_hint="image",
        )
        assert container_id is not None

    def test_publish_container_mock(self):
        media_id = instagram_poster.publish_container("mock_container_123")
        assert media_id is not None

    def test_post_reel_end_to_end_mock(self):
        media_id = instagram_poster.post_reel(
            video_url="https://example.com/video.mp4",
            caption="Full flow test",
        )
        assert media_id is not None

    def test_post_story_end_to_end_mock(self):
        media_id = instagram_poster.post_story(
            media_url="https://example.com/photo.jpg",
            media_type_hint="image",
        )
        assert media_id is not None

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            instagram_poster.create_reel_container(
                video_url="not-a-url",
                caption="Test",
            )


class TestCaptionValidation:
    def test_caption_under_limit(self):
        caption = "Short caption"
        result = utils.validate_caption(caption)
        assert result == caption

    def test_caption_at_limit(self):
        caption = "x" * 2200
        result = utils.validate_caption(caption)
        assert len(result) == 2200

    def test_caption_over_limit_truncated(self):
        caption = "x" * 2500
        result = utils.validate_caption(caption)
        assert len(result) == 2200
