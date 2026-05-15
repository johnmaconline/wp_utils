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
