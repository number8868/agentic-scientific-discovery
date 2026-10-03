import pytest
from nova.contracts import Result
from nova.storage import Storage
from nova.workflow import PersistentWorkflow

def proposal(pid, template):
    return {"proposal_id": pid, "template": template,
            "spec": {"mode": "fixture", "template": template}, "estimated_seconds": 1}

def test_persistent_two_round_fixture(tmp_path):
    store = Storage(tmp_path / "evidence.sqlite")
    wf = PersistentWorkflow(store, mode="fixture")
    wf.freeze_hypothesis()
    wf.register_plan([proposal("one", "family_screen"), proposal("two", "threshold_sensitivity")])
    wf.select("one")
    first = wf.run_first()
    review = wf.submit_review("check sensitivity", "threshold_sensitivity")
    second = wf.run_second("two")
    events = store.list_events(wf.run_id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert first.result_id != second.result_id
    assert store.read_spec("one").experiment_id == "one"
    assert store.read_result(first.result_id).quality_flags == ("fixture",)
    assert store.read_review(first.result_id).result_id == first.result_id
    assert review.recommended_template.value == "threshold_sensitivity"

def test_invalid_result_reference_rejected(tmp_path):
    store = Storage(tmp_path / "evidence.sqlite").initialize()
    result = Result("r", "missing", "x", "x", "failed", None, "a", "b", 0,
                    error={"type": "tool_failed"})
    with pytest.raises(ValueError):
        store.save_result(result)


def test_live_requires_dataset_hash_and_does_not_register_invalid_spec(tmp_path):
    store = Storage(tmp_path / "evidence.sqlite")
    wf = PersistentWorkflow(store, mode="live", experiment_executor=lambda spec: {})
    wf.freeze_hypothesis()
    wf.register_plan([
        {"proposal_id": "one", "template": "family_screen", "spec": {"mode": "live", "template": "family_screen"}},
        {"proposal_id": "two", "template": "threshold_sensitivity", "spec": {"mode": "live", "template": "threshold_sensitivity"}},
    ])
    with pytest.raises(ValueError, match="dataset_sha256"):
        wf.select("one")
    assert store.read_spec("one") is None
