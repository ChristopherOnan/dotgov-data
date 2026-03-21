"""
Tests for Google Photos integration (mock mode).
"""

import os
import sys

os.environ["MOCK_MODE"] = "true"
os.environ["IG_USER_ID"] = "test_ig_user_123"
os.environ["ACCESS_TOKEN"] = "test_access_token"
os.environ["ANTHROPIC_API_KEY"] = "test_anthropic_key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import google_photos


class TestGooglePhotosMock:
    def test_list_media_mock(self):
        token = {"access_token": "mock"}
        result = google_photos.list_media(token)
        assert "mediaItems" in result
        assert len(result["mediaItems"]) == 2

    def test_search_media_mock(self):
        token = {"access_token": "mock"}
        result = google_photos.search_media(token)
        assert "mediaItems" in result

    def test_list_albums_mock(self):
        token = {"access_token": "mock"}
        result = google_photos.list_albums(token)
        assert "albums" in result
        assert result["albums"][0]["title"] == "Camera Roll"

    def test_get_album_media_mock(self):
        token = {"access_token": "mock"}
        result = google_photos.get_album_media(token, "album_1")
        assert "mediaItems" in result

    def test_download_media_item_mock(self, tmp_path):
        token = {"access_token": "mock"}
        item = {
            "id": "test_123",
            "filename": "test_photo.jpg",
            "mimeType": "image/jpeg",
            "baseUrl": "https://mock.photos/test",
        }
        path = google_photos.download_media_item(token, item, dest_dir=tmp_path)
        assert path.exists()
        assert path.name == "test_photo.jpg"

    def test_sync_recent_mock(self, tmp_path):
        token = {"access_token": "mock"}
        # Temporarily override MEDIA_INBOX
        original = google_photos.MEDIA_INBOX
        google_photos.MEDIA_INBOX = tmp_path
        try:
            files = google_photos.sync_recent(token, hours=24)
            assert len(files) == 2
            assert all(f.exists() for f in files)
        finally:
            google_photos.MEDIA_INBOX = original
