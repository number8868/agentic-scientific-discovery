from __future__ import annotations

import importlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from scripts import run_native_adaptive as launcher


def test_native_yaml_parses_and_roles_have_separate_function_allowlists():
    document = launcher._validate_agent()
    roles = document["tools"]
    assert roles["planner"]["tools"].keys() == {"get_adaptive_options"}
    assert roles["skeptic"]["tools"].keys() == {"read_adaptive_evidence", "record_adaptive_review"}
    assert roles["runner"]["tools"].keys() == {"execute_selected_adaptive"}
    assert roles["commit_adaptive_choice"]["callable"] == "nova.adaptive_agent_tools.commit_adaptive_choice"
    assert "shell" not in json.dumps(document).lower()
    assert "terminal" not in json.dumps(document).lower()


def test_check_only_never_needs_model_or_science_runtime(monkeypatch):
    monkeypatch.setattr(launcher.importlib.metadata, "version", lambda _name: launcher.SDK_PIN)
    monkeypatch.setattr(launcher, "_codex_binaries", lambda *, require_host: (None, None))
    result = launcher.check_only()
    assert result["status"] == "configuration_validated"
    assert result["runtime_ready"] is False
    assert result["live_execution_enabled"] is False
    assert result["guardrail_verified"] is False
    assert result["guardrail_status"] == "requested_unverified_not_effective"
    assert result["model_calls"] is False
    assert result["science_calls"] is False


def test_model_override_applies_to_root_and_each_specialist():
    rendered = launcher._model_yaml(launcher._load_yaml(), "provider/model-x")
    assert rendered["executor"]["model"] == "provider/model-x"
    assert {tool["executor"]["model"] for tool in rendered["tools"].values()
            if isinstance(tool, dict) and tool.get("type") == "agent"} == {"provider/model-x"}
    assert launcher._load_yaml()["executor"]["model"] == launcher.DEFAULT_MODEL


def test_threshold_payload_loader_accepts_actual_committed_artifact_fixture(monkeypatch, tmp_path):
    from nova.adaptive_agent_tools import _load_registered_science_payload
    from nova.contracts import ExperimentSpec, Result

    evidence_dir = Path(__file__).resolve().parents[1] / "docs" / "results" / "adaptive_live_02_with_science"
    spec_data = next(item for item in json.loads((evidence_dir / "specs.json").read_text())
                     if item["experiment_id"] == "NOVA-e9d66bd1875e488f")
    result_data = next(item for item in json.loads((evidence_dir / "results.json").read_text())
                       if item["experiment_id"] == "NOVA-e9d66bd1875e488f")
    spec = ExperimentSpec.from_dict(spec_data)
    result = Result.from_dict(result_data)
    fixture_source = evidence_dir / "science-artifacts" / "science-payload-0f0af36d9dd4a9325cb3c5943956abd62c22a802e04455750f55ace4051e09c3.json"
    run_root = tmp_path / "runs"
    run_root.mkdir()
    destination = run_root / fixture_source.name
    destination.write_bytes(fixture_source.read_bytes())
    monkeypatch.setattr("nova.adaptive_agent_tools.ROOT", tmp_path)

    payload, digest = _load_registered_science_payload(result, spec)
    assert digest == "0f0af36d9dd4a9325cb3c5943956abd62c22a802e04455750f55ace4051e09c3"
    assert payload["registered_spec_sha256"] == spec.sha256
    assert payload["computation_spec_sha256"] == payload["science_result"]["spec_sha256"]
    assert payload["science_result"]["dataset_sha256"] == spec.dataset_sha256


def test_runtime_manifest_records_effective_models_before_dispatch(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    db = run_dir / "run.sqlite"
    db.touch()
    rendered = launcher._model_yaml(launcher._load_yaml(), None)
    manifest_path = launcher._create_runtime_manifest(db, "run-1", None, rendered)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["effective_role_models"] == {"pi": "gpt-6-luna", "planner": "gpt-6-luna",
                                                 "skeptic": "gpt-6-luna", "runner": "gpt-6-luna"}
    assert manifest["native_tools_policy_requested"] == "disabled"
    assert manifest["web_search_policy_requested"] == "disabled"
    assert manifest["guardrail_verification"] == "requested_unverified_not_effective"
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        launcher._create_runtime_manifest(db, "run-1", None, rendered)


def test_finalization_cli_reply_is_persisted_when_host_verification_fails(tmp_path):
    db_path = tmp_path / "run.sqlite"
    transcript = "The final review reply captured from the CLI."

    def failed_verification():
        raise ValueError("final response hash mismatch")

    with pytest.raises(ValueError, match="final response hash mismatch"):
        launcher._capture_finalization_response_before_verification(
            db_path, "run-04", transcript, failed_verification,
        )

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT response_text,response_sha256 FROM native_finalization_supervisor_results WHERE run_id=?",
            ("run-04",),
        ).fetchone()
    assert row == (transcript, __import__("hashlib").sha256(transcript.encode()).hexdigest())
    from nova.storage import Storage
    response_events = [event for event in Storage(db_path).initialize().list_events("run-04")
                       if event.event_type == "native_finalization_supervisor_response" and event.actor == "pi"]
    assert len(response_events) == 1
    assert response_events[0].payload_ref == f"sha256:{row[1]}"
    assert not any(event.event_type == "native_adaptive_orchestration_completed"
                   for event in Storage(db_path).list_events("run-04"))


def test_live_launcher_stops_on_runtime_preflight_before_context(monkeypatch):
    from nova import live_bridge

    def forbidden_context():
        raise AssertionError("disabled launcher must not inspect or change the active context")

    monkeypatch.setattr(launcher, "check_only", lambda **_kwargs: {"runtime_ready": False})
    monkeypatch.setattr(launcher, "_require_runtime_ready",
                        lambda _check, **_kwargs: (_ for _ in ()).throw(RuntimeError("runtime preflight rejected")))
    monkeypatch.setattr(live_bridge, "_read_context", forbidden_context)
    with pytest.raises(RuntimeError, match="runtime preflight rejected"):
        launcher.run_native_adaptive(model="gpt-6-luna", remaining_seconds=600)


def test_trusted_native_child_requires_parent_marker_and_absolute_deadline(monkeypatch):
    monkeypatch.delenv(launcher.CHILD_MARKER, raising=False)
    monkeypatch.delenv(launcher.PARENT_PID_ENV, raising=False)
    monkeypatch.delenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", raising=False)
    with pytest.raises(RuntimeError, match="bounded parent"):
        launcher._require_trusted_child()
    monkeypatch.setenv(launcher.CHILD_MARKER, "1")
    monkeypatch.setenv(launcher.PARENT_PID_ENV, str(__import__("os").getppid()))
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", str(time.monotonic() + 100))
    assert launcher._require_trusted_child() <= 100


def test_host_bound_context_rejects_changed_database_or_run(monkeypatch, tmp_path):
    from nova import live_bridge
    from nova import adaptive_agent_tools as tools

    expected_db = tmp_path / "bound.sqlite"
    active_db = tmp_path / "other.sqlite"
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", str(expected_db))
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", "bound-run")
    monkeypatch.setattr(live_bridge, "_read_context", lambda: (expected_db, "bound-run"))
    assert tools._read_bound_context() == (expected_db.resolve(), "bound-run")

    monkeypatch.setattr(live_bridge, "_read_context", lambda: (active_db, "other-run"))
    with pytest.raises(ValueError, match="differs from the trusted adaptive run binding"):
        tools._read_bound_context()

    monkeypatch.delenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID")
    with pytest.raises(ValueError, match="binding is incomplete"):
        tools._read_bound_context()


def test_runner_receives_only_pi_registered_id_and_returns_real_result(monkeypatch, tmp_path):
    from nova import adaptive_agent_tools as tools
    from nova.contracts import Mode, Result, ExperimentSpec, Template
    from nova.storage import Storage

    evidence_dir = Path(__file__).resolve().parents[1] / "docs" / "results" / "adaptive_live_02_with_science"
    specs = [ExperimentSpec.from_dict(item) for item in json.loads((evidence_dir / "specs.json").read_text())]
    results = [Result.from_dict(item) for item in json.loads((evidence_dir / "results.json").read_text())]
    run_id = "adaptive-live-02"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (tmp_path / "runs").mkdir(exist_ok=True)
    db_path = run_dir / "run.sqlite"
    monkeypatch.setattr(tools, "ROOT", tmp_path)
    parent_spec = next(item for item in specs if item.template.value == "family_screen")
    parent = next(item for item in results if item.experiment_id == parent_spec.experiment_id)
    followup_spec_fixture = next(item for item in specs if item.template is Template.THRESHOLD_SENSITIVITY)
    followup_fixture = next(item for item in results if item.experiment_id == followup_spec_fixture.experiment_id)
    parent_id = parent.result_id
    dataset = parent_spec.dataset_sha256
    store = Storage(db_path).initialize()
    store.register_spec(parent_spec)
    store.save_result(parent)
    store.append_event(run_id, "selection", actor="pi", mode=Mode.LIVE, payload_ref=parent_spec.experiment_id)
    store.append_event(run_id, "result", actor="runner", mode=Mode.LIVE, payload_ref=parent_id)

    live = importlib.import_module("nova.live_bridge")
    decisions = importlib.import_module("nova.decision_tools")
    method = importlib.import_module("nova.registered_method_audit")
    context = lambda: (db_path, run_id)
    monkeypatch.setattr(live, "_read_context", context)
    monkeypatch.setattr(decisions, "_read_context", context)
    monkeypatch.setattr(decisions, "_active_dataset_sha256", lambda: dataset)
    monkeypatch.setattr(method, "_protocol", lambda: (_ for _ in ()).throw(ValueError("fixture is threshold-only")))
    monkeypatch.setenv("NOVA_ADAPTIVE_REMAINING_SECONDS", "600")
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", str(time.monotonic() + 600))
    trace_path = run_dir / "native-model-audit.jsonl"
    trace_path.touch(mode=0o600)
    trace_path.chmod(0o600)
    monkeypatch.setenv("NOVA_ADAPTIVE_TRACE_PATH", str(trace_path))
    host_binary = run_dir / "codex-code-mode-host"
    host_binary.write_text("pinned fixture binary", encoding="utf-8")
    host_binary.chmod(0o700)
    tools.record_native_trace("executor_guard_installed", actor="native-adaptive-runtime", role="runner",
                              details={"native_tools_disabled": True, "web_search_disabled": True,
                                       "skills": "none", "config_overrides": [
                                           "features.code_mode_host=true", "features.code_mode=false",
                                           'web_search="disabled"', 'model_provider="openai"'],
                                       "host_binary": str(host_binary)})
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE decision_packets (run_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, review_json TEXT)")
        db.execute("INSERT INTO decision_packets VALUES(?,?,NULL)",
                   (run_id, json.dumps({"candidate_tests": [{"template": "threshold_sensitivity"}]})))

    options = tools.get_adaptive_options()
    assert options["parent_result_id"] == parent_id
    assert "threshold_sensitivity" in options["allowed_choices"]
    evidence = tools.read_adaptive_evidence()
    assert evidence["result"]["result_id"] == parent_id
    review = tools.record_adaptive_review("The discovery contrast is based on this snapshot.", ["groups_summary", "resampling_interval"])
    assert review["evidence"]["groups_summary"] == parent.to_dict()["groups_summary"]
    committed = tools.commit_adaptive_choice("threshold_sensitivity", "check whether the contrast changes across thresholds")
    registered_id = committed["registered_id"]
    assert committed["registered_id_kind"] == "experiment_id"
    assert store.get_spec(registered_id).template is Template.THRESHOLD_SENSITIVITY

    followup_spec = store.get_spec(registered_id)
    assert followup_spec == followup_spec_fixture
    source_payload = evidence_dir / "science-artifacts" / "science-payload-0f0af36d9dd4a9325cb3c5943956abd62c22a802e04455750f55ace4051e09c3.json"
    payload_path = tmp_path / "runs" / source_payload.name
    payload_path.write_bytes(source_payload.read_bytes())
    followup = followup_fixture
    # Reproduce the persisted science Result that survived the prior packaging failure.
    # The supervisor is still forbidden to finish until Runner returns it.
    store.save_result(followup)
    with pytest.raises(ValueError, match="completed Runner Result return"):
        tools.record_supervisor_response("A response without Runner feedback")

    def fake_execute(experiment_id):
        assert experiment_id == registered_id
        return followup
    monkeypatch.setattr(live, "execute_live_registered_experiment", fake_execute)
    with pytest.raises(ValueError, match="PI-committed"):
        tools.execute_selected_adaptive("NOVA-forged")
    returned = tools.execute_selected_adaptive(registered_id)
    assert returned["result"]["result_id"] == followup.result_id
    assert returned["result"]["artifact_ids"] == list(followup.artifact_ids)
    grid = returned["discovery_threshold_sensitivity"]
    science_payload, payload_sha256 = tools._load_registered_science_payload(followup, followup_spec)
    assert science_payload["registered_spec_sha256"] == followup_spec.sha256
    assert science_payload["registered_spec_sha256"] != science_payload["computation_spec_sha256"]
    assert followup.spec_sha256 == followup_spec.sha256
    assert science_payload["computation_spec_sha256"] == science_payload["science_result"]["spec_sha256"]
    assert [point["threshold_ev_atom"] for point in grid["points"]] == [point["threshold_ev_atom"] for point in science_payload["science_result"]["points"]]
    assert grid["primary_point_index"] == science_payload["science_result"]["primary_point_index"]
    assert grid["science_payload_sha256"] == payload_sha256
    with pytest.raises(ValueError, match="PI-committed"):
        tools.execute_selected_adaptive(registered_id)
    tools.record_native_trace("tool_request", actor="codex-model", tool="execute_selected_adaptive",
                              call_id="runner-call", args={"registered_id": registered_id}, model="gpt-6-luna",
                              role="runner")
    tools.record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool="execute_selected_adaptive",
                              call_id="runner-call", result=returned, model="gpt-6-luna", role="runner",
                              status="success", structured_result=returned)
    tools.record_native_trace("turn_complete", actor="codex-model", model="gpt-6-luna", role="runner",
                              status="completed")
    stored = tools.record_supervisor_response("Runner returned the registered Result summary.")
    assert stored["parent_result_id"] == parent_id
    assert any(event.event_type == "native_adaptive_runner_result_returned" for event in store.list_events(run_id))
    assert any(event.event_type == "native_adaptive_supervisor_returned" for event in store.list_events(run_id))
    with pytest.raises(ValueError, match="already recorded"):
        tools.record_supervisor_response("Duplicate supervisor response")


def test_runner_trace_rejects_wrong_process_and_wrong_structured_feedback(monkeypatch, tmp_path):
    import hashlib
    import os
    from nova import adaptive_agent_tools as tools

    run_root = tmp_path / "runs" / "run-trace"
    run_root.mkdir(parents=True)
    trace_path = run_root / "native-model-audit.jsonl"
    trace_path.touch(mode=0o600)
    trace_path.chmod(0o600)
    monkeypatch.setattr(tools, "ROOT", tmp_path)
    monkeypatch.setenv("NOVA_ADAPTIVE_TRACE_PATH", str(trace_path))
    host_binary = run_root / "codex-code-mode-host"
    host_binary.write_text("pinned fixture binary", encoding="utf-8")
    host_binary.chmod(0o700)
    tools.record_native_trace("executor_guard_installed", actor="native-adaptive-runtime", role="runner",
                              details={"native_tools_disabled": True, "web_search_disabled": True,
                                       "skills": "none", "config_overrides": [
                                           "features.code_mode_host=true", "features.code_mode=false",
                                           'web_search="disabled"', 'model_provider="openai"'],
                                       "host_binary": str(host_binary)})
    registered_id = "NOVA-0123456789abcdef"
    expected = {"registered_id": registered_id,
                "result": {"experiment_id": registered_id, "result_id": "nova-result-fixture",
                           "execution_status": "completed", "error": None},
                "discovery_threshold_sensitivity": {
                    "scope": "discovery_only_not_holdout_validation_or_replication"}}
    expected_sha = hashlib.sha256(tools._canonical_trace_json(expected).encode()).hexdigest()

    tools.record_native_trace("tool_request", actor="codex-model", tool="execute_selected_adaptive",
                              call_id="runner-call", args={"registered_id": registered_id}, role="runner")
    # A different worker PID cannot complete the Runner request.
    tools.record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool="execute_selected_adaptive",
                              call_id="runner-call", args={"registered_id": registered_id},
                              result={"success": True}, role="runner", pid=os.getpid() + 1,
                              status="success", structured_result=expected)
    tools.record_native_trace("turn_complete", actor="codex-model", role="runner", status="completed")
    assert not tools._has_runner_dispatch_trace(registered_id=registered_id, response_sha256=expected_sha)

    # Same PID and call ID still fail when decoded output differs from the host return.
    tools.record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool="execute_selected_adaptive",
                              call_id="runner-call", args={"registered_id": registered_id},
                              result={"success": True}, role="runner", status="success",
                              structured_result={**expected, "result": {"experiment_id": registered_id,
                                                                           "execution_status": "completed",
                                                                           "error": "different return"}})
    tools.record_native_trace("turn_complete", actor="codex-model", role="runner", status="completed")
    assert not tools._has_runner_dispatch_trace(registered_id=registered_id, response_sha256=expected_sha)

    tools.record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool="execute_selected_adaptive",
                              call_id="runner-call", args={"registered_id": registered_id},
                              result={"success": True}, role="runner", status="success",
                              structured_result=expected)
    tools.record_native_trace("turn_complete", actor="codex-model", role="runner", status="completed")
    assert tools._has_runner_dispatch_trace(registered_id=registered_id, response_sha256=expected_sha)
    assert tools._decode_native_runner_tool_result(expected, registered_id) == expected
    assert tools._decode_native_runner_tool_result({"result": expected}, registered_id) == expected
    assert tools._decode_native_runner_tool_result(
        {"content": [{"type": "text", "text": json.dumps(expected)}], "isError": False}, registered_id) == expected
    assert tools._decode_native_runner_tool_result({"success": True}, registered_id) is None


def test_runner_trace_accepts_only_hash_bound_python_repr_witness(monkeypatch, tmp_path):
    import hashlib
    from nova import adaptive_agent_tools as tools

    run_root = tmp_path / "runs" / "run-repr"
    run_root.mkdir(parents=True)
    trace_path = run_root / "native-model-audit.jsonl"
    trace_path.touch(mode=0o600)
    trace_path.chmod(0o600)
    monkeypatch.setattr(tools, "ROOT", tmp_path)
    monkeypatch.setenv("NOVA_ADAPTIVE_TRACE_PATH", str(trace_path))
    host_binary = run_root / "codex-code-mode-host"
    host_binary.write_text("pinned fixture binary", encoding="utf-8")
    host_binary.chmod(0o700)
    tools.record_native_trace("executor_guard_installed", actor="native-adaptive-runtime", role="runner",
                              details={"native_tools_disabled": True, "web_search_disabled": True,
                                       "skills": "none", "config_overrides": [
                                           "features.code_mode_host=true", "features.code_mode=false",
                                           'web_search="disabled"', 'model_provider="openai"'],
                                       "host_binary": str(host_binary)})
    registered_id = "NOVA-1123456789abcdef"
    expected = {"registered_id": registered_id,
                "result": {"experiment_id": registered_id, "result_id": "nova-result-fixture",
                           "execution_status": "completed", "error": None},
                "discovery_threshold_sensitivity": {
                    "scope": "discovery_only_not_holdout_validation_or_replication"}}
    wire_result = {"result": repr(expected)}
    expected_sha = hashlib.sha256(tools._canonical_trace_json(expected).encode()).hexdigest()
    tools.record_native_trace("tool_request", actor="codex-model", tool="execute_selected_adaptive",
                              call_id="repr-call", args={"registered_id": registered_id}, role="runner")
    tools.record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool="execute_selected_adaptive",
                              call_id="repr-call", args={"registered_id": registered_id},
                              result=wire_result, role="runner", status="success")
    tools.record_native_trace("turn_complete", actor="codex-model", role="runner", status="completed")
    bad_decoded = {**expected, "result": {**expected["result"], "result_id": "different"}}
    tools.record_native_trace("tool_result_decoded_retrospectively", actor="host-transport-verifier",
                              tool="execute_selected_adaptive", call_id="repr-call", pid=__import__("os").getpid(),
                              role="runner", result=wire_result, structured_result=bad_decoded)
    assert not tools._has_runner_dispatch_trace(registered_id=registered_id, response_sha256=expected_sha)
    tools.record_native_trace("tool_result_decoded_retrospectively", actor="host-transport-verifier",
                              tool="execute_selected_adaptive", call_id="repr-call", pid=__import__("os").getpid(),
                              role="runner", result=wire_result, structured_result=expected)
    assert tools._has_runner_dispatch_trace(registered_id=registered_id, response_sha256=expected_sha)
    assert tools._decode_native_runner_tool_result(wire_result, registered_id) == expected
    assert tools._decode_native_runner_tool_result(
        {"result": "__import__('os').system('true')"}, registered_id) is None
