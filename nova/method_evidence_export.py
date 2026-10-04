"""Export a completed run-owned method audit and its portable evidence."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from . import live_bridge
from .contracts import Event, ExperimentSpec, Mode, Result, Split, Template
from .evidence import _atomic_write, _safe_output

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / "runs"
RUN_FILES = ("events.jsonl", "specs.json", "results.json", "reviews.json")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decision_json(value: Any) -> str:
    # B persists its adaptive decision records with json.dumps' ASCII default.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _output_path(value: os.PathLike[str] | str | None) -> Path:
    path = Path(value) if value is not None else RUNS_ROOT / ("method-export-" + uuid4().hex[:12])
    if ".." in path.parts:
        raise ValueError("evidence output path traversal is not allowed")
    resolved, root = path.resolve(), RUNS_ROOT.resolve()
    if resolved == root or not _under(resolved, root):
        raise ValueError("method evidence output must be a separate directory under runs/")
    if path.is_symlink() or (resolved.exists() and not resolved.is_dir()):
        raise ValueError("evidence output path is not a regular directory")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("evidence output must be new or empty")
    return resolved


def _context() -> tuple[Path, str]:
    db, run_id = live_bridge._read_context()
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("live context is invalid")
    return Path(db).resolve(), run_id


def _same_context(expected: tuple[Path, str]) -> None:
    if _context() != expected:
        raise ValueError("live context changed; refusing method evidence export")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _snapshot(db_path: Path, run_id: str, audit_id: str) -> dict[str, Any]:
    if not isinstance(audit_id, str) or not audit_id or "/" in audit_id or "\\" in audit_id:
        raise ValueError("invalid method audit id")
    try:
        with _ro(db_path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            row = db.execute(
                """SELECT audit_id,run_id,parent_result_id,parent_experiment_id,
                          parent_spec_sha256,dataset_sha256,protocol_sha256,request_json,status
                     FROM registered_method_audits WHERE audit_id=? AND run_id=?""",
                (audit_id, run_id),
            ).fetchone()
            if row is None:
                raise ValueError("method audit is not registered for the active run")
            registration = dict(row)
            if registration["status"] != "completed":
                raise ValueError("method evidence export requires a completed audit")

            try:
                request = json.loads(registration["request_json"])
            except (TypeError, json.JSONDecodeError):
                raise ValueError("registered method audit request is malformed") from None
            expected = {
                key: registration[key]
                for key in (
                    "audit_id", "run_id", "parent_result_id", "parent_experiment_id",
                    "parent_spec_sha256", "dataset_sha256", "protocol_sha256",
                )
            }
            expected["schema_version"] = 1
            if not isinstance(request, dict) or request != expected or _canonical(request) != registration["request_json"]:
                raise ValueError("registered method audit request does not match its stored ownership fields")

            spec_row = db.execute(
                "SELECT spec_json FROM specs WHERE experiment_id=?",
                (request["parent_experiment_id"],),
            ).fetchone()
            if spec_row is None:
                raise ValueError("registered method audit parent evidence is unavailable")
            try:
                spec_raw = json.loads(spec_row[0])
                spec = ExperimentSpec.from_dict(spec_raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ValueError("registered method audit parent Spec is malformed") from None
            if (spec.template is not Template.FAMILY_SCREEN or spec.split is not Split.DISCOVERY or
                    spec.experiment_id != request["parent_experiment_id"] or
                    spec.sha256 != request["parent_spec_sha256"] or
                    spec.dataset_sha256 != request["dataset_sha256"]):
                raise ValueError("registered method audit parent is not its discovery family Spec")

            # Check the parent Result's linkage using metadata only before selecting or
            # decoding its JSON.  A tampered registration that points at a holdout
            # therefore cannot cause this exporter to read the holdout outcome.
            parent_metadata = db.execute(
                "SELECT experiment_id FROM results WHERE result_id=?",
                (request["parent_result_id"],),
            ).fetchone()
            if parent_metadata is None or parent_metadata[0] != spec.experiment_id:
                raise ValueError("registered method audit parent Result is not linked to its discovery Spec")
            parent_row = db.execute(
                "SELECT result_json FROM results WHERE result_id=?",
                (request["parent_result_id"],),
            ).fetchone()
            if parent_row is None:
                raise ValueError("registered method audit parent evidence is unavailable")
            try:
                parent = Result.from_dict(json.loads(parent_row[0]))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ValueError("registered method audit parent Result is malformed") from None
            if (parent.result_id != request["parent_result_id"] or
                    parent.experiment_id != spec.experiment_id or
                    parent.spec_sha256 != spec.sha256 or
                    parent.dataset_sha256 != spec.dataset_sha256 or
                    parent.execution_status != "completed" or parent.error is not None):
                raise ValueError("registered method audit parent Result does not match its discovery Spec")

            cached = db.execute(
                "SELECT result_json FROM registered_method_audit_results WHERE audit_id=?",
                (audit_id,),
            ).fetchone()
            if cached is None:
                raise ValueError("completed method audit has no cached result")
            try:
                audit_output = json.loads(cached[0])
            except (TypeError, json.JSONDecodeError):
                raise ValueError("cached method audit result is malformed") from None
            if not isinstance(audit_output, dict) or _canonical(audit_output) != cached[0]:
                raise ValueError("cached method audit result is not canonical")

            event_raw_values = [item[0] for item in db.execute(
                "SELECT event_json FROM events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()]
            events = [Event.from_dict(json.loads(item)) for item in event_raw_values]

            refs = {event.payload_ref for event in events if event.payload_ref}
            run_specs = {item[0] for item in db.execute("SELECT experiment_id,spec_sha256 FROM specs").fetchall()
                         if item[0] in refs or item[1] in refs}
            run_results = {item[0] for item in db.execute("SELECT result_id,experiment_id FROM results").fetchall()
                           if item[0] in refs or item[1] in run_specs}
            review_ids = {item[0] for item in db.execute("SELECT result_id FROM reviews").fetchall()
                          if item[0] in run_results or item[0] in refs}
            if run_specs != {spec.experiment_id}:
                raise ValueError("run export contains an unexpected or non-parent registered Spec")
            if run_results != {parent.result_id}:
                raise ValueError("run export contains an unexpected or non-parent science Result")
            if review_ids - {parent.result_id}:
                raise ValueError("run export contains a review for an unexpected Result")
            review_raw = None
            if review_ids:
                if not any(event.actor == "skeptic" and event.event_type in {"review", "second_review"}
                           and event.payload_ref == parent.result_id for event in events):
                    raise ValueError("parent review is not owned by its event ledger")
                review_row = db.execute("SELECT review_json FROM reviews WHERE result_id=?",
                                        (parent.result_id,)).fetchone()
                review_raw = review_row[0] if review_row is not None else None
            event_values = [json.loads(item[0]) for item in db.execute(
                "SELECT event_json FROM events WHERE run_id=? ORDER BY seq", (run_id,)
            ).fetchall()]
            parent_raw = json.loads(parent_row[0])
            review_value = json.loads(review_raw) if review_raw is not None else None

            tables = {item[0] for item in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            decision = None
            if "adaptive_followup_decisions" in tables:
                row = db.execute(
                    """SELECT parent_result_id,choice,reason,packet_json,selection_json
                         FROM adaptive_followup_decisions WHERE run_id=?""",
                    (run_id,),
                ).fetchone()
                decision = dict(row) if row is not None else None
    except sqlite3.Error:
        raise ValueError("registered method audit is unavailable") from None

    if not events or any(event.mode is not Mode.LIVE for event in events):
        raise ValueError("method evidence requires an all-live run")
    if not any(event.actor == "host" and event.event_type == "method_audit_registered"
               and event.mode is Mode.LIVE and event.payload_ref == audit_id for event in events):
        raise ValueError("method audit registration event is missing")
    if not any(event.actor == "host" and event.event_type == "method_audit_completed"
               and event.mode is Mode.LIVE and event.payload_ref == audit_id for event in events):
        raise ValueError("completed method audit event is missing")
    if not any(event.actor == "pi" and event.event_type in {"selection", "second_selection"}
               and event.payload_ref == spec.experiment_id for event in events):
        raise ValueError("parent Spec is not selected by the active run")
    if not any(event.actor == "runner" and event.event_type == "result"
               and event.payload_ref == parent.result_id for event in events):
        raise ValueError("parent Result is not owned by the active run")

    selection_event = any(
        event.actor == "pi" and event.event_type == "adaptive_followup_selected"
        and event.mode is Mode.LIVE and event.payload_ref == parent.result_id for event in events
    )
    if decision is None:
        if selection_event:
            raise ValueError("adaptive selection event has no persisted decision record")
        selection = {
            "schema_version": 1,
            "artifact_type": "nova.adaptive_selection_provenance.v1",
            "status": "not_recorded",
            "source": {"table": "adaptive_followup_decisions", "run_id": run_id},
        }
    else:
        try:
            packet = json.loads(decision["packet_json"])
            chosen = json.loads(decision["selection_json"])
        except (TypeError, json.JSONDecodeError):
            raise ValueError("persisted adaptive selection is malformed") from None
        if (decision["parent_result_id"] != parent.result_id or
                decision["choice"] != "method_sensitivity" or
                not isinstance(decision["reason"], str) or not decision["reason"].strip() or
                not isinstance(packet, dict) or packet.get("parent_result_id") != parent.result_id or
                not isinstance(chosen, dict) or chosen.get("choice") != "method_sensitivity" or
                chosen.get("reason") != decision["reason"] or not selection_event):
            raise ValueError("persisted adaptive selection does not match the method audit")
        if (_decision_json(packet) != decision["packet_json"] or
                _decision_json(chosen) != decision["selection_json"]):
            raise ValueError("persisted adaptive selection is not canonical")
        selection = {
            "schema_version": 1,
            "artifact_type": "nova.adaptive_selection_provenance.v1",
            "status": "recorded",
            "source": {
                "table": "adaptive_followup_decisions",
                "run_id": run_id,
                "event_type": "adaptive_followup_selected",
                "actor": "pi",
            },
            "choice": decision["choice"],
            "reason": decision["reason"],
            "packet": packet,
            "selection": chosen,
            "source_sha256": {
                "packet_json": _sha256(decision["packet_json"].encode("utf-8")),
                "selection_json": _sha256(decision["selection_json"].encode("utf-8")),
            },
        }

    return {
        "request": request,
        "audit_output": audit_output,
        "parent_result": parent,
        "parent_spec": spec,
        "events": events,
        "event_values": event_values,
        "spec_value": spec_raw,
        "parent_value": parent_raw,
        "review_value": review_value,
        "selection": selection,
    }


def _write_run_snapshot(snapshot: Mapping[str, Any], output: Path) -> Path:
    """Write only the already-scoped run events, parent Spec/Result, and review."""
    output = _safe_output(output)
    events = snapshot["event_values"]
    payloads = {
        "events.jsonl": b"".join(
            (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
            for item in events
        ),
        "specs.json": (json.dumps([snapshot["spec_value"]], sort_keys=True, indent=2) + "\n").encode(),
        "results.json": (json.dumps([snapshot["parent_value"]], sort_keys=True, indent=2) + "\n").encode(),
        "reviews.json": (json.dumps([snapshot["review_value"]] if snapshot["review_value"] else [],
                                     sort_keys=True, indent=2) + "\n").encode(),
    }
    for name, raw in payloads.items():
        _atomic_write(output / name, raw)
    manifest = {
        "schema_version": 1,
        "run_id": snapshot["request"]["run_id"],
        "mode": "live",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    counts = {
        "events.jsonl": len(events), "specs.json": 1, "results.json": 1,
        "reviews.json": int(snapshot["review_value"] is not None),
    }
    for name in RUN_FILES:
        raw = (output / name).read_bytes()
        manifest["files"][name] = {"sha256": _sha256(raw), "count": counts[name]}
    _atomic_write(output / "manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    return output


def _write(path: Path, raw: bytes, *, replace: bool = False) -> None:
    if path.exists() and not replace:
        raise ValueError("method export file already exists")
    fd, tmp = tempfile.mkstemp(prefix=".method-export-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if not replace and path.exists():
            raise ValueError("method export file already exists")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _pointer(value: Any, path: str) -> Any:
    current = value
    if path == "":
        return current
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("method evidence has an invalid JSON pointer")
    for item in path[1:].split("/"):
        token = item.replace("~1", "/").replace("~0", "~")
        try:
            current = current[token] if isinstance(current, dict) else current[int(token)]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("method evidence JSON pointer does not resolve") from None
    return current


def _verify_packet(body: Mapping[str, Any], digest: str, packet: Mapping[str, Any]) -> None:
    if packet.get("evidence_sha256") != digest or not isinstance(packet.get("references"), list):
        raise ValueError("method evidence citations do not match their artifact")
    for ref in packet["references"]:
        if not isinstance(ref, Mapping) or ref.get("evidence_sha256") != digest:
            raise ValueError("method evidence citation has a mismatched digest")
        target = _pointer(body, ref.get("json_pointer"))
        if "jid" in ref and (not isinstance(target, Mapping) or target.get("jid") != ref["jid"]):
            raise ValueError("candidate citation does not resolve to its stated JID")


def _verify_exports(output: Path, parent: Result, spec: ExperimentSpec,
                    payload_digest: str, source_payload: bytes) -> dict[str, Any]:
    specs_bytes = (output / "specs.json").read_bytes()
    results_bytes = (output / "results.json").read_bytes()
    specs, results = json.loads(specs_bytes), json.loads(results_bytes)
    science = json.loads((output / "science-artifacts.json").read_text(encoding="utf-8"))
    if (not isinstance(specs, list) or len(specs) != 1 or
            ExperimentSpec.from_dict(specs[0]).sha256 != spec.sha256):
        raise ValueError("exported Spec does not resolve to the registered parent")
    if not isinstance(results, list) or len(results) != 1 or results[0] != parent.to_dict():
        raise ValueError("exported Result does not resolve to the registered parent")
    result_refs = [item for item in science.get("results", []) if item.get("result_id") == parent.result_id]
    artifacts = [item for item in science.get("artifacts", [])
                 if item.get("artifact_id") == f"nova-result-payload:{payload_digest}"]
    if (len(result_refs) != 1 or result_refs[0].get("registered_spec_sha256") != spec.sha256 or
            f"nova-result-payload:{payload_digest}" not in result_refs[0].get("artifact_ids", []) or len(artifacts) != 1):
        raise ValueError("exported parent science payload reference is incomplete")
    copied = (output / artifacts[0]["exported_path"]).resolve()
    if (not _under(copied, output.resolve()) or copied.read_bytes() != source_payload or
            _sha256(copied.read_bytes()) != payload_digest):
        raise ValueError("copied parent science payload failed its checksum")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    results_hash = _sha256(results_bytes)
    if manifest.get("files", {}).get("results.json", {}).get("sha256") != results_hash:
        raise ValueError("exported parent Result file checksum is invalid")
    parent_ref = {
        "file": "results.json",
        "sha256": results_hash,
        "json_pointer": "/0",
        "result_id": parent.result_id,
        "experiment_id": parent.experiment_id,
        "spec_sha256": parent.spec_sha256,
        "dataset_sha256": parent.dataset_sha256,
    }
    resolved_parent = _pointer(results, parent_ref["json_pointer"])
    if any(resolved_parent.get(key) != parent_ref[key] for key in (
        "result_id", "experiment_id", "spec_sha256", "dataset_sha256"
    )):
        raise ValueError("parent Result citation does not resolve")
    return parent_ref


def _update_manifest(output: Path, audit_id: str, evidence_digest: str) -> None:
    path = output / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("run evidence manifest has no file checksums")
    for name, entry in files.items():
        file = (output / name).resolve()
        if not _under(file, output.resolve()) or not file.is_file() or _sha256(file.read_bytes()) != entry.get("sha256"):
            raise ValueError("run evidence export checksum verification failed")
    for name in ("science-artifacts.json", "method-audit.json", "method-evidence.json", "adaptive-selection.json"):
        raw = (output / name).read_bytes()
        files[name] = {"sha256": _sha256(raw), "count": 1}
    manifest["method_audit"] = {
        "audit_id": audit_id,
        "evidence_file": "method-audit.json",
        "evidence_sha256": evidence_digest,
        "citations_file": "method-evidence.json",
        "selection_file": "adaptive-selection.json",
    }
    _write(path, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(), replace=True)


def export_registered_method(audit_id: str, output: os.PathLike[str] | str | None = None) -> Path:
    """Export one completed method audit from its parent-only live run.

    This bounded handoff rejects runs that own extra Specs or science Results;
    it never registers or executes work.
    """
    out = _output_path(output)
    context = _context()
    db_path, run_id = context
    snapshot = _snapshot(db_path, run_id, audit_id)
    parent, spec = snapshot["parent_result"], snapshot["parent_spec"]

    from .holdout_bridge import _artifact_payload
    from .experiments import executor

    payload_digest, _payload = _artifact_payload(parent, spec, Path(executor.PROJECT_ROOT))
    payload_path = Path(executor.PROJECT_ROOT) / "runs" / f"science-payload-{payload_digest}.json"
    source_payload = payload_path.read_bytes()

    from .method_evidence import build_method_evidence, build_method_evidence_packet

    body = build_method_evidence(snapshot["request"], snapshot["audit_output"], parent, spec)
    body_bytes = (_canonical(body) + "\n").encode("utf-8")
    evidence_digest = _sha256(body_bytes)
    packet = dict(build_method_evidence_packet(body, evidence_digest))
    _verify_packet(body, evidence_digest, packet)
    selection_bytes = (_canonical(snapshot["selection"]) + "\n").encode("utf-8")

    _same_context(context)
    out = _output_path(out)
    out = _write_run_snapshot(snapshot, out)
    executor.export_science_artifacts(parent, out)
    parent_ref = _verify_exports(out, parent, spec, payload_digest, source_payload)
    packet.update({
        "evidence_file": "method-audit.json",
        "evidence_root_json_pointer": "",
        "parent_result_ref": parent_ref,
        "selection_ref": {
            "file": "adaptive-selection.json",
            "json_pointer": "",
            "sha256": _sha256(selection_bytes),
        },
    })
    packet_bytes = (_canonical(packet) + "\n").encode("utf-8")
    _write(out / "method-audit.json", body_bytes)
    _write(out / "method-evidence.json", packet_bytes)
    _write(out / "adaptive-selection.json", selection_bytes)

    if _sha256((out / "method-audit.json").read_bytes()) != evidence_digest:
        raise ValueError("method evidence artifact checksum verification failed")
    parsed_packet = json.loads((out / "method-evidence.json").read_text(encoding="utf-8"))
    _verify_packet(json.loads(body_bytes), evidence_digest, parsed_packet)
    if _sha256((out / "adaptive-selection.json").read_bytes()) != parsed_packet["selection_ref"]["sha256"]:
        raise ValueError("adaptive selection provenance checksum verification failed")
    _same_context(context)
    _update_manifest(out, audit_id, evidence_digest)
    return out


__all__ = ["export_registered_method"]
