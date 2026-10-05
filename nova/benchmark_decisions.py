"""Frozen, discovery-only decision benchmark rubric.

This scores structural validity (allowed action, exact citation reference, and
claim tags). It does not judge whether prose is semantically accurate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CORPUS_PATH = Path(__file__).resolve().parents[1] / "docs" / "examples" / "decision_benchmark_v1.json"
ALLOWED_ACTIONS = frozenset({"threshold_sensitivity", "method_sensitivity", "stop"})
FROZEN_CORPUS_SHA256 = "b6902af180e303204352cc71e94e8a2770fca03c6e224c1cb744842b831a786a"


def load_corpus(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CORPUS_PATH).read_text(encoding="utf-8"))


def canonical_corpus_bytes(corpus: dict[str, Any] | None = None) -> bytes:
    value = load_corpus() if corpus is None else corpus
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def corpus_sha256(corpus: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(canonical_corpus_bytes(corpus)).hexdigest()


def fixed_decision(case: dict[str, Any]) -> dict[str, Any]:
    """Apply the preregistered threshold -> method -> stop rule to a packet."""
    actions = set(case["available_actions"])
    budget = case["remaining_experiment_slots"]
    if not case["available_citations"]:
        action = "stop"
    elif budget <= 0:
        action = "stop"
    elif "threshold_sensitivity" in actions:
        action = "threshold_sensitivity"
    elif "method_sensitivity" in actions:
        action = "method_sensitivity"
    else:
        action = "stop"
    return {
        "action": action,
        "citations": list(case["available_citations"]),
        "claim_tags": list(case["available_claim_tags"]),
    }


def score_decision(case: str | dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Return structural rubric results for one frozen case."""
    if isinstance(case, str):
        case_id = case
        item = next((item for item in load_corpus()["cases"] if item["id"] == case_id), None)
        if item is None:
            raise ValueError(f"unknown decision case: {case_id}")
        case = item
    else:
        case_id = case["id"]
    action = decision.get("action")
    citations = decision.get("citations")
    claim_tags = decision.get("claim_tags")
    action_is_well_formed = isinstance(action, str) and action in ALLOWED_ACTIONS
    if not isinstance(citations, list) or not all(isinstance(item, str) for item in citations):
        raise TypeError("citations must be a list of exact result-reference strings")
    if not isinstance(claim_tags, list) or not all(isinstance(item, str) for item in claim_tags):
        raise TypeError("claim_tags must be a list of strings")
    valid_action = action_is_well_formed and action in case["acceptable_actions"] and action in case["available_actions"]
    valid_citation = (set(citations) == set(case["required_result_refs"]) and
                      len(citations) == len(set(citations)))
    supported_tags = set(case["supported_claim_tags"])
    no_unsupported_claim_tags = all(tag in supported_tags for tag in claim_tags)
    return {
        "case_id": case_id,
        "action_valid": valid_action,
        "citation_valid": valid_citation,
        "no_unsupported_claim_tags": no_unsupported_claim_tags,
        "structural_pass": valid_action and valid_citation and no_unsupported_claim_tags,
        "scoring_scope": "structural_check_only_not_semantic_accuracy",
    }
