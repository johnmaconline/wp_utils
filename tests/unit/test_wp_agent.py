from pathlib import Path

import wp_agent


def test_handle_args_accepts_unschedule(monkeypatch):
    monkeypatch.setattr(wp_agent.wpu, "load_dotenv", lambda: None)
    monkeypatch.setattr(wp_agent, "_ensure_stdout_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        wp_agent.sys,
        "argv",
        ["wp_agent.py", "--unschedule", "03-19-2026", "--dry-run"],
    )

    args = wp_agent.handle_args()

    assert args.unschedule == "03-19-2026"
    assert args.dry_run is True


def test_run_agentic_workflow_unschedule_mode(monkeypatch, tmp_path, capsys):
    captured = {}

    monkeypatch.setattr(wp_agent, "_init_google_client", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(wp_agent.wpu, "build_auth_header", lambda *_args, **_kwargs: {"Authorization": "Basic token"})
    monkeypatch.setattr(wp_agent.wpu, "render_ascii_table", lambda rows: f"rows={len(rows)}")

    def fake_unschedule(url, headers, target, dry_run=False):
        captured["url"] = url
        captured["headers"] = headers
        captured["target"] = target
        captured["dry_run"] = dry_run
        return [
            {
                "operation": "unschedule",
                "id": 99,
                "title": "Future Post",
                "status": "future",
                "date": "2026-03-19",
                "action": "would-update",
                "dry_run": "True",
                "link": "https://example.com/future-post/",
            }
        ]

    monkeypatch.setattr(wp_agent.wpu, "unschedule_posts_wp_api", fake_unschedule)

    args = type(
        "Args",
        (),
        {
            "unschedule": "03-19-2026",
            "wp_username": "user",
            "wp_app_password": "pass",
            "url": "https://example.com",
            "dry_run": True,
            "outdir": str(tmp_path),
            "llm_model": "gpt-5.1",
            "meta_json": None,
            "invoke_llm": False,
            "suggest": False,
            "schedule": True,
            "content_md": None,
            "publish_date": None,
            "preview": False,
            "force": False,
            "minimize_cost": False,
            "quality_profile": "balanced",
            "outfile": None,
            "outfile_format": "json",
        },
    )()

    rc_code, usage = wp_agent.run_agentic_workflow(args)

    assert rc_code == 0
    assert usage == {}
    assert captured["url"] == "https://example.com"
    assert captured["target"] == "03-19-2026"
    assert captured["dry_run"] is True
    assert captured["headers"]["Authorization"] == "Basic token"
    assert (Path(tmp_path) / "unschedule_results.json").exists()
    assert "rows=1" in capsys.readouterr().out


def test_handle_args_accepts_update_post(monkeypatch):
    monkeypatch.setattr(wp_agent.wpu, "load_dotenv", lambda: None)
    monkeypatch.setattr(wp_agent, "_ensure_stdout_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        wp_agent.sys,
        "argv",
        [
            "wp_agent.py",
            "--update-post",
            "Kill Your Darlings",
            "--content-md",
            "post.md",
            "--update",
            "content,date",
            "--publish-date",
            "05-18-2026",
        ],
    )

    args = wp_agent.handle_args()

    assert args.update_post == "Kill Your Darlings"
    assert args.content_md == ["post.md"]
    assert args.update == ["content,date"]
    assert args.publish_date == "05-18-2026"


def test_run_agentic_workflow_update_post_content_and_date(monkeypatch, tmp_path, capsys):
    source = tmp_path / "kill-your-darlings.md"
    source.write_text("# Kill Your Darlings\n\nUpdated body.\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(wp_agent, "_init_google_client", lambda *_args, **_kwargs: {"status": "ok"})
    monkeypatch.setattr(wp_agent.wpu, "build_auth_header", lambda *_args, **_kwargs: {"Authorization": "Basic token"})
    monkeypatch.setattr(wp_agent.wpu, "render_ascii_table", lambda rows: f"rows={len(rows)}")

    def fake_update(url, headers, target, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["target"] = target
        captured.update(kwargs)
        return {
            "row": {
                "operation": "update-post",
                "id": 57067,
                "title": "Kill Your Darlings",
                "status": "future",
                "action": "updated",
            },
            "payload": {"content": "Updated body.", "date": "2026-05-18T08:44:00"},
            "post": {"id": 57067},
        }

    monkeypatch.setattr(wp_agent.wpu, "upload_media_and_replace", lambda text, *_args: (text, []))
    monkeypatch.setattr(wp_agent.wpu, "update_existing_post_wp_api", fake_update)

    args = type(
        "Args",
        (),
        {
            "unschedule": None,
            "update_post": "Kill Your Darlings",
            "update": ["content,date"],
            "status": None,
            "wp_username": "user",
            "wp_app_password": "pass",
            "url": "https://example.com",
            "dry_run": False,
            "outdir": str(tmp_path / "out"),
            "llm_model": "gpt-5.1",
            "meta_json": None,
            "invoke_llm": False,
            "suggest": False,
            "schedule": True,
            "content_md": [str(source)],
            "publish_date": "05-18-2026",
            "preview": False,
            "force": False,
            "minimize_cost": False,
            "quality_profile": "balanced",
            "outfile": None,
            "outfile_format": "json",
        },
    )()

    rc_code, usage = wp_agent.run_agentic_workflow(args)

    assert rc_code == 0
    assert usage == {}
    assert captured["target"] == "Kill Your Darlings"
    assert captured["update_fields"] == ["content", "date"]
    assert captured["publish_date"] == "05-18-2026"
    assert captured["content_md"].startswith("# Kill Your Darlings")
    assert (Path(args.outdir) / "update_post_result.json").exists()
    assert "rows=1" in capsys.readouterr().out
