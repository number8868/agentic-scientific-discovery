from scripts.check_databricks_live_config import CONFIG, preflight, validate_config


def test_live_config_has_bounded_databricks_permissions():
    result = validate_config(CONFIG)
    assert result["ok"], result["errors"]
    text = CONFIG.read_text()
    assert "async: false" in text
    assert "nova.live_bridge.execute_live_registered_experiment" in text
    assert "execute_fixture" not in text


def test_forbidden_shell_paths_and_fixture_bridge_are_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("executor:\n  shell: true\n  path: /tmp\n  callable: nova.omnigent_bridge.execute_fixture_registered_experiment\n")
    result = validate_config(bad)
    assert not result["ok"]
    assert any("forbidden" in item or "fixture" in item for item in result["errors"])


def test_missing_local_prerequisites_fail_closed(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    result = preflight(CONFIG, root=root, environ={"PATH": str(tmp_path / "empty-bin")}, home=tmp_path)
    assert not result["ok"]
    assert not all(result["checks"].values())
    assert result["provider_call"] == "not attempted"


def test_preflight_accepts_complete_local_shape_without_provider_call(tmp_path):
    root = tmp_path / "repo"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "manifest.json").write_text('{"dataset":"dft_3d"}')
    (data / "protocol.json").write_text('{}')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("databricks", "omnigent"):
        executable = bin_dir / name
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    cfg = tmp_path / "databrickscfg"
    cfg.write_text("[oss]\nhost = https://redacted.example\n")
    result = preflight(CONFIG, root=root, environ={"PATH": str(bin_dir), "DATABRICKS_CONFIG_FILE": str(cfg)})
    assert result["ok"], result
    assert result["provider_call"] == "not attempted"
