"""Frozen evidence-to-next-decision quality benchmark (discovery only).

Answers are independently scored, plus one preregistered action and exact citation
set. Numeric answer tolerance is specified per answer; booleans never count as numbers.
"""
from __future__ import annotations

import hashlib
import json
import math
import copy
from pathlib import Path
from typing import Any

CORPUS_PATH = Path(__file__).resolve().parents[1] / "docs" / "examples" / "quality_benchmark_v1.json"
FROZEN_CORPUS_SHA256 = "bfabe6cc46487e406deffdeec5c12797c00294021aeff2b181acc4c45f7c57eb"


def load_corpus() -> dict[str, Any]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _canonical(corpus: dict[str, Any] | None = None) -> bytes:
    obj = load_corpus() if corpus is None else corpus
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def corpus_sha256(corpus: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(_canonical(corpus)).hexdigest()


def visible_packet(case: str | dict[str, Any]) -> dict[str, Any]:
    """Return only case identity and arm-visible packet/task; never expose rubric."""
    if isinstance(case, str):
        case = next(x for x in load_corpus()["cases"] if x["id"] == case)
    return {"id": case["id"], "packet": copy.deepcopy(case["packet"])}


def _equal(got: Any, spec: dict[str, Any]) -> bool:
    want = spec["value"]
    if want is None or isinstance(want, (str, bool)):
        return type(got) is type(want) and got == want
    if isinstance(want, (int, float)):
        return type(got) in (int, float) and math.isfinite(got) and abs(got - want) <= spec.get("tolerance", 0)
    return False


def score_decision(case: str | dict[str, Any], decision: Any) -> dict[str, Any]:
    """Score safely: malformed decisions return zero rather than raising."""
    try:
        if isinstance(case, str):
            case = next((x for x in load_corpus()["cases"] if x["id"] == case), None)
        if not isinstance(case, dict) or not isinstance(decision, dict):
            raise ValueError
        if set(decision) != {"answers", "action", "citations"}:
            raise ValueError
        rubric = case["rubric"]
        answers = decision["answers"]
        action = decision["action"]
        citations = decision["citations"]
        if (not isinstance(answers, dict) or set(answers) != set(rubric["expected_answers"])
                or not isinstance(action, str) or not isinstance(citations, list)
                or not all(isinstance(c, str) for c in citations)):
            raise ValueError
        expected = rubric["expected_answers"]
        correct = sum(q in answers and _equal(answers[q], spec) for q, spec in expected.items())
        action_valid = action == rubric["expected_action"]
        citation_valid = len(citations) == len(set(citations)) and set(citations) == set(rubric["expected_citations"])
        total = len(expected)
        score = (correct + int(action_valid) + int(citation_valid)) / (total + 2)
        return {"quality_score": score, "exact_pass": score == 1.0,
                "answer_correct": correct, "answer_total": total,
                "action_valid": action_valid, "citation_valid": citation_valid}
    except Exception:
        n = len(case.get("rubric", {}).get("expected_answers", {})) if isinstance(case, dict) else 0
        return {"quality_score": 0.0, "exact_pass": False, "answer_correct": 0,
                "answer_total": n, "action_valid": False, "citation_valid": False}
