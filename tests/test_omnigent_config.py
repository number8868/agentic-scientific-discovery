import os
from pathlib import Path
import tempfile

import pytest

from scripts.check_omnigent_config import TEMPLATE, render_local, validate


def test_databricks_template_is_safe_and_structured():
    assert validate(TEMPLATE) is True


def test_rejects_shell_and_secret(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("executor:\n  auth:\n    type: databricks\n    profile: oss\nos_env: inherit\ntoken: abc\n")
    with pytest.raises(ValueError):
        validate(bad)


def test_profile_render_comes_from_environment_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIGENT_DATABRICKS_PROFILE", "team-dev")
    destination = tmp_path / "local.yaml"
    render_local(output=destination)
    text = destination.read_text()
    assert "profile: team-dev" in text
    assert "DATABRICKS_TOKEN" not in text
    assert "https://" not in text
