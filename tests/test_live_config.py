from scripts.check_live_config import check
from scripts import run_open_source_live

def test_live_config():
    result=check(); assert result["ok"], result

def test_sdk_codex_is_bounded():
    result = check()
    assert result["required_runtime_env"] == {
        "HARNESS_CODEX_DISABLE_NATIVE_TOOLS": "1",
        "HARNESS_CODEX_ENABLE_WEB_SEARCH": "0",
    }

def test_launcher_check_only_does_not_start_omnigent(monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(run_open_source_live.subprocess, "run", fake_run)
    assert run_open_source_live.main(["--check-only"]) == 0
    assert len(calls) == 1
    assert calls[0][0][0][1].endswith("check_live_config.py")

def test_launcher_forces_bounded_environment(monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(run_open_source_live.subprocess, "run", fake_run)
    assert run_open_source_live.main([]) == 0
    assert len(calls) == 2
    argv, kwargs = calls[1][0][0], calls[1][1]
    assert argv[0] == str(run_open_source_live.OMNIGENT)
    assert argv[1:4] == ["run", "--no-session", str(run_open_source_live.CONFIG)]
    assert kwargs["env"].get("HARNESS_CODEX_DISABLE_NATIVE_TOOLS") == "1"
    assert kwargs["env"].get("HARNESS_CODEX_ENABLE_WEB_SEARCH") == "0"

def test_launcher_rejects_tool_override_without_starting(monkeypatch):
    calls = []
    monkeypatch.setattr(run_open_source_live.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    assert run_open_source_live.main(["--tools", "coding"]) == 2
    assert calls == []

def test_explicit_mixed_models_are_allowed(tmp_path):
    config = tmp_path / "live.yaml"
    text = run_open_source_live.CONFIG.read_text()
    text = text.replace("gpt-5.6-luna", "gpt-5.4-mini", 1)
    text = text.replace("gpt-5.6-luna", "gpt-6.1-sol", 1)
    config.write_text(text)
    result = __import__("scripts.check_live_config", fromlist=["check"]).check(config)
    assert result["ok"], result
    assert result["models"] == ["gpt-5.4-mini", "gpt-6.1-sol", "gpt-5.6-luna", "gpt-5.6-luna"]

def test_missing_executor_model_fails_closed(tmp_path):
    config = tmp_path / "live.yaml"
    text = run_open_source_live.CONFIG.read_text()
    text = text.replace("model: gpt-5.6-luna", "model:", 1)
    config.write_text(text)
    result = __import__("scripts.check_live_config", fromlist=["check"]).check(config)
    assert not result["ok"]
    assert "four explicit executor models (no silent default)" in result["missing"]
