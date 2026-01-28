import datetime

import wp_utilities


def test_valid_filename():
    url = "https://example.com/path/My%20File-Name.jpg?size=large"
    assert wp_utilities.valid_filename(url) == "My_File_Name.jpg"


def test_build_wp_api_posts_url_variants():
    assert (
        wp_utilities.build_wp_api_posts_url("https://example.com")
        == "https://example.com/wp-json/wp/v2/posts"
    )
    assert (
        wp_utilities.build_wp_api_posts_url("https://example.com/wp-json")
        == "https://example.com/wp-json/wp/v2/posts"
    )
    assert (
        wp_utilities.build_wp_api_posts_url("https://example.com/wp-json/wp/v2")
        == "https://example.com/wp-json/wp/v2/posts"
    )
    assert (
        wp_utilities.build_wp_api_posts_url("https://example.com/wp-json/wp/v2/posts")
        == "https://example.com/wp-json/wp/v2/posts"
    )


def test_format_wp_api_date():
    assert wp_utilities.format_wp_api_date("2026-01-27T08:44:00") == "2026-01-27"
    assert wp_utilities.format_wp_api_date("2026-01-27T13:44:00Z") == "2026-01-27"
    assert wp_utilities.format_wp_api_date("not-a-date") == "unknown-date"


def test_extract_text_from_html(monkeypatch, tmp_path):
    def fake_download_image(url, outdir):
        return "images/fake.png"

    monkeypatch.setattr(wp_utilities, "download_image", fake_download_image)

    html = (
        "<h1>Title</h1>"
        "<p>Hello world</p>"
        "<ul><li>One</li></ul>"
        "<ol><li>A</li><li>B</li></ol>"
        "<pre><code>print('hi')</code></pre>"
        "<figure class='wp-block-image'><img src='https://example.com/img.png'></figure>"
    )
    content = wp_utilities.extract_text_from_html(html, str(tmp_path))
    assert "# Title" in content
    assert "Hello world" in content
    assert "* One" in content
    assert "1. A" in content
    assert "2. B" in content
    assert "```" in content
    assert "[image: images/fake.png]" in content


def test_sanitize_filename():
    assert wp_utilities.sanitize_filename("Hello, World!") == "Hello-_World-"


def test_extract_date_from_filename():
    date_val = wp_utilities.extract_date_from_filename("foo-bar-2025-12-31.txt")
    assert isinstance(date_val, datetime.date)
    assert date_val.isoformat() == "2025-12-31"
