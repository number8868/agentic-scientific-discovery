#!/usr/bin/env python3
"""Run the eight-turn, tightly scoped Omnigent Codex pilot for NOVA-MAT.

This is a low-level SDK host for B's registered live tools, not the YAML
multi-agent server. The host prepares B's live context, exposes one function
per role turn, and delegates every durable transition to nova.decision_tools
or nova.live_bridge. The Codex CLI must have its matching
``codex-code-mode-host`` binary beside it, or the caller may set
``CODEX_CODE_MODE_HOST_PATH`` to that binary; this runner forwards that one
non-secret path through Omnigent's otherwise filtered child environment.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNS = ROOT / "runs"
MODEL = "gpt-6-luna"
HARNESS = "omnigent.inner.codex_executor.CodexExecutor"
OMNIGENT_SDK_PIN = "0.16.0"
CODEX_APP_SERVER_OVERRIDES = ("features.code_mode_host=true", "features.code_mode=false")
CODE_MODE_HOST_PATH_ENV = "CODEX_CODE_MODE_HOST_PATH"
TURN_TIMEOUT_SECONDS = 120
MAX_ROLE_TURNS = 8
MAX_MODEL_TURNS = 16
MAX_TOOL_CALLS = 8
_SECRETISH = re.compile(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")

ROLE_ORDER = ("planner", "pi_initial", "runner_first", "skeptic", "pi_second", "runner_second",
              "skeptic_final", "pi_freeze")


class NoToolCallError(RuntimeError):
    """A completed model turn that emitted no function request or callback."""

    def __init__(self, role: str, tool_name: str):
        super().__init__(f"{role} completed without calling {tool_name}")
        self.role = role
        self.tool_name = tool_name


TOOLS: dict[str, dict[str, Any]] = {
    "planner": {
        "name": "register_initial_plan",
        "description": "Register the two fixed, bounded initial options and recommend family_screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "chosen_template": {"type": "string", "enum": ["family_screen"]},
                "selection_reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["chosen_template", "selection_reason"],
            "additionalProperties": False,
        },
    },
    "pi_initial": {
        "name": "commit_initial_spec",
        "description": "Approve the registered family_screen initial protocol.",
        "parameters": {
            "type": "object",
            "properties": {"chosen_template": {"type": "string", "enum": ["family_screen"]}},
            "required": ["chosen_template"],
            "additionalProperties": False,
        },
    },
    "runner_first": {
        "name": "execute_live_registered_experiment",
        "description": "Execute the host-registered initial experiment ID exactly once.",
        "parameters": {
            "type": "object",
            "properties": {"experiment_id": {"type": "string", "minLength": 1, "maxLength": 100}},
            "required": ["experiment_id"],
            "additionalProperties": False,
        },
    },
    "skeptic": {
        "name": "submit_live_review",
        "description": "Record one cautious, result-grounded concern and the bounded follow-up.",
        "parameters": {
            "type": "object",
            "properties": {
                "result_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "concern": {"type": "string", "minLength": 1, "maxLength": 1000},
                "recommended_template": {"type": "string", "enum": ["threshold_sensitivity"]},
            },
            "required": ["result_id", "concern", "recommended_template"],
            "additionalProperties": False,
        },
    },
    "pi_second": {
        "name": "commit_next_spec",
        "description": "Approve the registered threshold_sensitivity follow-up for the reviewed result.",
        "parameters": {
            "type": "object",
            "properties": {
                "result_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "recommended_template": {"type": "string", "enum": ["threshold_sensitivity"]},
            },
            "required": ["result_id", "recommended_template"],
            "additionalProperties": False,
        },
    },
    "runner_second": {
        "name": "execute_live_registered_experiment",
        "description": "Execute the host-registered threshold follow-up ID exactly once.",
        "parameters": {
            "type": "object",
            "properties": {"experiment_id": {"type": "string", "minLength": 1, "maxLength": 100}},
            "required": ["experiment_id"],
            "additionalProperties": False,
        },
    },
    "skeptic_final": {
        "name": "submit_final_review",
        "description": "Record the final cautious review of the completed threshold follow-up.",
        "parameters": {
            "type": "object",
            "properties": {
                "result_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "concern": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["result_id", "concern"],
            "additionalProperties": False,
        },
    },
    "pi_freeze": {
        "name": "freeze_final",
        "description": "Freeze the reviewed discovery protocol and derive, but do not execute, its holdout.",
        "parameters": {
            "type": "object",
            "properties": {
                "main_result_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "followup_result_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "explanation": {"type": "string", "maxLength": 500},
            },
            "required": ["main_result_id", "followup_result_id", "explanation"],
            "additionalProperties": False,
        },
    },
}


def _safe_text(value: str, limit: int = 500) -> str:
    return _SECRETISH.sub("[redacted]", value).replace("\x00", "")[:limit]


def _safe_args(args: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            safe[key] = _safe_text(value, 500)
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = "[omitted]"
    return safe


def _usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    cleaned = {key: int(value[key]) for key in ("input_tokens", "output_tokens", "total_tokens")
               if isinstance(value.get(key), (int, float)) and value[key] >= 0}
    return cleaned or None


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        data = value.to_dict()
    elif isinstance(value, Mapping):
        data = dict(value)
    else:
        raise TypeError("registered experiment did not return a canonical Result")
    if not isinstance(data, dict):
        raise TypeError("Result.to_dict() must return an object")
    return data


def _result_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in ("result_id", "experiment_id", "execution_status", "scientific_status")}


def _call_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        if "result_id" in value:
            return _result_summary(value)
        if "recommended_template" in value:
            return {key: value.get(key) for key in ("result_id", "experiment_id", "recommended_template")}
        if "candidate_tests" in value:
            return {"registered_templates": sorted({str(x.get("draft_spec", {}).get("template"))
                                                       for x in value.get("candidate_tests", [])
                                                       if isinstance(x, Mapping)})}
        return {key: value.get(key) for key in ("experiment_id", "chosen_template") if key in value}
    if isinstance(value, str):
        return {"id": _safe_text(value, 180)}
    return {"type": type(value).__name__}


def _default_api() -> dict[str, Callable[..., Any]]:
    from nova import decision_tools, live_bridge
    return {
        "register_initial_plan": decision_tools.register_initial_plan,
        "commit_initial_spec": decision_tools.commit_initial_spec,
        "execute_live_registered_experiment": live_bridge.execute_live_registered_experiment,
        "submit_live_review": decision_tools.submit_live_review,
        "commit_next_spec": decision_tools.commit_next_spec,
        "submit_final_review": decision_tools.submit_final_review,
        "freeze_final": decision_tools.freeze_final,
    }


class LivePilotHost:
    """Strict eight-step host that only accepts each role's one registered tool."""

    def __init__(self, database: Path, run_id: str, api: Mapping[str, Callable[..., Any]] | None = None):
        self.database = Path(database).resolve()
        self.run_id = run_id
        self.api = dict(api or _default_api())
        self.phase = 0
        self.tool_calls = 0
        self.aborted = False
        self.plan: dict[str, Any] | None = None
        self.initial_id: str | None = None
        self.first_result: dict[str, Any] | None = None
        self.review: dict[str, Any] | None = None
        self.second_id: str | None = None
        self.second_result: dict[str, Any] | None = None
        self.final_review: dict[str, Any] | None = None
        self.frozen: dict[str, Any] | None = None
        self.executed_ids: set[str] = set()

    @property
    def role(self) -> str | None:
        return ROLE_ORDER[self.phase] if self.phase < len(ROLE_ORDER) else None

    def _reject(self, message: str) -> None:
        self.aborted = True
        raise ValueError(message)

    def _storage(self):
        from nova.storage import Storage
        return Storage(self.database).initialize()

    def _registered_spec(self, experiment_id: str, template: str):
        spec = self._storage().read_spec(experiment_id)
        if spec is None or spec.template.value != template:
            self._reject("experiment ID is not registered for the expected template")
        return spec

    async def handle_tool(self, role: str, name: str, args: Any) -> dict[str, Any]:
        if self.aborted:
            raise ValueError("pilot is aborted; tool retries are disabled")
        self.tool_calls += 1
        if self.tool_calls > MAX_TOOL_CALLS:
            self._reject("pilot tool-call budget exceeded")
        if self.role != role:
            self._reject("tool call is out of role order")
        expected = TOOLS[role]["name"]
        if name != expected:
            self._reject("tool is not exposed to this role")
        schema = TOOLS[role]["parameters"]
        if not isinstance(args, dict) or set(args) != set(schema["required"]):
            self._reject("tool arguments do not match the registered schema")
        try:
            if role == "planner":
                if args["chosen_template"] != "family_screen":
                    self._reject("initial plan must recommend family_screen")
                reason = args["selection_reason"]
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
                    self._reject("planner rationale must be a short non-empty string")
                result = self.api["register_initial_plan"]("family_screen", reason.strip())
                candidates = result.get("candidate_tests", []) if isinstance(result, Mapping) else []
                templates = {x.get("draft_spec", {}).get("template") for x in candidates if isinstance(x, Mapping)}
                if (templates != {"family_screen", "threshold_sensitivity"}
                        or result.get("chosen_proposal_id") != "proposal-family_screen"):
                    self._reject("Planner did not register the two bounded options")
                self.plan = dict(result)
                response = {"plan_registered": True, "templates": sorted(templates),
                            "chosen_proposal_id": "proposal-family_screen"}
            elif role == "pi_initial":
                if not self.plan or args["chosen_template"] != "family_screen":
                    self._reject("PI initial approval must match the registered plan")
                experiment_id = self.api["commit_initial_spec"]("family_screen")
                if not isinstance(experiment_id, str) or not experiment_id:
                    self._reject("PI tool did not return a registered experiment ID")
                self._registered_spec(experiment_id, "family_screen")
                self.initial_id = experiment_id
                response = {"experiment_id": experiment_id, "template": "family_screen", "approved": True}
            elif role == "runner_first":
                experiment_id = args["experiment_id"]
                if experiment_id != self.initial_id or experiment_id in self.executed_ids:
                    self._reject("Runner may execute only the selected initial ID, once")
                self._registered_spec(experiment_id, "family_screen")
                self.executed_ids.add(experiment_id)
                value = await asyncio.wait_for(
                    asyncio.to_thread(self.api["execute_live_registered_experiment"], experiment_id),
                    timeout=TURN_TIMEOUT_SECONDS,
                )
                data = _result_dict(value)
                if data.get("experiment_id") != experiment_id or data.get("execution_status") != "completed" or data.get("error"):
                    self._reject("registered initial experiment did not return a completed Result")
                self.first_result = data
                response = data
            elif role == "skeptic":
                result_id, concern = args["result_id"], args["concern"]
                if not self.first_result or result_id != self.first_result.get("result_id"):
                    self._reject("review must cite the actual first result")
                if not isinstance(concern, str) or not concern.strip() or len(concern) > 1000:
                    self._reject("review concern must be bounded and non-empty")
                if args["recommended_template"] != "threshold_sensitivity":
                    self._reject("MVP review must recommend threshold_sensitivity")
                result = self.api["submit_live_review"](result_id, concern.strip(), "threshold_sensitivity")
                if (not isinstance(result, Mapping) or result.get("result_id") != result_id
                        or result.get("recommended_template") != "threshold_sensitivity"):
                    self._reject("review did not bind to the first result")
                self.review = dict(result)
                response = self.review
            elif role == "pi_second":
                result_id = args["result_id"]
                if (not self.first_result or not self.review or result_id != self.first_result.get("result_id")
                        or args["recommended_template"] != "threshold_sensitivity"):
                    self._reject("PI follow-up approval must match the reviewed first result")
                experiment_id = self.api["commit_next_spec"](result_id, "threshold_sensitivity")
                if not isinstance(experiment_id, str) or not experiment_id:
                    self._reject("PI follow-up tool did not return a registered ID")
                spec = self._registered_spec(experiment_id, "threshold_sensitivity")
                if spec.parent_result_id != result_id or spec.review_id != result_id:
                    self._reject("follow-up spec is not linked to the actual result and review")
                self.second_id = experiment_id
                response = {"experiment_id": experiment_id, "template": "threshold_sensitivity",
                            "parent_result_id": result_id, "review_id": result_id, "approved": True}
            else:
                if role == "skeptic_final":
                    result_id, concern = args["result_id"], args["concern"]
                    if not self.second_result or result_id != self.second_result.get("result_id"):
                        self._reject("final review must cite the actual follow-up result")
                    if not isinstance(concern, str) or not concern.strip() or len(concern) > 500:
                        self._reject("final review concern must be bounded and non-empty")
                    result = self.api["submit_final_review"](result_id, concern.strip())
                    if (not isinstance(result, Mapping) or result.get("result_id") != result_id
                            or result.get("recommended_template") is not None):
                        self._reject("final review did not bind to the follow-up result")
                    self.final_review = dict(result)
                    response = self.final_review
                elif role == "pi_freeze":
                    main_id = args["main_result_id"]
                    followup_id = args["followup_result_id"]
                    explanation = args["explanation"]
                    if (not self.first_result or not self.second_result or not self.final_review
                            or main_id != self.first_result.get("result_id")
                            or followup_id != self.second_result.get("result_id")):
                        self._reject("final freeze must follow both results and the final review")
                    if not isinstance(explanation, str) or len(explanation) > 500:
                        self._reject("final explanation must be bounded")
                    result = self.api["freeze_final"](main_id, followup_id, explanation.strip())
                    if (not isinstance(result, Mapping) or not result.get("frozen_protocol_id")
                            or not result.get("holdout_experiment_id")):
                        self._reject("final freeze did not return a frozen protocol and holdout ID")
                    self.frozen = dict(result)
                    response = self.frozen
                else:
                    experiment_id = args["experiment_id"]
                    if experiment_id != self.second_id or experiment_id in self.executed_ids:
                        self._reject("Runner may execute only the selected follow-up ID, once")
                    spec = self._registered_spec(experiment_id, "threshold_sensitivity")
                    if not self.first_result or spec.parent_result_id != self.first_result.get("result_id"):
                        self._reject("follow-up ID is not linked to the first result")
                    self.executed_ids.add(experiment_id)
                    value = await asyncio.wait_for(
                        asyncio.to_thread(self.api["execute_live_registered_experiment"], experiment_id),
                        timeout=TURN_TIMEOUT_SECONDS,
                    )
                    data = _result_dict(value)
                    if data.get("experiment_id") != experiment_id or data.get("execution_status") != "completed" or data.get("error"):
                        self._reject("registered follow-up did not return a completed Result")
                    self.second_result = data
                    response = data
            self.phase += 1
            return response if isinstance(response, dict) else dict(response)
        except Exception:
            self.aborted = True
            raise

    def context_for(self, role: str) -> str:
        if role == "planner":
            return ("Objective: compare the discovery-snapshot joint bandgap-and-ehull screen pass rates for oxide and "
                    "chalcogenide families. The primary delta is a pass-rate difference, not a missingness measure. "
                    "Hypothesis H-001 is frozen. The only initial options are the "
                    "host-built family_screen and threshold_sensitivity protocols. Recommend family_screen "
                    "as the required initial protocol and briefly explain the bounded rationale.")
        if role == "pi_initial":
            return "Review this registered two-option plan and approve the selected family_screen initial protocol:\n" + _compact(self.plan)
        if role == "runner_first":
            return (f"Execute only this selected registered experiment ID: {self.initial_id}. "
                    f"Call the function with exactly this JSON parameter: {{\"experiment_id\": \"{self.initial_id}\"}}. "
                    "After the tool succeeds, reply with only a short ACK; do not repeat the Result.")
        if role == "skeptic":
            result, payload = self._stored_result_and_payload(self.first_result["result_id"])
            return ("Review the actual stored first Result and its complete scientific payload. Metric clarification: "
                    "delta and resampling_interval are the difference and interval for the joint inclusive "
                    "bandgap-plus-ehull screen pass rate; they are not missingness metrics. The observed group "
                    "coverage values are " + _coverage_summary(result) + ". Refer to missingness only through the "
                    "separate missingness_interval field. Do not relabel delta as missingness. State one cautious, "
                    "specific limitation grounded in these values. Recommend threshold_sensitivity. Do not claim "
                    "causality or generalize beyond this snapshot.\nRESULT:\n" + _compact(result) + "\nFULL_SCIENCE_PAYLOAD:\n" + _compact(payload))
        if role == "pi_second":
            result = self._storage().get_result(self.first_result["result_id"])
            review = self._storage().get_review(self.first_result["result_id"])
            result_data = result.to_dict()
            return ("Review the persisted first Result and Skeptic packet. Metric clarification: delta is the "
                    "difference in joint inclusive bandgap-plus-ehull screen pass rate, not missingness. The "
                    "observed group coverage values are " + _coverage_summary(result_data) + "; missingness is "
                    "represented separately by missingness_interval. Approve the fixed registered "
                    "threshold_sensitivity follow-up for this result.\nRESULT:\n" + _compact(result.to_dict()) +
                    "\nREVIEW:\n" + _compact(review.to_dict()))
        if role == "runner_second":
            return (f"Execute only the approved registered follow-up experiment ID: {self.second_id}. "
                    f"Call the function with exactly this JSON parameter: {{\"experiment_id\": \"{self.second_id}\"}}. "
                    "After the tool succeeds, reply with only a short ACK; do not repeat the Result.")
        if role == "skeptic_final":
            if not self.second_result:
                raise ValueError("final review has no follow-up Result")
            return ("Review the completed threshold follow-up Result conservatively. State one bounded final concern "
                    "and whether the preregistered discovery protocol is ready to freeze. Call submit_final_review "
                    "with the actual result ID and your own concise concern. Do not propose or execute a holdout.\n"
                    "RESULT:\n" + _compact(self.second_result))
        if role == "pi_freeze":
            return ("Review the two completed discovery Results and the final Skeptic review. Call freeze_final with "
                    "the exact primary and follow-up result IDs and a concise explanation. This only freezes the "
                    "protocol and derives a holdout ID; never execute the holdout.\nPRIMARY:\n" +
                    _compact(self.first_result) + "\nFOLLOWUP:\n" + _compact(self.second_result) +
                    "\nFINAL_REVIEW:\n" + _compact(self.final_review))
        raise ValueError("unknown role")

    def _stored_result_and_payload(self, result_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        result = self._storage().get_result(result_id)
        if result is None:
            raise ValueError("first Result is not persisted")
        root_runs = (ROOT / "runs").resolve()
        payload_ids = [x.partition(":")[2] for x in result.artifact_ids if x.startswith("nova-result-payload:")]
        path_refs = [x.partition(":")[2] for x in result.artifact_ids if x.startswith("nova-artifact-path:")]
        if len(payload_ids) != 1 or len(path_refs) != 1:
            raise ValueError("first Result has no unique full science payload")
        path = (ROOT / path_refs[0]).resolve()
        if path != root_runs / f"science-payload-{payload_ids[0]}.json" or not path.is_file():
            raise ValueError("science payload path is outside the registered runs artifact")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != payload_ids[0]:
            raise ValueError("science payload hash does not match its registered ID")
        return result.to_dict(), json.loads(body.decode("utf-8"))


def _compact(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _coverage_summary(result: Mapping[str, Any]) -> str:
    groups = result.get("groups_summary", [])
    if not isinstance(groups, (list, tuple)):
        return "unavailable"
    values = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        coverage = group.get("coverage")
        if isinstance(coverage, (int, float)):
            values.append(f"{group.get('group', 'group')}={coverage:.1%}")
    return ", ".join(values) if values else "unavailable"


def _new_codex_executor(executor_type: Any, cwd: str, sdk_version: str, model: str = MODEL) -> Any:
    if sdk_version != OMNIGENT_SDK_PIN:
        raise RuntimeError(f"private Codex config override requires omnigent=={OMNIGENT_SDK_PIN}")
    executor = executor_type(cwd=cwd, model=model, enable_web_search=False,
                             disable_native_tools=True, skills_filter="none")
    # Pinned Omnigent 0.16.0 internal API: CodexExecutor passes this private
    # list into _CodexAppServerSession; _start_unchecked translates each entry
    # to `app-server -c <value>` before spawning the app-server process.
    overrides = getattr(executor, "_codex_config_overrides", None)
    if not isinstance(overrides, list):
        raise RuntimeError("Omnigent 0.16.0 CodexExecutor config override API changed")
    for override in CODEX_APP_SERVER_OVERRIDES:
        if override not in overrides:
            overrides.append(override)

    # Omnigent's clean child environment intentionally strips arbitrary CODEX_*
    # values. Forward only this explicitly requested, non-secret executable
    # path, which Codex 0.160 uses to locate the separately packaged host.
    host_override = os.environ.get(CODE_MODE_HOST_PATH_ENV)
    if host_override:
        host_path = Path(host_override).expanduser()
        if not host_path.is_file():
            raise RuntimeError(f"{CODE_MODE_HOST_PATH_ENV} does not name a file")
        if os.name != "nt" and not os.access(host_path, os.X_OK):
            raise RuntimeError(f"{CODE_MODE_HOST_PATH_ENV} is not executable")
        child_env = getattr(executor, "_env", None)
        if not isinstance(child_env, dict):
            raise RuntimeError("Omnigent 0.16.0 CodexExecutor environment API changed")
        child_env[CODE_MODE_HOST_PATH_ENV] = str(host_path.resolve())
    return executor


class JsonlAudit:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("x", encoding="utf-8")

    def write(self, event: str, **fields: Any) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        self._handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _repair_instruction(role: str, tool: Mapping[str, Any], host: LivePilotHost) -> str:
    authored_argument_instruction = ""
    if role == "planner":
        example = {"chosen_template": "family_screen"}
        authored_argument_instruction = (
            "Write your own concise bounded rationale in the required selection_reason field. "
        )
    elif role == "pi_initial":
        example = {"chosen_template": "family_screen"}
    elif role in {"runner_first", "runner_second"}:
        experiment_id = host.initial_id if role == "runner_first" else host.second_id
        if not experiment_id:
            raise RuntimeError("cannot repair Runner turn without a registered experiment ID")
        example = {"experiment_id": experiment_id}
    elif role == "skeptic":
        if not host.first_result:
            raise RuntimeError("cannot repair Skeptic turn without the actual first Result")
        example = {
            "result_id": host.first_result["result_id"],
            "recommended_template": "threshold_sensitivity",
        }
        authored_argument_instruction = (
            "Write the required concern yourself from the supplied actual Result and scientific payload, using its "
            "counts, delta, and interval. Do not copy a generic limitation or use a prewritten concern. "
        )
    elif role == "skeptic_final":
        if not host.second_result:
            raise RuntimeError("cannot repair final review without the follow-up Result")
        example = {"result_id": host.second_result["result_id"]}
        authored_argument_instruction = "Write the final concern yourself from the actual follow-up Result. "
    elif role == "pi_freeze":
        if not host.first_result or not host.second_result:
            raise RuntimeError("cannot repair final freeze without both Results")
        example = {"main_result_id": host.first_result["result_id"],
                   "followup_result_id": host.second_result["result_id"], "explanation": ""}
    else:
        if not host.first_result:
            raise RuntimeError("cannot repair PI follow-up turn without the actual first Result")
        example = {
            "result_id": host.first_result["result_id"],
            "recommended_template": "threshold_sensitivity",
        }
    return (
        "REPAIR REQUIRED: your previous reply completed without invoking a function. "
        f"Now invoke the exposed function `{tool['name']}` exactly once; a text response or ACK does not count. "
        "Use this exact registered argument schema, include every required field, and keep the fixed values below. "
        f"{authored_argument_instruction}"
        f"JSON Schema: {_compact(tool['parameters'])}\n"
        f"Fixed argument values: {_compact(example)}\n"
        "Do not add fields, change registered IDs, or claim completion until the function returns."
    )


async def _consume_role_turn(executor: Any, host: LivePilotHost, audit: JsonlAudit, role: str,
                            turn_number: int, timeout: int, *, role_turn: int | None = None,
                            role_attempt: int = 1, repair: bool = False, model: str = MODEL) -> dict[str, Any]:
    from omnigent.inner.executor import ExecutorConfig, ExecutorError, ToolCallComplete, ToolCallRequest, TurnComplete

    phase_before = host.phase
    if host.aborted:
        raise RuntimeError("pilot is aborted; role turn cannot start")
    tool = copy.deepcopy(TOOLS[role])
    if role in {"runner_first", "runner_second"}:
        registered_id = host.initial_id if role == "runner_first" else host.second_id
        if not registered_id:
            raise RuntimeError("Runner turn has no host-selected registered ID")
        tool["parameters"]["properties"]["experiment_id"]["enum"] = [registered_id]
    session_id = f"nova-{host.run_id}-{turn_number}-{uuid.uuid4().hex[:8]}"
    callback_count = 0

    async def callback(name: str, args: dict[str, Any]) -> dict[str, Any]:
        nonlocal callback_count
        callback_count += 1
        if callback_count != 1:
            host.aborted = True
            raise ValueError("exactly one function call is permitted in each role turn")
        return await host.handle_tool(role, name, args)

    executor._tool_executor = callback
    user_content = host.context_for(role)
    if repair:
        user_content += "\n\n" + _repair_instruction(role, tool, host)
    messages = [{"role": "user", "content": user_content, "session_id": session_id}]
    config = ExecutorConfig(model=model, max_tokens=700, extra={"reasoning_effort": "low"})
    state: dict[str, Any] = {"request_count": 0, "complete_count": 0, "tool_status": None,
                             "usage": None, "response": None, "turn_completed": False}

    async def consume() -> None:
        async for event in executor.run_turn(messages=messages, tools=[tool],
        system_prompt=("You are the " + role + " role in a bounded scientific workflow. "
                       "Use only the one registered function tool. Call it exactly once with "
                       "schema-compliant values, then stop. Never claim a computation ran "
                       "unless the Runner tool returned its Result. Runner turns must use "
                       "the literal registered experiment_id from the user message and finish "
                       "with only a short ACK, without repeating the tool Result."), config=config):
            if isinstance(event, ToolCallRequest):
                state["request_count"] += 1
                audit.write("ToolCallRequest", turn=turn_number, role_turn=role_turn or turn_number,
                            role_attempt=role_attempt, role=role, call_id=_call_id(event.metadata),
                            tool=event.name, args=_safe_args(event.args))
                if event.name != tool["name"]:
                    host.aborted = True
                    raise ValueError("Codex requested a tool outside this role allowlist")
            elif isinstance(event, ToolCallComplete):
                state["complete_count"] += 1
                state["tool_status"] = getattr(event.status, "value", str(event.status))
                audit.write("ToolCallComplete", turn=turn_number, role_turn=role_turn or turn_number,
                            role_attempt=role_attempt, role=role,
                            call_id=_call_id(event.metadata), tool=event.name,
                            status=state["tool_status"], summary=_call_summary(event.result),
                            error=_safe_text(event.error, 180) if event.error else None)
            elif isinstance(event, TurnComplete):
                state["turn_completed"] = True
                state["usage"] = _usage(event.usage)
                state["response"] = _safe_text(event.response or "", 320)
            elif isinstance(event, ExecutorError):
                state["usage"] = _usage(event.usage)
                audit.write("ExecutorError", turn=turn_number, role_turn=role_turn or turn_number,
                            role_attempt=role_attempt, role=role,
                            error_type="executor_error", summary=_safe_text(event.message, 180))
                raise RuntimeError("Codex executor reported an error")

    failure: Exception | None = None
    status = "turn_error"
    try:
        await asyncio.wait_for(consume(), timeout=timeout)
        if state["request_count"] == 0 and state["complete_count"] == 0 and callback_count == 0:
            if host.phase != phase_before or host.aborted:
                status = "no_tool_call_state_changed"
            elif state["turn_completed"]:
                status = "no_tool_call"
            else:
                status = "missing_turn_complete"
        elif (callback_count != 1 or state["request_count"] != 1 or state["complete_count"] != 1
              or state["tool_status"] != "success"):
            status = "tool_call_incomplete"
        elif not state["turn_completed"]:
            status = "missing_turn_complete"
        elif host.aborted:
            status = "host_aborted"
        else:
            status = "success"
    except asyncio.TimeoutError:
        status = "timeout"
        host.aborted = True
        try:
            await asyncio.wait_for(executor.interrupt_session(session_id), timeout=2)
        except Exception:
            pass
        failure = TimeoutError(f"Codex {role} turn exceeded {timeout} seconds")
    except Exception as exc:
        status = "executor_error"
        failure = exc
        host.aborted = True
    finally:
        try:
            await asyncio.wait_for(executor.close_session(session_id), timeout=10)
        except Exception:
            pass
        observed = {"turn": turn_number, "role_turn": role_turn or turn_number,
                    "role_attempt": role_attempt, "repair_attempt": repair, "role": role,
                    "model": model, "harness": HARNESS,
                    "response_summary": state["response"], "usage": state["usage"],
                    "request_count": state["request_count"], "complete_count": state["complete_count"],
                    "callback_count": callback_count, "tool_status": state["tool_status"], "status": status}
        audit.write("ModelTurnObserved", **observed)

    if failure is not None:
        host.aborted = True
        raise failure
    if status == "no_tool_call":
        # This is the sole recoverable state: no callback or tool events ran,
        # the host phase is untouched, and the host remains usable.
        raise NoToolCallError(role, tool["name"])
    if status != "success":
        host.aborted = True
        raise RuntimeError(f"{role} turn did not complete exactly one successful registered tool call ({status})")
    audit.write("ModelTurnComplete", **observed)
    return observed


async def _run_role_with_repair(executor: Any, host: LivePilotHost, audit: JsonlAudit,
                                role: str, role_turn: int, first_model_turn: int,
                                timeout: int, model: str = MODEL) -> tuple[dict[str, Any], int]:
    """Run one host role, permitting a single repair only for a clean no-tool reply."""
    phase_before = host.phase
    for role_attempt in (1, 2):
        model_turn = first_model_turn + role_attempt - 1
        if model_turn > MAX_MODEL_TURNS:
            host.aborted = True
            raise RuntimeError("pilot model-turn budget exceeded")
        try:
            observed = await _consume_role_turn(
                executor, host, audit, role, model_turn, timeout,
                role_turn=role_turn, role_attempt=role_attempt, repair=role_attempt == 2,
                model=model,
            )
        except NoToolCallError:
            if (role_attempt == 1 and host.phase == phase_before and not host.aborted
                    and role_turn == phase_before + 1):
                audit.write("NoToolCallRepairScheduled", turn=model_turn, role_turn=role_turn,
                            role_attempt=2, role=role, tool=TOOLS[role]["name"],
                            host_phase=host.phase)
                continue
            host.aborted = True
            raise
        return observed, model_turn + 1
    host.aborted = True
    raise RuntimeError(f"{role} exhausted its one no-tool repair attempt")


def _call_id(metadata: Any) -> str | None:
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("call_id") or metadata.get("id")
    return _safe_text(str(value), 120) if value is not None else None


@contextmanager
def _minimal_codex_config():
    marker = object()
    previous: str | object = os.environ.get("HARNESS_CODEX_MINIMAL_CONFIG", marker)
    os.environ["HARNESS_CODEX_MINIMAL_CONFIG"] = "1"
    try:
        yield
    finally:
        if previous is marker:
            os.environ.pop("HARNESS_CODEX_MINIMAL_CONFIG", None)
        else:
            os.environ["HARNESS_CODEX_MINIMAL_CONFIG"] = str(previous)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _check_live_platform() -> None:
    """Require a POSIX runtime for the SDK process/session boundary."""
    if os.name != "posix":
        raise RuntimeError(
            "The live Codex pilot requires a POSIX runtime (Linux/WSL or macOS); "
            "Windows native CODEX_HOME permission checks are unsupported."
        )


def _export(database: Path, run_id: str, run_dir: Path, turns: list[dict[str, Any]],
            audit_path: Path, error: str | None, model: str = MODEL) -> Path | None:
    import hashlib
    import sqlite3
    from nova.evidence import export_run
    from nova.experiments.executor import export_science_artifacts
    from nova.storage import Storage

    if not database.is_file():
        return None
    evidence_dir = run_dir / "evidence"
    exported = export_run(database, run_id, evidence_dir)
    store = Storage(database).initialize()
    results = store.list_results()
    for result in results:
        export_science_artifacts(result, exported)
    with sqlite3.connect(database) as db:
        try:
            row = db.execute(
                "SELECT plan_json, review_json FROM decision_packets WHERE run_id=?", (run_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
    decisions = {
        "run_id": run_id,
        "plan": json.loads(row[0]) if row and row[0] else None,
        "review": json.loads(row[1]) if row and row[1] else None,
    }
    decisions_path = exported / "decisions.json"
    decisions_bytes = (_compact(decisions) + "\n").encode("utf-8")
    decisions_path.write_bytes(decisions_bytes)
    audit_bytes = audit_path.read_bytes()
    observed_turns: list[dict[str, Any]] = []
    for line in audit_bytes.decode("utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "ModelTurnObserved":
            observed_turns.append({key: value for key, value in record.items() if key not in {"at", "event"}})
    if observed_turns:
        turns = observed_turns
    portable_audit_path = exported / "model-audit.jsonl"
    portable_audit_path.write_bytes(audit_bytes)
    usage_totals: dict[str, int] = {}
    for turn in turns:
        for key, amount in (turn.get("usage") or {}).items():
            usage_totals[key] = usage_totals.get(key, 0) + amount
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": "live",
        "model": model,
        "harness": HARNESS,
        "omnigent_sdk_version": OMNIGENT_SDK_PIN,
        "native_tools_disabled": True,
        "web_search_disabled": True,
        "skills_filter": "none",
        "app_server_config_overrides": list(CODEX_APP_SERVER_OVERRIDES),
        "turn_limit": MAX_MODEL_TURNS,
        "role_limit": MAX_ROLE_TURNS,
        "tool_call_limit": MAX_TOOL_CALLS,
        "turns": turns,
        "usage_total": usage_totals or None,
        "result_ids": [result.result_id for result in results],
        "science_artifact_manifest": "science-artifacts.json",
        "files": {
            "model-audit.jsonl": {"sha256": hashlib.sha256(audit_bytes).hexdigest(), "size_bytes": len(audit_bytes)},
            "decisions.json": {"sha256": hashlib.sha256(decisions_bytes).hexdigest(), "size_bytes": len(decisions_bytes)},
        },
        "model_audit": "model-audit.jsonl",
        "decisions": "decisions.json",
        "error_summary": _safe_text(error, 300) if error else None,
    }
    (exported / "pilot-manifest.json").write_text(_compact(manifest) + "\n", encoding="utf-8")
    return exported


async def _run_six_turns(database: Path, run_id: str, audit: JsonlAudit,
                        timeout: int = TURN_TIMEOUT_SECONDS, model: str = MODEL) -> tuple[LivePilotHost, list[dict[str, Any]]]:
    from importlib.metadata import version as package_version
    from omnigent.inner.codex_executor import CodexExecutor

    host = LivePilotHost(database, run_id)
    turns: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="nova-codex-cwd-", dir="/tmp") as model_cwd:
        executor = _new_codex_executor(CodexExecutor, model_cwd, package_version("omnigent"), model=model)
        try:
            model_turn = 1
            for role_turn, role in enumerate(ROLE_ORDER, start=1):
                if role_turn > MAX_ROLE_TURNS:
                    raise RuntimeError("pilot role-turn budget exceeded")
                observed, model_turn = await _run_role_with_repair(
                    executor, host, audit, role, role_turn, model_turn, timeout,
                    model=model,
                )
                turns.append(observed)
            if host.phase != MAX_ROLE_TURNS or host.tool_calls != MAX_TOOL_CALLS:
                raise RuntimeError("pilot did not complete its exact eight-turn protocol")
        finally:
            await executor.close()
    return host, turns


def run_pilot(database: Path, run_id: str | None = None, timeout: int = TURN_TIMEOUT_SECONDS,
              model: str = MODEL) -> Path:
    _check_live_platform()
    if timeout < 1 or timeout > TURN_TIMEOUT_SECONDS:
        raise ValueError("turn timeout must be between 1 and 120 seconds")
    database = database if database.is_absolute() else ROOT / database
    database = database.resolve()
    if not _inside(database, RUNS.resolve()) or database == RUNS.resolve():
        raise ValueError("database must be a new file under the project runs directory")
    run_dir = database.parent
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "model-audit.jsonl"
    if database.exists() or audit_path.exists() or (run_dir / "evidence").exists():
        raise FileExistsError("database, audit, and evidence targets must be new")
    context_path = ROOT / ".nova" / "live_context.json"
    if context_path.exists():
        raise FileExistsError("a NOVA live context already exists; clear or archive it before starting a new run")

    from scripts.prepare_live_run import prepare_live_run
    prepared = prepare_live_run(database, run_id=run_id)
    actual_run_id = prepared["run_id"]
    audit = JsonlAudit(audit_path)
    turns: list[dict[str, Any]] = []
    host: LivePilotHost | None = None
    error_summary: str | None = None
    audit.write("PilotStarted", run_id=actual_run_id, model=model, harness=HARNESS,
                native_tools_disabled=True, web_search_disabled=True, skills_filter="none")
    try:
        with _minimal_codex_config():
            host, turns = asyncio.run(_run_six_turns(database, actual_run_id, audit, timeout, model=model))
    except Exception as exc:
        error_summary = f"{type(exc).__name__}: {_safe_text(str(exc), 220)}"
        audit.write("PilotFailed", run_id=actual_run_id, error_summary=error_summary)
        raise
    finally:
        audit.write("PilotFinished", run_id=actual_run_id, completed=error_summary is None)
        audit.close()
        try:
            _export(database, actual_run_id, run_dir, turns, audit_path, error_summary, model=model)
        except Exception:
            if error_summary is None:
                raise
    return run_dir / "evidence"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="new SQLite path under runs/")
    parser.add_argument("--run-id", help="optional safe NOVA run identifier")
    parser.add_argument("--turn-timeout", type=int, default=TURN_TIMEOUT_SECONDS)
    parser.add_argument("--model", default=MODEL, help="explicit model name for all eight role turns")
    args = parser.parse_args(argv)
    if not isinstance(args.model, str) or not args.model.strip() or any(c in args.model for c in "\r\n\x00"):
        parser.error("--model must be a non-empty single-line model name")
    evidence = run_pilot(args.database, args.run_id, args.turn_timeout, args.model.strip())
    print(json.dumps({"status": "completed", "evidence": str(evidence)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
