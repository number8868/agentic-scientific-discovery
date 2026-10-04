"""ID-only host gate for one registered, frozen live holdout execution.

The bridge owns run authorization and the single-attempt claim. The worker
receives only the host-derived registered spec, the immutable frozen protocol,
and verified discovery evidence; it never receives a caller-supplied path.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from datetime import datetime, timezone
from typing import Any
import uuid

from .contracts import Event, ExperimentSpec, Mode, Result, Split, Template
from .live_bridge import _read_context
from .process_control import ProcessController, WorkerTimeoutError
from .storage import Storage


MAX_WORKER_SECONDS = 120.0
AGGREGATE_SCIENCE_BUDGET_SECONDS = 360.0
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_THRESHOLD_GRID = (0.025, 0.05, 0.10)
_PROTOCOL_FIELDS = frozenset({
    "schema_version", "hypothesis_id", "dataset_sha256", "main_result_id",
    "followup_result_id", "main_spec", "followup_spec", "review_refs",
    "explanation", "holdout_split", "holdout_template",
})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _protocol_json(value: Any) -> str:
    # Match decision_tools.freeze_final exactly: default ensure_ascii=True.
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _secure_regular_file(path: Path, message: str) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise ValueError(message) from None
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError(message)


def _record(path: Path, run_id: str) -> tuple[str, str, str, dict[str, Any]]:
    """Return the full frozen record, including hash columns hidden by Storage."""
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            row = db.execute(
                "SELECT frozen_protocol_id, protocol_sha256, holdout_experiment_id, protocol_json "
                "FROM final_protocols WHERE run_id=?", (run_id,),
            ).fetchone()
    except Exception:
        raise ValueError("frozen protocol record is unavailable") from None
    if row is None:
        raise ValueError("run has no frozen final protocol")
    try:
        protocol = json.loads(row[3])
    except Exception:
        raise ValueError("frozen protocol record is invalid") from None
    if not isinstance(protocol, dict):
        raise ValueError("frozen protocol record is invalid")
    return row[0], row[1], row[2], protocol


def _derive_holdout(run_id: str, protocol: dict[str, Any], frozen_id: str) -> ExperimentSpec:
    main = ExperimentSpec.from_dict(protocol["main_spec"])
    followup = ExperimentSpec.from_dict(protocol["followup_spec"])
    return ExperimentSpec(
        1,
        "NOVA-HOLDOUT-" + _sha256((run_id + ":" + frozen_id).encode("utf-8"))[:16],
        main.hypothesis_id,
        main.dataset_sha256,
        Split.HOLDOUT,
        Template.HOLDOUT_VALIDATION,
        main.groups,
        main.bandgap_method,
        main.gap_window_ev,
        main.ehull_max_ev_atom,
        main.bootstrap_repeats,
        main.seed,
        main.timeout_seconds,
        protocol["followup_result_id"],
        protocol["followup_result_id"],
        frozen_id,
    )


def _check_frozen_science_spec(spec: ExperimentSpec, template: Template) -> None:
    expected = {
        "schema_version": 1,
        "template": template,
        "split": Split.DISCOVERY,
        "groups": ("oxide", "chalcogenide"),
        "bandgap_method": "opt",
        "gap_window_ev": (1.1, 1.8),
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "timeout_seconds": 120,
    }
    for field, value in expected.items():
        if getattr(spec, field) != value:
            raise ValueError(f"registered {template.value} spec is not the frozen discovery spec")


def _event(events, kind: str, actor: str, reference: str | None):
    matches = [item for item in events if item.event_type == kind and
               item.actor == actor and item.mode is Mode.LIVE and
               item.payload_ref == reference]
    return matches[0] if len(matches) == 1 else None


def _assert_owned_discovery(
    store: Storage, events: list[Event], protocol: dict[str, Any], active_dataset: str,
) -> tuple[ExperimentSpec, ExperimentSpec, Result, Result]:
    if set(protocol) != _PROTOCOL_FIELDS or protocol.get("schema_version") != 1:
        raise ValueError("frozen protocol has an unsupported shape")
    main_id, followup_id = protocol.get("main_result_id"), protocol.get("followup_result_id")
    if not all(isinstance(value, str) and value for value in (main_id, followup_id)) or main_id == followup_id:
        raise ValueError("frozen protocol result references are invalid")
    if protocol.get("review_refs") != [main_id, followup_id]:
        raise ValueError("frozen protocol review references are invalid")
    if (protocol.get("holdout_split") != Split.HOLDOUT.value or
            protocol.get("holdout_template") != Template.HOLDOUT_VALIDATION.value):
        raise ValueError("frozen protocol does not define a holdout validation")
    if protocol.get("dataset_sha256") != active_dataset:
        raise ValueError("frozen protocol dataset does not match the active prepared dataset")

    try:
        main = ExperimentSpec.from_dict(protocol["main_spec"])
        followup = ExperimentSpec.from_dict(protocol["followup_spec"])
    except Exception:
        raise ValueError("frozen protocol discovery specs are invalid") from None
    registered_main = store.read_spec(main.experiment_id)
    registered_followup = store.read_spec(followup.experiment_id)
    if (registered_main is None or registered_followup is None or
            registered_main.to_dict() != main.to_dict() or
            registered_followup.to_dict() != followup.to_dict()):
        raise ValueError("frozen protocol discovery specs do not match registered specs")
    if main.experiment_id == followup.experiment_id:
        raise ValueError("frozen protocol requires two distinct discovery specs")
    _check_frozen_science_spec(main, Template.FAMILY_SCREEN)
    _check_frozen_science_spec(followup, Template.THRESHOLD_SENSITIVITY)
    if (main.dataset_sha256 != active_dataset or followup.dataset_sha256 != active_dataset or
            main.hypothesis_id != followup.hypothesis_id or
            protocol.get("hypothesis_id") != main.hypothesis_id):
        raise ValueError("frozen discovery specs do not share the active hypothesis and dataset")

    main_result = store.read_result(main_id)
    followup_result = store.read_result(followup_id)
    if main_result is None or followup_result is None:
        raise ValueError("frozen discovery results are unavailable")
    for result, spec in ((main_result, main), (followup_result, followup)):
        if (result.execution_status != "completed" or result.error is not None or
                result.experiment_id != spec.experiment_id or
                result.spec_sha256 != spec.sha256 or
                result.dataset_sha256 != active_dataset or
                not isinstance(result.elapsed_seconds, (int, float)) or
                isinstance(result.elapsed_seconds, bool) or
                not math.isfinite(result.elapsed_seconds) or result.elapsed_seconds < 0):
            raise ValueError("frozen discovery result identity or hash is invalid")

    main_selection = _event(events, "selection", "pi", main.experiment_id)
    followup_selection = _event(events, "second_selection", "pi", followup.experiment_id)
    created = _event(events, "run_created", "host", None)
    main_running = _event(events, "running", "runner", main.experiment_id)
    followup_running = _event(events, "running", "runner", followup.experiment_id)
    main_owned = _event(events, "result", "runner", main_id)
    followup_owned = _event(events, "result", "runner", followup_id)
    running_events = [event for event in events if event.event_type == "running"]
    discovery_result_events = [event for event in events
                               if event.event_type == "result" and event.actor == "runner"]
    selection_events = [event for event in events
                        if event.event_type in {"selection", "second_selection"}]
    if (len(running_events) != 2 or
            {event.payload_ref for event in running_events} !=
            {main.experiment_id, followup.experiment_id} or
            any(event.actor != "runner" or event.mode is not Mode.LIVE for event in running_events) or
            len(discovery_result_events) != 2 or
            {event.payload_ref for event in discovery_result_events} != {main_id, followup_id} or
            len(selection_events) != 2 or
            {event.payload_ref for event in selection_events} !=
            {main.experiment_id, followup.experiment_id}):
        raise ValueError("run does not contain exactly two native discovery executions")
    if not all((created, main_selection, followup_selection, main_running, followup_running,
                main_owned, followup_owned)):
        raise ValueError("frozen discovery results are not owned by this live run")
    failed = any(event.event_type in {"tool_failed", "holdout_failed"} and
                 event.payload_ref in {main.experiment_id, followup.experiment_id}
                 for event in events)
    if failed:
        raise ValueError("frozen discovery lineage contains a failed execution attempt")
    if not (created.seq < main_selection.seq < main_running.seq < main_owned.seq <
            followup_selection.seq < followup_running.seq < followup_owned.seq):
        raise ValueError("discovery registration and result event lineage is invalid")
    if followup.parent_result_id != main_id or followup.review_id != main_id:
        raise ValueError("follow-up spec is not linked to the primary result")

    main_review = store.read_review(main_id)
    followup_review = store.read_review(followup_id)
    main_review_event = _event(events, "review", "skeptic", main_id)
    followup_review_event = _event(events, "second_review", "skeptic", followup_id)
    if (main_review is None or main_review.experiment_id != main.experiment_id or
            main_review.result_id != main_id or
            main_review.recommended_template is not Template.THRESHOLD_SENSITIVITY or
            main_id not in main_review.claim_refs or main_review_event is None):
        raise ValueError("primary discovery Skeptic review is missing or invalid")
    if (followup_review is None or followup_review.experiment_id != followup.experiment_id or
            followup_review.result_id != followup_id or
            followup_review.recommended_template is not None or
            followup_id not in followup_review.claim_refs or followup_review_event is None):
        raise ValueError("follow-up discovery Skeptic review is missing or invalid")
    if (main_owned.seq >= main_review_event.seq or
            main_review_event.seq >= followup_selection.seq or
            followup_owned.seq >= followup_review_event.seq):
        raise ValueError("follow-up review predates its run-owned result")
    return main, followup, main_result, followup_result


def _artifact_payload(result: Result, spec: ExperimentSpec, root: Path) -> tuple[str, dict[str, Any]]:
    payload_refs = [item for item in result.artifact_ids if item.startswith("nova-result-payload:")]
    path_refs = [item for item in result.artifact_ids if item.startswith("nova-artifact-path:")]
    if len(payload_refs) != 1 or len(path_refs) != 1:
        raise ValueError("science result must reference one immutable payload")
    digest = payload_refs[0].partition(":")[2]
    if not _HEX_SHA256.fullmatch(digest):
        raise ValueError("science payload ID is invalid")
    relative = Path("runs") / f"science-payload-{digest}.json"
    if path_refs[0] != f"nova-artifact-path:{relative.as_posix()}":
        raise ValueError("science payload path does not match its content hash")
    runs_root = (root / "runs").resolve()
    path = root / relative
    try:
        if path.resolve().parent != runs_root or path.resolve().name != relative.name:
            raise ValueError("science payload escaped the runs directory")
    except OSError:
        raise ValueError("science payload is unavailable") from None
    _secure_regular_file(path, "science payload is unavailable or insecure")
    try:
        raw = path.read_bytes()
        if _sha256(raw) != digest:
            raise ValueError("science payload checksum is invalid")
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise
    except Exception:
        raise ValueError("science payload is invalid") from None
    if (not isinstance(body, dict) or body.get("schema_version") != 1 or
            body.get("artifact_type") != "nova.science_payload.v1" or
            body.get("experiment_id") != spec.experiment_id or
            body.get("registered_spec_sha256") != spec.sha256 or
            not isinstance(body.get("science_result"), dict)):
        raise ValueError("science payload identity does not match its registered spec")

    from .experiments import executor
    expected_computation_sha = executor._computation_spec_sha256(
        executor._minimal_science_spec(spec)
    )
    if body.get("computation_spec_sha256") != expected_computation_sha:
        raise ValueError("discovery computation hash does not match the frozen protocol")
    science_result = body["science_result"]
    if (science_result.get("template") != spec.template.value or
            science_result.get("dataset_sha256") != spec.dataset_sha256 or
            science_result.get("spec_sha256") != expected_computation_sha):
        raise ValueError("discovery science payload result identity is invalid")
    expected_result_id = "nova-result-" + _sha256(_canonical_json({
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "payload_sha256": digest,
    }).encode("utf-8"))
    if result.result_id != expected_result_id:
        raise ValueError("discovery result ID does not match its immutable science payload")
    _assert_result_matches_artifact(result, science_result, digest, spec)
    return digest, science_result


def _assert_result_matches_artifact(result: Result, science_result: dict[str, Any],
                                    digest: str, spec: ExperimentSpec) -> None:
    from .experiments import executor

    raw_artifacts = science_result.get("artifact_ids", ())
    if (not isinstance(raw_artifacts, (tuple, list)) or
            any(not isinstance(item, str) for item in raw_artifacts)):
        raise ValueError("science payload artifact references are invalid")
    expected_artifacts = tuple(raw_artifacts) + (
        f"nova-result-payload:{digest}",
        f"nova-artifact-path:runs/science-payload-{digest}.json",
    )
    try:
        expected_groups = executor._groups_summary(science_result.get("groups_summary"))
        expected_interval = executor._interval(
            science_result.get("resampling_interval"), "resampling_interval"
        )
        expected_missingness = executor._interval(
            science_result.get("missingness_interval"), "missingness_interval"
        )
        expected_quality = ("science-quality-json-v1:" +
                            executor._canonical_json(science_result.get("quality_flags")),)
    except Exception:
        raise ValueError("science payload contains invalid canonical result fields") from None
    if (result.execution_status != "completed" or result.error is not None or
            result.scientific_status != science_result.get("scientific_status") or
            result.groups_summary != expected_groups or result.delta != science_result.get("delta") or
            result.resampling_interval != expected_interval or
            result.missingness_interval != expected_missingness or
            result.quality_flags != expected_quality or result.artifact_ids != expected_artifacts):
        raise ValueError("stored Result fields do not match its immutable science payload")


def _verified_evidence(main: ExperimentSpec, followup: ExperimentSpec,
                       main_result: Result, followup_result: Result) -> dict[str, Any]:
    from .experiments import executor
    # Hash both discovery artifacts before passing the canonical native Results
    # to the executor. Only the threshold artifact's grid values are needed.
    _artifact_payload(main_result, main, Path(executor.PROJECT_ROOT))
    _, followup_science = _artifact_payload(
        followup_result, followup, Path(executor.PROJECT_ROOT)
    )
    if followup_science.get("primary_point_index") != 1:
        raise ValueError("follow-up science payload has an invalid frozen primary point")
    points = followup_science.get("points")
    if not isinstance(points, list) or len(points) != len(_THRESHOLD_GRID):
        raise ValueError("follow-up science payload does not contain the frozen threshold grid")
    try:
        grid = tuple(float(point["threshold_ev_atom"]) for point in points)
    except Exception:
        raise ValueError("follow-up science payload threshold grid is invalid") from None
    if grid != _THRESHOLD_GRID:
        raise ValueError("follow-up science payload threshold grid differs from the frozen grid")
    return {
        "main_result": main_result.to_dict(),
        "followup_result": followup_result.to_dict(),
        "followup_science_result": followup_science,
    }


def _claim_table(path: Path) -> None:
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS holdout_bridge_claims (
                run_id TEXT NOT NULL,
                holdout_experiment_id TEXT NOT NULL,
                frozen_protocol_id TEXT NOT NULL,
                protocol_sha256 TEXT NOT NULL,
                spec_sha256 TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('claimed','failed','succeeded')),
                result_id TEXT,
                PRIMARY KEY(run_id, holdout_experiment_id),
                UNIQUE(run_id)
            )""")
    except Exception:
        raise ValueError("holdout execution claim store is unavailable") from None


def _claim(path: Path, run_id: str, spec: ExperimentSpec,
           frozen_id: str, protocol_sha: str) -> tuple[str, str | None]:
    _claim_table(path)
    try:
        with sqlite3.connect(str(path), timeout=5, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT frozen_protocol_id, protocol_sha256, spec_sha256, state, result_id "
                "FROM holdout_bridge_claims WHERE run_id=? AND holdout_experiment_id=?",
                (run_id, spec.experiment_id),
            ).fetchone()
            if row is not None:
                if row[:3] != (frozen_id, protocol_sha, spec.sha256):
                    db.execute("ROLLBACK")
                    raise ValueError("holdout execution claim does not match the frozen registration")
                db.execute("COMMIT")
                if row[3] == "claimed":
                    raise ValueError("holdout execution is already claimed")
                return row[3], row[4]
            db.execute(
                "INSERT INTO holdout_bridge_claims VALUES (?,?,?,?,?,'claimed',NULL)",
                (run_id, spec.experiment_id, frozen_id, protocol_sha, spec.sha256),
            )
            db.execute("COMMIT")
            return "claimed", None
    except sqlite3.IntegrityError:
        raise ValueError("holdout execution is already claimed") from None
    except ValueError:
        raise
    except Exception:
        raise ValueError("holdout execution claim failed closed") from None


def _append_event(path: Path, run_id: str, kind: str, actor: str, ref: str) -> Event:
    return Storage(path).initialize().append_event(
        run_id, kind, actor=actor, mode=Mode.LIVE, payload_ref=ref
    )


def _payload_digest_and_check_result_id(result: Result, spec: ExperimentSpec,
                                        protocol_sha256: str) -> str:
    from .experiments import executor
    root = Path(executor.PROJECT_ROOT)
    payload_refs = [item for item in result.artifact_ids if item.startswith("nova-result-payload:")]
    path_refs = [item for item in result.artifact_ids if item.startswith("nova-artifact-path:")]
    if len(payload_refs) != 1 or len(path_refs) != 1:
        raise ValueError("holdout result must reference one immutable payload")
    digest = payload_refs[0].partition(":")[2]
    if not _HEX_SHA256.fullmatch(digest):
        raise ValueError("holdout result payload ID is invalid")
    relative = Path("runs") / f"science-payload-{digest}.json"
    if path_refs[0] != f"nova-artifact-path:{relative.as_posix()}":
        raise ValueError("holdout result payload path does not match its content hash")
    path = root / relative
    runs_root = (root / "runs").resolve()
    try:
        if path.resolve().parent != runs_root or path.resolve().name != relative.name:
            raise ValueError("holdout result payload escaped the runs directory")
    except OSError:
        raise ValueError("holdout result payload is unavailable") from None
    _secure_regular_file(path, "holdout result payload is unavailable or insecure")
    try:
        raw = path.read_bytes()
        if _sha256(raw) != digest:
            raise ValueError("holdout result payload checksum is invalid")
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise
    except Exception:
        raise ValueError("holdout result payload is invalid") from None
    if (not isinstance(body, dict) or body.get("schema_version") != 1 or
            body.get("artifact_type") != "nova.science_payload.v1" or
            body.get("experiment_id") != spec.experiment_id or
            body.get("registered_spec_sha256") != spec.sha256 or
            not isinstance(body.get("science_result"), dict)):
        raise ValueError("holdout result payload identity is invalid")
    science_result = body["science_result"]
    from .experiments import holdout_validation, threshold_sensitivity
    computation = holdout_validation.computation_spec(
        spec, protocol_sha256, threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256,
    )
    expected_computation_sha = _sha256(_canonical_json(computation).encode("utf-8"))
    if (body.get("computation_spec_sha256") != expected_computation_sha or
            science_result.get("spec_sha256") != expected_computation_sha or
            science_result.get("template") != Template.HOLDOUT_VALIDATION.value):
        raise ValueError("holdout computation hash does not match the frozen implementation")
    expected_result_id = "nova-result-" + _sha256(_canonical_json({
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "payload_sha256": digest,
    }).encode("utf-8"))
    if result.result_id != expected_result_id:
        raise ValueError("holdout result ID does not match its immutable result payload")
    if science_result.get("dataset_sha256") != spec.dataset_sha256:
        raise ValueError("holdout result payload dataset does not match its registered spec")
    _assert_result_matches_artifact(result, science_result, digest, spec)
    return digest


def _validate_holdout_result(result: Any, spec: ExperimentSpec,
                             protocol_sha256: str) -> Result:
    if not isinstance(result, Result):
        raise ValueError("holdout executor returned a non-canonical result")
    if (result.experiment_id != spec.experiment_id or result.spec_sha256 != spec.sha256 or
            result.dataset_sha256 != spec.dataset_sha256 or
            result.execution_status != "completed" or result.error is not None or
            not isinstance(result.result_id, str) or not result.result_id):
        raise ValueError("holdout executor returned a result for the wrong frozen registration")
    _payload_digest_and_check_result_id(result, spec, protocol_sha256)
    return result


def _load_existing(store: Storage, events: list[Event], spec: ExperimentSpec,
                   claim_state: str, claim_result_id: str | None,
                   protocol_sha256: str) -> Result:
    existing = next((r for r in store.list_results()
                     if r.experiment_id == spec.experiment_id), None)
    event = _event(events, "holdout_result", "runner", claim_result_id or "")
    running = next((e for e in events if e.event_type == "holdout_running" and
                    e.actor == "runner" and e.payload_ref == spec.experiment_id), None)
    if (claim_state != "succeeded" or not claim_result_id or existing is None or
            existing.result_id != claim_result_id or event is None or running is None or
            event.seq <= running.seq):
        raise ValueError("registered holdout has no complete run-owned result")
    return _validate_holdout_result(existing, spec, protocol_sha256)


def _mark_failed(path: Path, run_id: str, spec: ExperimentSpec) -> None:
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            db.execute("UPDATE holdout_bridge_claims SET state='failed', result_id=NULL "
                       "WHERE run_id=? AND holdout_experiment_id=? AND state='claimed'",
                       (run_id, spec.experiment_id))
        _append_event(path, run_id, "holdout_failed", "host", spec.experiment_id)
    except Exception:
        # The durable claim is still present and therefore cannot be reopened.
        pass


def _persist_success(path: Path, run_id: str, spec: ExperimentSpec, result: Result) -> None:
    """Commit the Result, ownership event, and successful claim as one unit."""
    try:
        with sqlite3.connect(str(path), timeout=5, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            registered = db.execute("SELECT spec_sha256 FROM specs WHERE experiment_id=?",
                                    (spec.experiment_id,)).fetchone()
            if registered is None or registered[0] != spec.sha256:
                raise ValueError("holdout registration changed during execution")
            claim = db.execute(
                "SELECT state, spec_sha256 FROM holdout_bridge_claims "
                "WHERE run_id=? AND holdout_experiment_id=?",
                (run_id, spec.experiment_id),
            ).fetchone()
            if claim is None or claim[0] != "claimed" or claim[1] != spec.sha256:
                raise ValueError("holdout execution claim changed during execution")
            if db.execute("SELECT 1 FROM results WHERE experiment_id=? OR result_id=?",
                          (spec.experiment_id, result.result_id)).fetchone():
                raise ValueError("holdout result already exists without a successful claim")
            db.execute("INSERT INTO results VALUES (?,?,?)",
                       (result.result_id, result.experiment_id, result.to_json()))
            seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?",
                             (run_id,)).fetchone()[0]
            event = Event(run_id, seq, str(uuid.uuid4()), "holdout_result", "runner",
                          datetime.now(timezone.utc).isoformat(), 0, Mode.LIVE, result.result_id)
            db.execute("INSERT INTO events VALUES (?,?,?)", (run_id, seq, event.to_json()))
            db.execute("UPDATE holdout_bridge_claims SET state='succeeded', result_id=? "
                       "WHERE run_id=? AND holdout_experiment_id=?",
                       (result.result_id, run_id, spec.experiment_id))
            db.execute("COMMIT")
    except Exception:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise


def _holdout_worker(payload: dict[str, Any], protocol: dict[str, Any],
                    discovery_evidence: dict[str, Any]) -> Result:
    from .experiments.executor import execute_holdout
    return execute_holdout(payload, protocol, discovery_evidence)


def _default_controller_factory(registered: dict[str, Any]) -> ProcessController:
    return ProcessController(registered)


_controller_factory = _default_controller_factory


def execute_live_registered_holdout(experiment_id: str) -> Result:
    """Execute the sole frozen live holdout, addressed only by registered ID."""
    if (not isinstance(experiment_id, str) or not experiment_id or
            os.path.sep in experiment_id or (os.path.altsep and os.path.altsep in experiment_id)):
        raise ValueError("invalid holdout experiment id")
    db_path, run_id = _read_context()
    try:
        store = Storage(db_path).initialize()
        events = store.list_events(run_id)
    except Exception:
        raise ValueError("live database is unavailable") from None
    if not events or any(event.mode is not Mode.LIVE for event in events):
        raise ValueError("run is not authorized for live holdout execution")

    # Validate the immutable host record and event before looking for a cached
    # result or constructing a worker.
    frozen_id, protocol_sha, registered_holdout_id, protocol = _record(db_path, run_id)
    try:
        canonical = _protocol_json(protocol)
    except Exception:
        raise ValueError("frozen protocol is not canonical JSON") from None
    actual_protocol_sha = _sha256(canonical.encode("utf-8"))
    derived_frozen_id = "NOVA-FINAL-" + actual_protocol_sha[:16]
    if (protocol_sha != actual_protocol_sha or frozen_id != derived_frozen_id or
            registered_holdout_id != experiment_id):
        raise ValueError("frozen protocol identity or hash does not match the registered holdout")
    if _event(events, "final_protocol_frozen", "host", frozen_id) is None:
        raise ValueError("host-owned final freeze event is missing")

    from .experiments import executor
    try:
        active_dataset = executor.active_dataset_sha256()
    except Exception:
        raise ValueError("active prepared dataset is unavailable") from None
    if not isinstance(active_dataset, str) or not _HEX_SHA256.fullmatch(active_dataset):
        raise ValueError("active prepared dataset hash is invalid")
    main, followup, main_result, followup_result = _assert_owned_discovery(
        store, events, protocol, active_dataset,
    )
    consumed = sum(float(result.elapsed_seconds) for result in (main_result, followup_result))
    if consumed >= AGGREGATE_SCIENCE_BUDGET_SECONDS:
        raise ValueError("aggregate discovery science budget is exhausted")
    try:
        holdout_spec = _derive_holdout(run_id, protocol, frozen_id)
    except Exception:
        raise ValueError("frozen holdout spec cannot be derived") from None
    registered = store.read_spec(experiment_id)
    if (registered is None or registered.to_dict() != holdout_spec.to_dict() or
            registered.split is not Split.HOLDOUT or
            registered.template is not Template.HOLDOUT_VALIDATION or
            registered.dataset_sha256 != active_dataset or
            registered.frozen_protocol_id != frozen_id):
        raise ValueError("registered holdout spec differs from the frozen derivation")
    final_event = _event(events, "final_protocol_frozen", "host", frozen_id)
    review_event = _event(events, "second_review", "skeptic", protocol["followup_result_id"])
    if final_event is None or review_event is None or final_event.seq <= review_event.seq:
        raise ValueError("host freeze event does not follow the native final review")
    if any(event.event_type == "tool_failed" and event.seq < final_event.seq for event in events):
        raise ValueError("run contains a failed discovery attempt before the final freeze")
    evidence = _verified_evidence(main, followup, main_result, followup_result)

    # Cached results are consulted only after the entire authorization and
    # immutable discovery evidence chain above has been verified.
    claim_state, claim_result_id = _claim(db_path, run_id, registered, frozen_id, protocol_sha)
    existing_for_spec = next((result for result in store.list_results()
                              if result.experiment_id == registered.experiment_id), None)
    if claim_state == "succeeded":
        if existing_for_spec is None:
            raise ValueError("successful holdout claim has no stored Result")
        return _load_existing(
            store, events, registered, claim_state, claim_result_id, protocol_sha,
        )
    if claim_state != "claimed" or existing_for_spec is not None:
        raise ValueError("holdout execution was already attempted and will not be retried")

    remaining = AGGREGATE_SCIENCE_BUDGET_SECONDS - consumed
    deadline = min(MAX_WORKER_SECONDS, remaining, float(registered.timeout_seconds))
    try:
        _append_event(db_path, run_id, "holdout_running", "runner", registered.experiment_id)
        payload = registered.to_dict()
        payload.update(mode=Mode.LIVE.value, run_id=run_id)
        controller = _controller_factory({"execute_holdout": _holdout_worker})
        execution = controller.run(
            "execute_holdout", (payload, protocol, evidence), deadline_seconds=deadline,
        )
        result = _validate_holdout_result(execution.value, registered, protocol_sha)
        _persist_success(db_path, run_id, registered, result)
        return result
    except WorkerTimeoutError:
        _mark_failed(db_path, run_id, registered)
        raise ValueError("live holdout worker timed out; this frozen holdout cannot be retried") from None
    except Exception:
        _mark_failed(db_path, run_id, registered)
        raise ValueError("live holdout execution failed; this frozen holdout cannot be retried") from None


__all__ = ["execute_live_registered_holdout"]
