from pathlib import Path
from scripts.check_opensource_config import check, CALLABLE

ROOT = Path(__file__).parents[1]

def test_open_source_yaml_is_fixture_only_and_closed():
    result = check(ROOT / "agents" / "opensource.yaml")
    assert result["ok"], result
    assert result["function_tools"] == 1
    assert result["callable"] == CALLABLE

def test_no_secret_or_os_access_fields():
    text = (ROOT / "agents" / "opensource.yaml").read_text()
    for marker in ("os_env:", "terminals:", "DATABRICKS_TOKEN", "api_key:", "shell", "terminal:", "auth:"):
        assert marker not in text
    assert text.count("harness: codex-native") == 4
    assert "harness: codex\n" not in text
    assert text.count("model: gpt-5.6-luna") == 4
    assert "sol" not in text.lower()
    assert "gpt-reserve" not in text
