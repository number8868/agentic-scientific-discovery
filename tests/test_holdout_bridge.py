from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from nova import decision_tools, holdout_bridge
from nova.contracts import ExperimentSpec, GroupSummary, Result
from nova.experiments import executor, threshold_sensitivity
from nova.process_control import WorkerResult, WorkerTimeoutError
from nova.storage import Storage


DATASET_SHA = "a" * 64


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _write_payload(root: Path, spec: ExperimentSpec, raw: dict) -> Result:
    computation = executor._computation_spec_sha256(executor._minimal_science_spec(spec))
    science = {key: value for key, value in raw.items()
               if key not in {"started_at", "finished_at", "elapsed_seconds"}}
    body = {
        "schema_version": 1,
        "artifact_type": "nova.science_payload.v1",
        "experiment_id": spec.experiment_id,
        "registered_spec_sha256": spec.sha256,
        "computation_spec_sha256": computation,
        "science_result": science,
    }
    payload = (_canonical(body) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("runs") / f"science-payload-{digest}.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o600)
    result_id = "nova-result-" + hashlib.sha256(_canonical({
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "payload_sha256": digest,
    }).encode("utf-8")).hexdigest()
    raw_artifacts = tuple(raw.get("artifact_ids", ())) + (
        f"nova-result-payload:{digest}",
        f"nova-artifact-path:{relative.as_posix()}",
    )
    groups = executor._groups_summary(raw["groups_summary"])
    quality = ("science-quality-json-v1:" + executor._canonical_json(raw["quality_flags"]),)
    return Result(
        result_id, spec.experiment_id, spec.sha256, spec.dataset_sha256,
        "completed", raw["scientific_status"], raw["started_at"], raw["finished_at"],
        float(raw["elapsed_seconds"]), groups, raw["delta"],
        executor._interval(raw["resampling_interval"], "resampling_interval"),
        executor._interval(raw["missingness_interval"], "missingness_interval"),
        quality, raw_artifacts, None,
    )


def _raw_science(spec: ExperimentSpec, elapsed: float, template: str) -> dict:
    summary = {
        "oxide": {
            "n_total": 50, "n_observed": 45, "n_pass": 20,
            "coverage": 45 / 50, "observed_rate": 20 / 45,
            "missing_lower": 20 / 50, "missing_upper": 25 / 50,
        },
        "chalcogenide": {
            "n_total": 50, "n_observed": 45, "n_pass": 25,
            "coverage": 45 / 50, "observed_rate": 25 / 45,
            "missing_lower": 25 / 50, "missing_upper": 30 / 50,
        },
    }
    quality = {
        "oxide": {
            "minimum_evaluable_count_pass": True,
            "minimum_coverage_pass": True,
            "endpoint_has_pass_and_fail": True,
        },
        "chalcogenide": {
            "minimum_evaluable_count_pass": True,
            "minimum_coverage_pass": True,
            "endpoint_has_pass_and_fail": True,
        },
        "minimum_sample_and_coverage_pass": True,
        "endpoint_non_degenerate": True,
        "all_holdout_quality_gates_pass": True,
        "missingness_bounds_cross_zero": True,
    }
    raw = {
        "schema_version": 1,
        "template": template,
        "execution_status": "success",
        "scientific_status": "inconclusive",
        "dataset_sha256": spec.dataset_sha256,
        "spec_sha256": executor._computation_spec_sha256(executor._minimal_science_spec(spec)),
        "started_at": "2026-10-03T12:00:00+00:00",
        "finished_at": "2026-10-03T12:00:01+00:00",
        "elapsed_seconds": elapsed,
        "groups_summary": summary,
        "delta": 0.1,
        "resampling_interval": {"lower": -0.1, "upper": 0.3},
        "missingness_interval": {"lower": -0.2, "upper": 0.4},
        "quality_flags": quality,
        "artifact_ids": [f"nova-manifest:{spec.dataset_sha256}"],
    }
    if template == "threshold_sensitivity":
        raw["primary_point_index"] = 1
        raw["primary_threshold_ev_atom"] = 0.05
        raw["protocol_sha256"] = "9" * 64
        raw["extension_protocol_sha256"] = threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
        raw["split"] = "discovery"
        raw["points"] = [
            {"threshold_ev_atom": threshold, "delta": delta, "scientific_status": "inconclusive",
             "groups_summary": summary, "quality_flags": quality,
             "resampling_interval": {"lower": -0.1, "upper": 0.3},
             "missingness_interval": {"lower": -0.2, "upper": 0.4}}
            for threshold, delta in zip((0.025, 0.05, 0.1), (0.0, 0.1, 0.2))
        ]
        raw["main_point"] = raw["points"][1]
        raw["quality_flags"] = quality
        raw["artifact_ids"].append(
            "nova-threshold-protocol:" + threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
        )
    return raw


def _result(store: Storage, root: Path, spec: ExperimentSpec, elapsed: float,
            raw_builder=None) -> Result:
    raw = (raw_builder or _raw_science)(spec, elapsed, spec.template.value)
    result = _write_payload(root, spec, raw)
    store.save_result(result)
    return result


def _setup_run(tmp_path, monkeypatch, *, freeze=True, explanation="frozen protocol",
               raw_builder=None):
    run_id = "gate-run"
    db = tmp_path / "live.sqlite"
    store = Storage(db).initialize()
    db.chmod(0o600)
    monkeypatch.setattr(decision_tools, "_read_context", lambda: (db, run_id))
    monkeypatch.setattr(decision_tools, "_active_dataset_sha256", lambda: DATASET_SHA)
    monkeypatch.setattr(holdout_bridge, "_read_context", lambda: (db, run_id))
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(executor, "active_dataset_sha256", lambda: DATASET_SHA)

    store.append_event(run_id, "run_created", actor="host", mode="live")
    decision_tools.register_initial_plan("family_screen", "bounded synthetic authorization fixture")
    main_id = decision_tools.commit_initial_spec("family_screen")
    main_spec = store.read_spec(main_id)
    store.append_event(run_id, "running", actor="runner", mode="live", payload_ref=main_id)
    main_result = _result(store, tmp_path, main_spec, 2.0, raw_builder)
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=main_result.result_id)
    decision_tools.submit_live_review(main_result.result_id, "threshold sensitivity is required",
                                      "threshold_sensitivity")

    followup_id = decision_tools.commit_next_spec(main_result.result_id, "threshold_sensitivity")
    followup_spec = store.read_spec(followup_id)
    store.append_event(run_id, "running", actor="runner", mode="live", payload_ref=followup_id)
    followup_result = _result(store, tmp_path, followup_spec, 3.0, raw_builder)
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=followup_result.result_id)
    decision_tools.submit_final_review(followup_result.result_id, "final synthetic review")
    frozen = None
    if freeze:
        frozen = decision_tools.freeze_final(main_result.result_id, followup_result.result_id, explanation)
    return {
        "db": db, "store": store, "run_id": run_id,
        "main_spec": main_spec, "main_result": main_result,
        "followup_spec": followup_spec, "followup_result": followup_result,
        "frozen": frozen,
    }


def _mock_holdout_result(payload, protocol):
    spec = ExperimentSpec.from_dict({key: value for key, value in payload.items()
                                     if key in {field.name for field in __import__("dataclasses").fields(ExperimentSpec)}})
    frozen_sha = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    from nova.experiments import holdout_validation
    computation = holdout_validation.computation_spec(
        spec, frozen_sha, threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256,
    )
    computation_sha = holdout_validation._canonical_sha(computation)
    raw = {
        "schema_version": 1,
        "template": "holdout_validation",
        "execution_status": "success",
        "scientific_status": "not_tested",
        "error": None,
        "dataset_sha256": spec.dataset_sha256,
        "frozen_protocol_sha256": frozen_sha,
        "extension_protocol_sha256": threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256,
        "spec_sha256": computation_sha,
        "computation_spec": computation,
        "split": "holdout",
        "started_at": "2026-10-03T12:01:00+00:00",
        "finished_at": "2026-10-03T12:01:01+00:00",
        "elapsed_seconds": 1.0,
        "groups_summary": _raw_science(spec, 1.0, "family_screen")["groups_summary"],
        "delta": 0.0,
        "resampling_interval": None,
        "missingness_interval": {"lower": -1.0, "upper": 1.0},
        "quality_flags": {"primary_quality_pass": False},
        "artifact_ids": ["nova-synthetic-holdout-payload"],
    }
    body = executor._artifact_body(raw, spec, computation_sha)
    payload_bytes = (executor._canonical_json(body) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    relative = Path("runs") / f"science-payload-{digest}.json"
    target = Path(executor.PROJECT_ROOT) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload_bytes)
    target.chmod(0o600)
    result_id = "nova-result-" + hashlib.sha256(executor._canonical_json({
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "payload_sha256": digest,
    }).encode("utf-8")).hexdigest()
    return Result(
        result_id, spec.experiment_id, spec.sha256, spec.dataset_sha256,
        "completed", "not_tested", raw["started_at"], raw["finished_at"], 1.0,
        executor._groups_summary(raw["groups_summary"]), raw["delta"], None,
        executor._interval(raw["missingness_interval"], "missingness_interval"),
        ("science-quality-json-v1:" + executor._canonical_json(raw["quality_flags"]),),
        tuple(raw["artifact_ids"]) + (
            f"nova-result-payload:{digest}",
            f"nova-artifact-path:{relative.as_posix()}",
        ),
        None,
    )


def _synthetic_discovery_raw(spec: ExperimentSpec, elapsed: float, template: str) -> dict:
    discovery_rows = []
    for family, hulls in (
        ("oxide", (0.03, 0.07, 0.12)),
        ("chalcogenide", (0.02, 0.08, 0.11)),
    ):
        for index, hull in enumerate(hulls):
            discovery_rows.append({
                "family": family,
                "split": "discovery",
                "excluded": "false",
                "opt_gap_ev": 1.2 + 0.2 * index,
                "ehull_ev_atom": hull,
                "ehull_valid": "true",
            })
    points = [
        {
            "threshold_ev_atom": threshold,
            **threshold_sensitivity._analyze_point(discovery_rows, threshold),
        }
        for threshold in threshold_sensitivity.THRESHOLD_GRID_EV_ATOM
    ]
    primary = points[threshold_sensitivity.PRIMARY_POINT_INDEX]
    raw = _raw_science(spec, elapsed, template)
    for field in ("scientific_status", "groups_summary", "delta",
                  "resampling_interval", "missingness_interval", "quality_flags"):
        raw[field] = primary[field]
    if template == "threshold_sensitivity":
        raw.update({
            "protocol_sha256": "9" * 64,
            "extension_protocol_sha256": threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256,
            "split": "discovery",
            "primary_point_index": threshold_sensitivity.PRIMARY_POINT_INDEX,
            "primary_threshold_ev_atom": 0.05,
            "points": points,
            "main_point": primary,
        })
    return raw


class InlineController:
    def __init__(self, registered):
        self.registered = registered

    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        assert name == "execute_holdout"
        return WorkerResult(self.registered[name](*args, **(kwargs or {})), 1)


def _allow_worker(monkeypatch, calls=None):
    calls = calls if calls is not None else []

    def execute(payload, protocol, evidence):
        calls.append((payload, protocol, evidence))
        return _mock_holdout_result(payload, protocol)

    monkeypatch.setattr(executor, "execute_holdout", execute, raising=False)
    monkeypatch.setattr(holdout_bridge, "_controller_factory", InlineController)
    return calls


def _holdout_id(state):
    return state["frozen"]["holdout_experiment_id"]


def test_holdout_bridge_rejects_before_freeze_and_cross_run(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch, freeze=False)
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("premature holdout constructed a worker"))
    with pytest.raises(ValueError, match="frozen final protocol"):
        holdout_bridge.execute_live_registered_holdout("not-registered")

    other_root = tmp_path / "other"
    other_root.mkdir()
    frozen_state = _setup_run(other_root, monkeypatch)
    monkeypatch.setattr(holdout_bridge, "_read_context",
                        lambda: (frozen_state["db"], "foreign-run"))
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("cross-run holdout constructed a worker"))
    with pytest.raises(ValueError, match="live"):
        holdout_bridge.execute_live_registered_holdout(_holdout_id(frozen_state))


@pytest.mark.parametrize("tamper", [
    "protocol", "registered_holdout", "result", "numeric_result", "review",
    "freeze_event", "extra_running", "extra_other_running", "missing_run_created",
    "failed_discovery",
])
def test_holdout_bridge_rejects_tampered_authorization_before_worker(monkeypatch, tmp_path, tamper):
    state = _setup_run(tmp_path, monkeypatch)
    store, db, run_id = state["store"], state["db"], state["run_id"]
    holdout_id = _holdout_id(state)
    with sqlite3.connect(db) as conn:
        if tamper == "protocol":
            protocol = store.get_final_protocol(run_id)
            protocol["explanation"] = "changed after freeze"
            conn.execute("UPDATE final_protocols SET protocol_json=? WHERE run_id=?",
                         (json.dumps(protocol, sort_keys=True, separators=(",", ":")), run_id))
        elif tamper == "registered_holdout":
            spec = store.read_spec(holdout_id)
            changed = ExperimentSpec(
                spec.schema_version, spec.experiment_id, spec.hypothesis_id,
                spec.dataset_sha256, spec.split, spec.template, spec.groups,
                spec.bandgap_method, (1.2, 1.7), spec.ehull_max_ev_atom,
                spec.bootstrap_repeats, spec.seed, spec.timeout_seconds,
                spec.parent_result_id, spec.review_id, spec.frozen_protocol_id,
            )
            conn.execute("UPDATE specs SET spec_json=? WHERE experiment_id=?",
                         (changed.to_json(), holdout_id))
        elif tamper == "result":
            item = state["followup_result"]
            raw = json.loads(item.to_json())
            raw["dataset_sha256"] = "b" * 64
            conn.execute("UPDATE results SET result_json=? WHERE result_id=?",
                         (json.dumps(raw, sort_keys=True, separators=(",", ":")), item.result_id))
        elif tamper == "numeric_result":
            item = state["followup_result"]
            raw = json.loads(item.to_json())
            raw["delta"] = -0.5
            conn.execute("UPDATE results SET result_json=? WHERE result_id=?",
                         (json.dumps(raw, sort_keys=True, separators=(",", ":")), item.result_id))
        elif tamper == "review":
            conn.execute("DELETE FROM reviews WHERE result_id=?",
                         (state["followup_result"].result_id,))
        elif tamper == "extra_running":
            store.append_event(run_id, "running", actor="runner", mode="live",
                               payload_ref=state["followup_spec"].experiment_id)
        elif tamper == "extra_other_running":
            store.append_event(run_id, "running", actor="runner", mode="live",
                               payload_ref="unregistered-extra")
        elif tamper == "missing_run_created":
            event = next(e for e in store.list_events(run_id) if e.event_type == "run_created")
            conn.execute("DELETE FROM events WHERE run_id=? AND seq=?", (run_id, event.seq))
        elif tamper == "failed_discovery":
            store.append_event(run_id, "tool_failed", actor="host", mode="live",
                               payload_ref=state["followup_spec"].experiment_id)
        elif tamper == "freeze_event":
            event = next(e for e in store.list_events(run_id)
                         if e.event_type == "final_protocol_frozen")
            from dataclasses import replace
            conn.execute("UPDATE events SET event_json=? WHERE run_id=? AND seq=?",
                         (replace(event, actor="pi").to_json(), run_id, event.seq))
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("invalid gate constructed a worker"))
    with pytest.raises(ValueError):
        holdout_bridge.execute_live_registered_holdout(holdout_id)


def test_holdout_bridge_rejects_unregistered_id_and_tampered_protocol_parameter(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch)
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("invalid ID constructed a worker"))
    with pytest.raises(ValueError, match="frozen protocol identity"):
        holdout_bridge.execute_live_registered_holdout("NOVA-HOLDOUT-wrong")
    with sqlite3.connect(state["db"]) as conn:
        protocol = state["store"].get_final_protocol(state["run_id"])
        protocol["main_spec"]["ehull_max_ev_atom"] = 0.1
        # Rehash the modified protocol so the deeper frozen-input validation is exercised.
        serialized = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        event = next(e for e in state["store"].list_events(state["run_id"])
                     if e.event_type == "final_protocol_frozen")
        from dataclasses import replace
        changed_frozen_id = "NOVA-FINAL-" + digest[:16]
        conn.execute("UPDATE final_protocols SET protocol_json=?, protocol_sha256=?, frozen_protocol_id=? WHERE run_id=?",
                     (serialized, digest, changed_frozen_id, state["run_id"]))
        conn.execute("UPDATE events SET event_json=? WHERE run_id=? AND seq=?",
                     (replace(event, payload_ref=changed_frozen_id).to_json(),
                      state["run_id"], event.seq))
    with pytest.raises(ValueError, match="frozen"):
        holdout_bridge.execute_live_registered_holdout(_holdout_id(state))


def test_holdout_bridge_rejects_cached_orphan_result_after_authorization(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch)
    spec = state["store"].read_spec(_holdout_id(state))
    orphan = Result("untrusted-cache", spec.experiment_id, spec.sha256, spec.dataset_sha256,
                    "completed", "inconclusive", "t0", "t1", 1.0)
    state["store"].save_result(orphan)
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("orphan result reached a worker"))
    with pytest.raises(ValueError, match="already attempted"):
        holdout_bridge.execute_live_registered_holdout(spec.experiment_id)


def test_holdout_bridge_success_is_hash_validated_and_idempotent(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch, explanation="frozen café")
    calls = _allow_worker(monkeypatch)
    holdout_id = _holdout_id(state)
    result = holdout_bridge.execute_live_registered_holdout(holdout_id)
    cached = holdout_bridge.execute_live_registered_holdout(holdout_id)
    assert result == cached
    assert len(calls) == 1
    payload, protocol, evidence = calls[0]
    assert payload["experiment_id"] == holdout_id
    assert payload["run_id"] == state["run_id"]
    assert set(evidence) == {"main_result", "followup_result", "followup_science_result"}
    assert evidence["main_result"]["result_id"] == state["main_result"].result_id
    events = state["store"].list_events(state["run_id"])
    assert [event.event_type for event in events[-2:]] == ["holdout_running", "holdout_result"]
    assert events[-1].payload_ref == result.result_id


def test_holdout_bridge_concurrent_duplicate_claim_fails_closed(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    calls = _allow_worker(monkeypatch)

    class BlockingController(InlineController):
        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            entered.set()
            assert release.wait(10)
            return super().run(name, args, kwargs, deadline_seconds=deadline_seconds)

    monkeypatch.setattr(holdout_bridge, "_controller_factory", BlockingController)
    outcome = {}

    def first_call():
        try:
            outcome["result"] = holdout_bridge.execute_live_registered_holdout(_holdout_id(state))
        except Exception as exc:  # pragma: no cover - diagnostic for thread failures
            outcome["error"] = exc

    thread = threading.Thread(target=first_call)
    thread.start()
    assert entered.wait(10)
    with pytest.raises(ValueError, match="already claimed"):
        holdout_bridge.execute_live_registered_holdout(_holdout_id(state))
    release.set()
    thread.join(15)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert outcome["result"].execution_status == "completed"
    assert len(calls) == 1


def test_holdout_bridge_timeout_consumes_claim_and_never_retries(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch)
    calls = []

    class TimeoutController:
        def __init__(self, registered):
            pass

        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            calls.append(deadline_seconds)
            assert deadline_seconds == 120
            raise WorkerTimeoutError("synthetic deadline")

    monkeypatch.setattr(holdout_bridge, "_controller_factory", TimeoutController)
    holdout_id = _holdout_id(state)
    with pytest.raises(ValueError, match="timed out"):
        holdout_bridge.execute_live_registered_holdout(holdout_id)
    assert calls == [120]
    assert state["store"].list_results()[-1].experiment_id != holdout_id
    assert state["store"].list_events(state["run_id"])[-1].event_type == "holdout_failed"
    monkeypatch.setattr(holdout_bridge, "_controller_factory",
                        lambda _registered: pytest.fail("failed claim was retried"))
    with pytest.raises(ValueError, match="already attempted"):
        holdout_bridge.execute_live_registered_holdout(holdout_id)


def test_holdout_claim_unique_per_run_even_for_a_changed_holdout_id(monkeypatch, tmp_path):
    state = _setup_run(tmp_path, monkeypatch)
    protocol = state["frozen"]["protocol"]
    protocol_sha = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    frozen_id = state["frozen"]["frozen_protocol_id"]
    first = state["store"].read_spec(_holdout_id(state))
    assert holdout_bridge._claim(state["db"], state["run_id"], first,
                                 frozen_id, protocol_sha) == ("claimed", None)
    changed = ExperimentSpec(
        first.schema_version, "NOVA-HOLDOUT-different", first.hypothesis_id,
        first.dataset_sha256, first.split, first.template, first.groups,
        first.bandgap_method, first.gap_window_ev, first.ehull_max_ev_atom,
        first.bootstrap_repeats, first.seed, first.timeout_seconds,
        first.parent_result_id, first.review_id, first.frozen_protocol_id,
    )
    with pytest.raises(ValueError, match="already claimed"):
        holdout_bridge._claim(state["db"], state["run_id"], changed,
                              "NOVA-FINAL-different", "c" * 64)


def test_holdout_cli_gate_to_actual_executor_uses_only_synthetic_rows(
    monkeypatch, tmp_path, capsys,
):
    from importlib.util import module_from_spec, spec_from_file_location

    from nova import live_bridge
    from nova.data import pipeline
    from nova.experiments import holdout_validation

    state = _setup_run(tmp_path, monkeypatch, raw_builder=_synthetic_discovery_raw)
    monkeypatch.setattr(holdout_validation, "DATASET_SHA256", DATASET_SHA)
    manifest = {
        "original_download_zip_sha256": DATASET_SHA,
        "protocol_sha256": "9" * 64,
        "split_assignment_sha256": "8" * 64,
    }
    parent_protocol = {"protocol_id": "family_screen_v1", "dataset_sha256": DATASET_SHA}
    extension = {"dataset_sha256": DATASET_SHA}
    extension_sha = threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
    monkeypatch.setattr(
        holdout_validation, "_verify_fixed_manifests",
        lambda: (manifest, parent_protocol, extension, extension_sha),
    )

    synthetic_rows = []
    for family, hulls in (
        ("oxide", (0.03, 0.07, 0.12)),
        ("chalcogenide", (0.02, 0.08, 0.11)),
    ):
        for index, hull in enumerate(hulls):
            synthetic_rows.append({
                "family": family,
                "split": "holdout",
                "excluded": "false",
                "opt_gap_ev": 1.2 + 0.2 * index,
                "ehull_ev_atom": hull,
                "ehull_valid": "true",
            })
    loader_calls = []

    def synthetic_loader():
        loader_calls.append(True)
        return synthetic_rows, manifest, parent_protocol

    monkeypatch.setattr(pipeline, "_read_prepared_compositions", synthetic_loader)

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_holdout_validation.py"
    script_spec = spec_from_file_location("synthetic_holdout_cli", script_path)
    runner = module_from_spec(script_spec)
    script_spec.loader.exec_module(runner)
    runner.ROOT = tmp_path
    monkeypatch.setattr(live_bridge, "_read_context",
                        lambda: (state["db"], state["run_id"]))
    worker_errors = []

    class ActualExecutorController(InlineController):
        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            try:
                return super().run(name, args, kwargs, deadline_seconds=deadline_seconds)
            except Exception as exc:
                worker_errors.append(exc)
                raise

    monkeypatch.setattr(holdout_bridge, "_controller_factory", ActualExecutorController)

    output = tmp_path / "runs" / "holdout-evidence"
    output.mkdir()
    status = runner.main(["--experiment-id", _holdout_id(state),
                          "--output", str(output)])
    assert status == 0, repr(worker_errors)
    assert len(loader_calls) == 1
    assert {row["split"] for row in synthetic_rows} == {"holdout"}
    exported = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(exported) == 3
    assert any(item["experiment_id"] == _holdout_id(state) for item in exported)
    artifact_manifest = json.loads(
        (output / "science-artifacts.json").read_text(encoding="utf-8")
    )
    assert len(artifact_manifest["results"]) == 3
    evidence_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert {"final_protocol.json", "science-artifacts.json"} <= set(evidence_manifest["files"])
    assert (output / "final_protocol.json").is_file()
