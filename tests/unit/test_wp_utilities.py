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

def test_build_wp_api_base_and_plugins_url():
    assert wp_utilities.build_wp_api_base("https://example.com") == "https://example.com"
    assert (
        wp_utilities.build_wp_api_base("https://example.com/wp-json/wp/v2/posts")
        == "https://example.com"
    )
    assert wp_utilities.build_wp_api_base("example.com") == "https://example.com"
    assert (
        wp_utilities.build_wp_api_plugins_url("https://example.com")
        == "https://example.com/wp-json/wp/v2/plugins"
    )


def test_normalize_users_includes_permissions():
    data = [{
        'id': 1,
        'name': 'User One',
        'slug': 'user-one',
        'link': 'https://example.com/author/user-one/',
        'registered_date': '2026-01-01T00:00:00',
        'roles': ['administrator'],
        'capabilities': {'edit_posts': True, 'delete_posts': False}
    }]
    rows = wp_utilities.normalize_wp_rows('get-users', data)
    assert rows[0]['registered_date'] == '2026-01-01T00:00:00'
    assert rows[0]['roles'] == 'administrator'
    assert 'edit_posts' in rows[0]['capabilities']


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


def test_ensure_post_navigation_blocks_appends_once():
    content = "Hello world"
    updated = wp_utilities.ensure_post_navigation_blocks(content)
    assert updated.startswith("Hello world")
    assert updated.count("wp:post-navigation-link") == 2
    assert '"type":"previous"' in updated
    assert '"type":"next"' in updated


def test_ensure_post_navigation_blocks_is_idempotent():
    content = "Hello world\n\n" + wp_utilities.POST_NAVIGATION_BLOCKS
    updated = wp_utilities.ensure_post_navigation_blocks(content)
    assert updated == content


def test_schedule_post_wp_api_dry_run_adds_navigation_blocks(monkeypatch):
    monkeypatch.setattr(wp_utilities, "resolve_term_ids", lambda *_args, **_kwargs: [123])
    monkeypatch.setattr(
        wp_utilities,
        "fetch_latest_scheduled_date",
        lambda *_args, **_kwargs: datetime.datetime(2026, 1, 27, 8, 44),
    )
    monkeypatch.setattr(wp_utilities, "find_post_by_slug", lambda *_args, **_kwargs: None)

    result = wp_utilities.schedule_post_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        "Body copy",
        {"title": "My Post", "categories": ["AI"], "tags": ["tag-one"]},
        dry_run=True,
    )

    assert result["action"] == "create"
    assert result["payload"]["content"].startswith("Body copy")
    assert result["payload"]["content"].count("wp:post-navigation-link") == 2


def test_sanitize_filename():
    assert wp_utilities.sanitize_filename("Hello, World!") == "Hello-_World-"


def test_extract_date_from_filename():
    date_val = wp_utilities.extract_date_from_filename("foo-bar-2025-12-31.txt")
    assert isinstance(date_val, datetime.date)
    assert date_val.isoformat() == "2025-12-31"
