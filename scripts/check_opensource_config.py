"""Dependency-free static checks for the open-source fixture YAML."""
from pathlib import Path
import re
import sys

CALLABLE = "nova.omnigent_bridge.execute_fixture_registered_experiment"

def check(path="agents/opensource.yaml"):
    text = Path(path).read_text(encoding="utf-8")
    required = ["name: nova-mat-opensource-h2-fixture", "harness: codex-native", "model: gpt-5.6-luna", "async: false",
                "type: agent", "callable: " + CALLABLE, "limit_tool_calls:", "limit: 16",
                "mode=fixture", "Planner", "Skeptic"]
    missing = [x for x in required if x not in text]
    forbidden = [x for x in ("os_env:", "terminals:", "shell", "terminal:", "DATABRICKS_TOKEN", "api_key:", "module:", "auth:", "sol", "gpt-reserve") if x in text.lower()]
    if re.search(r"^\s+harness:\s*codex\s*$", text, re.MULTILINE):
        forbidden.append("harness: codex")
    # Exactly one function tool, and it must have a closed experiment_id object.
    # Policy handlers also have type=function; count callable declarations,
    # which is the relevant tool surface.
    function_count = len(re.findall(r"^\s+callable:\s*\S+", text, re.MULTILINE))
    if function_count != 1:
        missing.append("exactly one function tool")
    if "additionalProperties: false" not in text or "required: [experiment_id]" not in text:
        missing.append("closed experiment_id parameters")
    if text.count("harness: codex-native") != 4 or text.count("model: gpt-5.6-luna") != 4:
        missing.append("root and all three sub-agents must explicitly use codex-native/gpt-5.6-luna")
    if forbidden:
        missing.extend("forbidden: " + x for x in forbidden)
    return {"ok": not missing, "missing": missing, "function_tools": function_count, "callable": CALLABLE}

def main(argv=None):
    result = check((argv or sys.argv[1:] or ["agents/opensource.yaml"])[0])
    if not result["ok"]:
        print("invalid open-source config: " + "; ".join(result["missing"]), file=sys.stderr)
        return 1
    print("open-source fixture config: OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
