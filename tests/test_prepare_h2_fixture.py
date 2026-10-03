import json
from pathlib import Path

import pytest

from nova.storage import Storage
from scripts.prepare_h2_fixture import prepare_h2_fixture


def test_prepare_creates_canonical_fixture_spec_and_events(tmp_path):
    db = tmp_path / "h2.sqlite"
    output = prepare_h2_fixture(db, "run-fixture-01")
    store = Storage(db).initialize()
    spec = store.get_spec(output["experiment_id"])
    events = store.list_events("run-fixture-01")
    assert spec.template.value == "family_screen"
    assert spec.split.value == "discovery"
    assert output["mode"] == "fixture"
    assert [event.event_type for event in events] == ["run_created", "hypothesis_frozen", "selection"]
    assert all(event.mode.value == "fixture" for event in events)
    assert [event.actor for event in events] == ["host", "pi", "pi"]
    assert output["next_environment"]["NOVA_RUN_DB"] == str(db.resolve())


def test_rejects_dangerous_and_non_sqlite_targets(tmp_path):
    with pytest.raises(ValueError):
        prepare_h2_fixture(Path.home())
    non_sqlite = tmp_path / "not.sqlite"
    non_sqlite.write_text("not sqlite")
    with pytest.raises(ValueError):
        prepare_h2_fixture(non_sqlite)
    with pytest.raises(ValueError):
        prepare_h2_fixture(tmp_path / "bad id", "../unsafe")


def test_output_has_no_secret_or_host_and_no_external_process(tmp_path):
    output = prepare_h2_fixture(tmp_path / "safe.sqlite", "safe-run")
    text = json.dumps(output)
    assert "token" not in text.lower()
    assert "authorization" not in text.lower()
    assert "https://" not in text.lower()
    assert "databricks_host" not in text.lower()
    assert output["next_command"] == "omnigent run /tmp/nova-mat-databricks.yaml"
