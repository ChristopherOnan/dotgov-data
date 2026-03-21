"""
Tests for the Flask upload server.
"""

import io
import os
import sys

os.environ["MOCK_MODE"] = "true"
os.environ["IG_USER_ID"] = "test_ig_user_123"
os.environ["ACCESS_TOKEN"] = "test_access_token"
os.environ["ANTHROPIC_API_KEY"] = "test_anthropic_key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import upload_server


@pytest.fixture
def client():
    """Create a test client with auth disabled."""
    upload_server.UPLOAD_API_KEY = ""  # disable auth for tests
    upload_server.AUTO_POST = False
    upload_server.app.config["TESTING"] = True
    with upload_server.app.test_client() as c:
        yield c


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"


class TestUploadEndpoint:
    def test_upload_no_file(self, client):
        resp = client.post("/upload")
        assert resp.status_code == 400

    def test_upload_valid_image(self, client):
        data = {"file": (io.BytesIO(b"fake image data"), "test.jpg")}
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["saved"] is True
        assert result["media_type"] == "image"

    def test_upload_valid_video(self, client):
        data = {"file": (io.BytesIO(b"fake video data"), "test.mp4")}
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["media_type"] == "video"

    def test_upload_unsupported_type(self, client):
        data = {"file": (io.BytesIO(b"not media"), "test.txt")}
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_upload_empty_filename(self, client):
        data = {"file": (io.BytesIO(b"data"), "")}
        resp = client.post("/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400


class TestInboxEndpoint:
    def test_list_inbox(self, client):
        resp = client.get("/inbox")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "count" in data
        assert "files" in data


class TestBatchUpload:
    def test_batch_no_files(self, client):
        resp = client.post("/upload/batch")
        assert resp.status_code == 400

    def test_batch_multiple_files(self, client):
        data = {
            "files": [
                (io.BytesIO(b"img1"), "photo1.jpg"),
                (io.BytesIO(b"img2"), "photo2.png"),
            ]
        }
        resp = client.post("/upload/batch", data=data, content_type="multipart/form-data")
        assert resp.status_code == 201
        result = resp.get_json()
        assert result["uploaded"] == 2


class TestAuth:
    def test_auth_required_when_key_set(self):
        upload_server.UPLOAD_API_KEY = "test_secret_key"
        upload_server.app.config["TESTING"] = True
        with upload_server.app.test_client() as c:
            data = {"file": (io.BytesIO(b"data"), "test.jpg")}
            resp = c.post("/upload", data=data, content_type="multipart/form-data")
            assert resp.status_code == 401

    def test_auth_passes_with_correct_key(self):
        upload_server.UPLOAD_API_KEY = "test_secret_key"
        upload_server.app.config["TESTING"] = True
        with upload_server.app.test_client() as c:
            data = {"file": (io.BytesIO(b"data"), "test.jpg")}
            resp = c.post(
                "/upload",
                data=data,
                headers={"X-API-Key": "test_secret_key"},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 201
