from pathlib import Path
import re,sys
def check(path="agents/opensource-live.yaml"):
    t=Path(path).read_text(); bad=[x for x in ("os_env:","shell","terminal:","sol","fixture","gpt-reserve","api_key:","auth:") if x in t.lower()]
    req=["harness: codex-native","model: gpt-5.6-luna","async: false","nova.decision_tools.commit_initial_spec","nova.decision_tools.commit_next_spec","nova.decision_tools.register_initial_plan","nova.live_bridge.execute_live_registered_experiment","nova.decision_tools.submit_live_review","limit: 16"]
    miss=[x for x in req if x not in t]
    if t.count("harness: codex-native")!=4 or t.count("model: gpt-5.6-luna")!=4: miss.append("four explicit Luna executors")
    if t.count("pass_history: true")!=3: miss.append("history passed to three bounded sub-agents")
    return {"ok":not(bad or miss),"forbidden":bad,"missing":miss}
if __name__=="__main__":
    r=check(sys.argv[1] if len(sys.argv)>1 else "agents/opensource-live.yaml"); print("live config: OK" if r["ok"] else r); raise SystemExit(0 if r["ok"] else 1)
