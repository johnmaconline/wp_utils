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


def test_build_wp_api_pages_url_variants():
    assert (
        wp_utilities.build_wp_api_pages_url("https://example.com")
        == "https://example.com/wp-json/wp/v2/pages"
    )
    assert (
        wp_utilities.build_wp_api_pages_url("https://example.com/wp-json")
        == "https://example.com/wp-json/wp/v2/pages"
    )
    assert (
        wp_utilities.build_wp_api_pages_url("https://example.com/wp-json/wp/v2")
        == "https://example.com/wp-json/wp/v2/pages"
    )
    assert (
        wp_utilities.build_wp_api_pages_url("https://example.com/wp-json/wp/v2/pages")
        == "https://example.com/wp-json/wp/v2/pages"
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


def test_schedule_post_wp_api_dry_run_renders_markdown_and_adds_navigation_blocks(monkeypatch):
    monkeypatch.setattr(wp_utilities, "resolve_term_ids", lambda *_args, **_kwargs: [123])
    monkeypatch.setattr(
        wp_utilities,
        "fetch_latest_scheduled_date",
        lambda *_args, **_kwargs: datetime.datetime(2026, 1, 27, 8, 44),
    )
    monkeypatch.setattr(wp_utilities, "find_post_by_slug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text}</p>",
    )

    result = wp_utilities.schedule_post_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        "Body copy",
        {"title": "My Post", "categories": ["AI"], "tags": ["tag-one"]},
        dry_run=True,
    )

    assert result["action"] == "create"
    assert result["payload"]["content"].startswith("<!-- wp:paragraph -->")
    assert "<p>Body copy</p>" in result["payload"]["content"]
    assert result["payload"]["content"].count("wp:post-navigation-link") == 2


def test_schedule_post_wp_api_preserves_single_line_feeds_for_email_rendering(monkeypatch):
    monkeypatch.setattr(wp_utilities, "resolve_term_ids", lambda *_args, **_kwargs: [123])
    monkeypatch.setattr(
        wp_utilities,
        "fetch_latest_scheduled_date",
        lambda *_args, **_kwargs: datetime.datetime(2026, 1, 27, 8, 44),
    )
    monkeypatch.setattr(wp_utilities, "find_post_by_slug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda _text, **_kwargs: "<p>Line one<br />\nLine two</p><p>Next para</p>",
    )

    result = wp_utilities.schedule_post_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        "Line one\nLine two\n\nNext para",
        {"title": "My Post", "categories": ["AI"]},
        dry_run=True,
    )

    email_html = wp_utilities.build_email_preview_html(result["payload"]["content"])
    email_text = wp_utilities.build_email_preview_text(result["payload"]["content"])

    assert "<br" in email_html
    assert "Line one" in email_html
    assert "Line two" in email_html
    assert "<p>Next para</p>" in email_html
    assert "Line one\nLine two\n\nNext para" in email_text


def test_schedule_post_wp_api_dry_run_preserves_html(monkeypatch):
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
        "<p>Body copy</p>",
        {"title": "My Post", "categories": ["AI"]},
        dry_run=True,
    )

    assert result["action"] == "create"
    assert result["payload"]["content"].startswith("<!-- wp:html -->")
    assert "<p>Body copy</p>" in result["payload"]["content"]
    assert result["payload"]["content"].count("wp:post-navigation-link") == 2


def test_normalize_post_navigation_content_converts_markdown(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text.replace(chr(10) * 2, '</p><p>')}</p>",
    )
    updated, body_format = wp_utilities.normalize_post_navigation_content(
        "Line one\n\nLine two"
    )

    assert body_format == "markdown"
    assert updated.startswith("<!-- wp:paragraph -->")
    assert "<p>Line one</p>" in updated
    assert "<p>Line two</p>" in updated
    assert updated.count("wp:post-navigation-link") == 2


def test_backfill_post_navigation_dry_run(monkeypatch):
    posts = [
        {
            "id": 1,
            "status": "publish",
            "date": "2026-01-27T08:44:00",
            "link": "https://example.com/one/",
            "title": {"rendered": "One"},
        },
        {
            "id": 2,
            "status": "publish",
            "date": "2026-01-28T08:44:00",
            "link": "https://example.com/two/",
            "title": {"rendered": "Two"},
        },
    ]
    monkeypatch.setattr(wp_utilities, "fetch_wp_endpoint", lambda *_args, **_kwargs: posts)
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text.replace(chr(10) * 2, '</p><p>')}</p>",
    )
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_post_edit",
        lambda *args, **_kwargs: {
            1: {
                "id": 1,
                "status": "publish",
                "date": "2026-01-27T08:44:00",
                "link": "https://example.com/one/",
                "title": {"rendered": "One"},
                "content": {"raw": "Hello\n\nWorld"},
            },
            2: {
                "id": 2,
                "status": "publish",
                "date": "2026-01-28T08:44:00",
                "link": "https://example.com/two/",
                "title": {"rendered": "Two"},
                "content": {"raw": wp_utilities.POST_NAVIGATION_BLOCKS},
            },
        }[args[2]],
    )

    rows, stats = wp_utilities.backfill_post_navigation(
        "https://example.com",
        {"Authorization": "Basic token"},
        dry_run=True,
    )

    assert len(rows) == 2
    assert rows[0]["action"] == "would-update"
    assert rows[0]["content_format"] == "markdown"
    assert rows[1]["action"] == "already-has-navigation"
    assert stats == {
        "processed": 2,
        "already_has_navigation": 1,
        "needs_update": 1,
        "skipped": 0,
    }


def test_backfill_post_navigation_updates_post(monkeypatch):
    posts = [
        {
            "id": 3,
            "status": "publish",
            "date": "2026-01-29T08:44:00",
            "link": "https://example.com/three/",
            "title": {"rendered": "Three"},
        }
    ]
    monkeypatch.setattr(wp_utilities, "fetch_wp_endpoint", lambda *_args, **_kwargs: posts)
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text.replace(chr(10) * 2, '</p><p>')}</p>",
    )
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_post_edit",
        lambda *_args, **_kwargs: {
            "id": 3,
            "status": "publish",
            "date": "2026-01-29T08:44:00",
            "link": "https://example.com/three/",
            "title": {"rendered": "Three"},
            "content": {"raw": "Hello\n\nWorld"},
        },
    )

    captured = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return DummyResponse()

    monkeypatch.setattr(wp_utilities.requests, "post", fake_post)

    rows, stats = wp_utilities.backfill_post_navigation(
        "https://example.com",
        {"Authorization": "Basic token"},
        dry_run=False,
    )

    assert rows[0]["action"] == "updated"
    assert captured["url"] == "https://example.com/wp-json/wp/v2/posts/3"
    assert captured["json"]["content"].count("wp:post-navigation-link") == 2
    assert captured["json"]["content"].startswith("<!-- wp:paragraph -->")
    assert "<p>Hello</p>" in captured["json"]["content"]
    assert "<p>World</p>" in captured["json"]["content"]
    assert stats["needs_update"] == 1


def test_backfill_post_navigation_updates_markdown_body_with_existing_navigation(monkeypatch):
    posts = [
        {
            "id": 4,
            "status": "publish",
            "date": "2026-01-30T08:44:00",
            "link": "https://example.com/four/",
            "title": {"rendered": "Four"},
        }
    ]
    monkeypatch.setattr(wp_utilities, "fetch_wp_endpoint", lambda *_args, **_kwargs: posts)
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text.replace(chr(10) * 2, '</p><p>')}</p>",
    )
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_post_edit",
        lambda *_args, **_kwargs: {
            "id": 4,
            "status": "publish",
            "date": "2026-01-30T08:44:00",
            "link": "https://example.com/four/",
            "title": {"rendered": "Four"},
            "content": {"raw": f"Hello\n\nWorld\n\n{wp_utilities.POST_NAVIGATION_BLOCKS}"},
        },
    )

    captured = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["json"] = json
        return DummyResponse()

    monkeypatch.setattr(wp_utilities.requests, "post", fake_post)

    rows, stats = wp_utilities.backfill_post_navigation(
        "https://example.com",
        {"Authorization": "Basic token"},
        dry_run=False,
    )

    assert rows[0]["action"] == "updated"
    assert rows[0]["content_format"] == "markdown"
    assert captured["url"] == "https://example.com/wp-json/wp/v2/posts/4"
    assert captured["json"]["content"].startswith("<!-- wp:paragraph -->")
    assert "<p>Hello</p>" in captured["json"]["content"]
    assert "<p>World</p>" in captured["json"]["content"]
    assert captured["json"]["content"].count("wp:post-navigation-link") == 2
    assert stats["already_has_navigation"] == 0
    assert stats["needs_update"] == 1


def test_backfill_post_navigation_specific_post_id(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda text: f"<p>{text.replace(chr(10) * 2, '</p><p>')}</p>",
    )
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_post_edit",
        lambda *_args, **_kwargs: {
            "id": 42,
            "status": "publish",
            "date": "2026-03-10T08:44:00",
            "link": "https://example.com/forty-two/",
            "title": {"rendered": "Forty Two"},
            "content": {"raw": "First para\n\nSecond para"},
        },
    )

    def fail_fetch_endpoint(*_args, **_kwargs):
        raise AssertionError("fetch_wp_endpoint should not be used for --post-id")

    monkeypatch.setattr(wp_utilities, "fetch_wp_endpoint", fail_fetch_endpoint)

    captured = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["json"] = json
        return DummyResponse()

    monkeypatch.setattr(wp_utilities.requests, "post", fake_post)

    rows, stats = wp_utilities.backfill_post_navigation(
        "https://example.com",
        {"Authorization": "Basic token"},
        dry_run=False,
        post_id=42,
    )

    assert len(rows) == 1
    assert rows[0]["id"] == 42
    assert rows[0]["action"] == "updated"
    assert rows[0]["content_format"] == "markdown"
    assert captured["url"] == "https://example.com/wp-json/wp/v2/posts/42"
    assert captured["json"]["content"].startswith("<!-- wp:paragraph -->")
    assert "<p>First para</p>" in captured["json"]["content"]
    assert stats["processed"] == 1
    assert stats["needs_update"] == 1


def test_update_page_wp_api_dry_run(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_page_edit",
        lambda *_args, **_kwargs: {
            "id": 55217,
            "status": "publish",
            "link": "https://example.com/how-to-talk-to-ai/",
            "title": {"rendered": "How to Talk to AI"},
            "content": {"raw": "<p>old</p>"},
        },
    )

    row = wp_utilities.update_page_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        55217,
        "<p>new</p>",
        dry_run=True,
    )

    assert row["operation"] == "update-page"
    assert row["id"] == 55217
    assert row["action"] == "would-update"
    assert row["content_changed"] == "True"
    assert row["dry_run"] == "True"


def test_prepare_wp_page_content_wraps_html_block():
    wrapped = wp_utilities.prepare_wp_page_content("<div>hello</div>")
    assert wrapped.startswith("<!-- wp:html -->")
    assert "<div>hello</div>" in wrapped
    assert wrapped.endswith("<!-- /wp:html -->")


def test_prepare_wp_html_block_content_preserves_existing_gutenberg_block():
    content = "<!-- wp:paragraph --><p>hello</p><!-- /wp:paragraph -->"
    assert wp_utilities.prepare_wp_html_block_content(content) == content


def test_build_email_preview_html_strips_gutenberg_comments():
    content = "<!-- wp:paragraph --><p>Alpha</p><!-- /wp:paragraph -->"
    assert wp_utilities.build_email_preview_html(content) == "<p>Alpha</p>"


def test_build_email_preview_text_preserves_line_feeds_and_paragraphs():
    content = (
        "<!-- wp:paragraph --><p>Line one<br />Line two</p><!-- /wp:paragraph -->"
        "<!-- wp:paragraph --><p>Next para</p><!-- /wp:paragraph -->"
    )

    assert wp_utilities.build_email_preview_text(content) == "Line one\nLine two\n\nNext para"


def test_markdown_to_gutenberg_blocks_serializes_common_native_blocks(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda _text, **_kwargs: (
            "<h2>Heading</h2>"
            "<p>Paragraph with <strong>bold</strong> text.</p>"
            "<ul><li>One</li><li>Two</li></ul>"
            '<blockquote><p>Quoted</p></blockquote>'
            '<pre><code class="language-python">print(\'hi\')</code></pre>'
            "<hr />"
        ),
    )
    blocks = wp_utilities.markdown_to_gutenberg_blocks(
        "## Heading\n\nParagraph with **bold** text.\n\n- One\n- Two\n\n> Quoted\n\n```python\nprint('hi')\n```\n\n---\n"
    )

    assert "<!-- wp:heading -->" in blocks
    assert "<h2>Heading</h2>" in blocks
    assert "<!-- wp:paragraph -->" in blocks
    assert "<strong>bold</strong>" in blocks
    assert "<!-- wp:list -->" in blocks
    assert '<ul class="wp-block-list">' in blocks
    assert "<!-- wp:quote -->" in blocks
    assert 'class="wp-block-quote"' in blocks
    assert "<!-- wp:code -->" in blocks
    assert 'class="wp-block-code"' in blocks
    assert "<!-- wp:separator -->" in blocks


def test_markdown_to_gutenberg_blocks_converts_markdown_image_to_image_block(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda _text, **_kwargs: '<p><img src="https://example.com/image.png" alt="Alt text" /></p>',
    )
    blocks = wp_utilities.markdown_to_gutenberg_blocks("![Alt text](https://example.com/image.png)")

    assert blocks.startswith("<!-- wp:image -->")
    assert 'class="wp-block-image"' in blocks
    assert 'src="https://example.com/image.png"' in blocks
    assert 'alt="Alt text"' in blocks


def test_render_markdown_html_enables_nl2br(monkeypatch):
    captured = {}

    def fake_markdown(text, extensions=None):
        captured["text"] = text
        captured["extensions"] = extensions
        return "<p>ok</p>"

    monkeypatch.setattr(wp_utilities, "render_markdown", fake_markdown)

    rendered = wp_utilities._render_markdown_html("Line one\nLine two")

    assert rendered == "<p>ok</p>"
    assert captured["text"] == "Line one\nLine two"
    assert "nl2br" in captured["extensions"]


def test_markdown_to_gutenberg_blocks_renders_single_line_feeds_as_breaks(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "render_markdown",
        lambda _text, **_kwargs: "<p>Line one<br />\nLine two</p><p>Next para</p>",
    )
    blocks = wp_utilities.markdown_to_gutenberg_blocks("Line one\nLine two\n\nNext para")

    assert "<!-- wp:paragraph -->" in blocks
    assert "<p>Line one<br />\nLine two</p>" in blocks or "<p>Line one<br/>\nLine two</p>" in blocks
    assert blocks.count("<!-- wp:paragraph -->") == 2


def test_update_page_wp_api_skips_when_unchanged(monkeypatch):
    prepared = wp_utilities.prepare_wp_page_content("<p>same</p>")
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_page_edit",
        lambda *_args, **_kwargs: {
            "id": 55217,
            "status": "publish",
            "link": "https://example.com/how-to-talk-to-ai/",
            "title": {"rendered": "How to Talk to AI"},
            "content": {"raw": prepared},
        },
    )

    row = wp_utilities.update_page_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        55217,
        "<p>same</p>",
        dry_run=False,
    )

    assert row["action"] == "skipped-no-change"
    assert row["content_changed"] == "False"


def test_update_page_wp_api_updates_page(monkeypatch):
    monkeypatch.setattr(
        wp_utilities,
        "fetch_wp_page_edit",
        lambda *_args, **_kwargs: {
            "id": 55217,
            "status": "publish",
            "link": "https://example.com/how-to-talk-to-ai/",
            "title": {"rendered": "How to Talk to AI"},
            "content": {"raw": "<p>old</p>"},
        },
    )

    captured = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json():
            return {
                "id": 55217,
                "status": "publish",
                "link": "https://example.com/how-to-talk-to-ai/",
            }

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return DummyResponse()

    monkeypatch.setattr(wp_utilities.requests, "post", fake_post)

    row = wp_utilities.update_page_wp_api(
        "https://example.com",
        {"Authorization": "Basic token"},
        55217,
        "<p>new</p>",
        dry_run=False,
    )

    assert row["action"] == "updated"
    assert captured["url"] == "https://example.com/wp-json/wp/v2/pages/55217"
    assert captured["json"] == {"content": wp_utilities.prepare_wp_page_content("<p>new</p>")}


def test_sanitize_filename():
    assert wp_utilities.sanitize_filename("Hello, World!") == "Hello-_World-"


def test_extract_date_from_filename():
    date_val = wp_utilities.extract_date_from_filename("foo-bar-2025-12-31.txt")
    assert isinstance(date_val, datetime.date)
    assert date_val.isoformat() == "2025-12-31"
