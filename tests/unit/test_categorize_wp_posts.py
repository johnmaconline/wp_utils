import base64

import pytest

import categorize_wp_posts as cwp


class DummyResponse:
    def __init__(self, output_text):
        self.output_text = output_text


class DummyClient:
    class responses:
        @staticmethod
        def create(**_kwargs):
            return DummyResponse('{"add": true, "confidence": 0.9, "reason": "mentions AI"}')


class DummyBadClient:
    class responses:
        @staticmethod
        def create(**_kwargs):
            return DummyResponse('not json')



def test_build_wp_api_base_and_endpoints():
    base = cwp.build_wp_api_base("https://example.com/wp-json/wp/v2/posts")
    assert base == "https://example.com"
    posts_url, categories_url = cwp.build_wp_endpoints("https://example.com")
    assert posts_url.endswith("/wp-json/wp/v2/posts")
    assert categories_url.endswith("/wp-json/wp/v2/categories")


def test_build_auth_header():
    header = cwp.build_auth_header("user", "pass")
    expected = base64.b64encode(b"user:pass").decode("utf-8")
    assert header == {"Authorization": f"Basic {expected}"}


def test_truncate_text():
    assert cwp.truncate_text("short", 10) == "short"
    assert cwp.truncate_text("hello world", 5) == "hello..."


def test_safe_json_loads():
    assert cwp.safe_json_loads('{"a": 1}') == {"a": 1}
    assert cwp.safe_json_loads("not json") is None


def test_html_to_text():
    text = cwp.html_to_text("<p>Hello <b>world</b></p>")
    assert "Hello" in text
    assert "world" in text


def test_classify_post_parses_json():
    result = cwp.classify_post(
        DummyClient(),
        "gpt-4.1",
        "AI",
        "Title",
        "<p>Excerpt</p>",
        "<p>Content</p>",
        1000,
    )
    assert result["add"] is True
    assert result["confidence"] == 0.9


def test_classify_post_invalid_json_raises():
    with pytest.raises(cwp.APIError):
        cwp.classify_post(
            DummyBadClient(),
            "gpt-4.1",
            "AI",
            "Title",
            "<p>Excerpt</p>",
            "<p>Content</p>",
            1000,
        )
