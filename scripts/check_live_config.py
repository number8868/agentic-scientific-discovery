from pathlib import Path
import sys

def check(path="agents/opensource-live.yaml"):
    t=Path(path).read_text()
    # Comments document the required launcher environment; security checks
    # apply to actual YAML values, not prose such as "shell" or "codex-native".
    source="\n".join(line.split("#", 1)[0] for line in t.splitlines()).lower()
    bad=[x for x in ("os_env:","shell","terminal:","sol","fixture","gpt-reserve","api_key:","auth:") if x in source]
    req=["harness: codex","model: gpt-5.6-luna","async: false","nova.decision_tools.commit_initial_spec","nova.decision_tools.commit_next_spec","nova.decision_tools.register_initial_plan","nova.live_bridge.execute_live_registered_experiment","nova.decision_tools.submit_live_review","nova.decision_tools.submit_final_review","nova.decision_tools.freeze_final","holdout_experiment_id","Never execute a holdout","limit: 16"]
    miss=[x for x in req if x not in t]
    if "codex-native" in source: miss.append("SDK codex harness (native terminal forbidden)")
    if source.count("harness: codex")!=4 or source.count("model: gpt-5.6-luna")!=4: miss.append("four explicit Luna SDK executors")
    if "web_search" in source or "builtins:" in source: miss.append("no built-in web search")
    if "terminals:" in source: miss.append("no terminal declarations")
    if t.count("pass_history: true")!=3: miss.append("history passed to three bounded sub-agents")
    return {"ok":not(bad or miss),"forbidden":bad,"missing":miss,
            "required_runtime_env": {"HARNESS_CODEX_DISABLE_NATIVE_TOOLS": "1",
                                      "HARNESS_CODEX_ENABLE_WEB_SEARCH": "0"}}
if __name__=="__main__":
    r=check(sys.argv[1] if len(sys.argv)>1 else "agents/opensource-live.yaml"); print("live config: OK" if r["ok"] else r); raise SystemExit(0 if r["ok"] else 1)
