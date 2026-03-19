from datetime import date, time as dtime

import post


def test_markdown_to_text():
    text = post.markdown_to_text("# Title\n\nHello **world**")
    assert "Title" in text
    assert "Hello" in text
    assert "world" in text


def test_build_auth_header():
    header = post.build_auth_header("user", "pass")
    assert header["Authorization"].startswith("Basic ")
    assert header["Content-Type"] == "application/json"


def test_local_to_utc():
    dt = post.local_to_utc(date(2026, 1, 27), dtime(hour=8, minute=44))
    assert dt.hour == 13
    assert dt.minute == 44
    assert dt.tzinfo is not None


def test_schedule_post_converts_markdown_to_native_gutenberg_blocks(monkeypatch):
    captured = {}

    class DummyResponse:
        status_code = 201

        @staticmethod
        def json():
            return {"link": "https://example.com/scheduled-post/"}

    def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return DummyResponse()

    monkeypatch.setattr(post.requests, "post", fake_post)

    link = post.schedule_post(
        "My Post",
        "Body copy",
        post.local_to_utc(date(2026, 1, 27), dtime(hour=8, minute=44)),
        excerpt="Short summary",
    )

    assert link == "https://example.com/scheduled-post/"
    assert captured["json"]["content"].startswith("<!-- wp:paragraph -->")
    assert "<p>Body copy</p>" in captured["json"]["content"]
    assert captured["json"]["excerpt"] == "Short summary"
