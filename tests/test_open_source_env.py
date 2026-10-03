import json

from scripts.check_open_source_env import _offline_yaml_check, inspect_environment


def test_offline_yaml_check_does_not_need_provider(tmp_path):
    path = tmp_path / "agent.yaml"
    path.write_text("name: demo\nexecutor:\n  auth:\n    type: databricks\ntools:\npolicies:\ncallable: nova.bridge.run\n")
    result = _offline_yaml_check(path)
    assert result["ok"]
    assert result["has_databricks_auth"]
    assert result["has_runner_callable"]


def test_yaml_check_rejects_os_access(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: bad\nexecutor:\ntools:\npolicies:\nos_env: inherit\n")
    assert not _offline_yaml_check(path)["ok"]


def test_inspection_reports_version_help_and_never_provider_call():
    result = inspect_environment("/definitely/missing/omnigent", None)
    assert result["version"]["ok"] is False
    assert result["help"]["ok"] is False
    assert result["provider_call"] == "not attempted"
