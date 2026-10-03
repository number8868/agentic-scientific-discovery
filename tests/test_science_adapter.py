import pytest
from nova.contracts import ExperimentSpec, GroupSummary, Result, Split, Template
from nova import science_adapter

def spec(template="family_screen", **updates):
    value = dict(schema_version=1, experiment_id="E1", hypothesis_id="H1", dataset_sha256="d" * 64,
                 split="discovery", template=template, groups=("oxide", "chalcogenide"),
                 bandgap_method="opt", gap_window_ev=(1.1, 1.8), ehull_max_ev_atom=.05,
                 bootstrap_repeats=2000, seed=1729, timeout_seconds=120, mode="live")
    value.update(updates); return value

def returned(s, template):
    c = ExperimentSpec.from_dict({k: v for k, v in s.items() if k not in {"mode"}})
    g = tuple(GroupSummary(x, 10, 10, 2, 1, .2, .2, .2) for x in ("oxide", "chalcogenide"))
    return Result("R-" + template, c.experiment_id, c.sha256, c.dataset_sha256,
                  "completed", "inconclusive", "s", "f", 1.0, g)

@pytest.mark.parametrize("template", ["family_screen", "threshold_sensitivity"])
def test_adapter_uses_a_executor(monkeypatch, template):
    seen = []
    monkeypatch.setattr(science_adapter.science_executor, "execute", lambda payload: (seen.append(payload) or returned(payload, template)))
    result = science_adapter.execute_science_experiment(spec(template=template))
    assert result.execution_status == "completed" and seen[0]["mode"] == "live"
    assert seen[0]["template"] == template

def test_adapter_rejects_fixture_paths_and_schema(monkeypatch):
    with pytest.raises(ValueError): science_adapter.execute_science_experiment(spec(mode="fixture"))
    with pytest.raises(ValueError): science_adapter.execute_science_experiment(dict(spec(), dataset_path="x"))
    with pytest.raises(ValueError): science_adapter.execute_science_experiment(spec(template="holdout_validation"))

def test_adapter_does_not_swallow_executor_error(monkeypatch):
    def fail(_): raise ValueError("dataset authorization failed")
    monkeypatch.setattr(science_adapter.science_executor, "execute", fail)
    with pytest.raises(ValueError, match="authorization"): science_adapter.execute_science_experiment(spec())

def test_adapter_validates_result_associations(monkeypatch):
    bad = returned(spec(), "family_screen")
    bad = Result(bad.result_id, bad.experiment_id, "wrong", bad.dataset_sha256, bad.execution_status,
                 bad.scientific_status, bad.started_at, bad.finished_at, bad.elapsed_seconds, bad.groups_summary)
    monkeypatch.setattr(science_adapter.science_executor, "execute", lambda _: bad)
    with pytest.raises(ValueError, match="spec_sha256"): science_adapter.execute_science_experiment(spec())
