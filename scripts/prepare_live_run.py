#!/usr/bin/env python3
"""Prepare host-owned live context; never registers selection/result."""
import argparse, json, os, re, tempfile, uuid, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nova.contracts import Mode
from nova.storage import Storage

ROOT=Path(__file__).resolve().parents[1]
LIVE_CONTEXT_PATH=ROOT/".nova"/"live_context.json"
def active_dataset_sha256():
    # Lazy import keeps the secure preparer usable for checks without science
    # dependencies; production preparation still fails closed if A's data stack
    # or manifest is unavailable.
    from nova.experiments.executor import active_dataset_sha256 as read_hash
    return read_hash()
SAFE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
def prepare_live_run(db_path, run_id=None, objective="NOVA-MAT live study"):
    digest=active_dataset_sha256()
    db=Path(db_path).expanduser().resolve(); run=run_id or "live-"+uuid.uuid4().hex[:12]
    if not SAFE.fullmatch(run): raise ValueError("run-id must contain only safe identifier characters")
    if db in (Path("/"),Path.home()) or db.exists(): raise ValueError("unsafe or existing database target")
    db.parent.mkdir(parents=True,exist_ok=True)
    store=Storage(db).initialize(); os.chmod(db,0o600)
    store.append_event(run,"run_created",actor="host",mode=Mode.LIVE)
    store.append_event(run,"objective_registered",actor="host",mode=Mode.LIVE,payload_ref=objective)
    store.append_event(run,"hypothesis_frozen",actor="pi",mode=Mode.LIVE,payload_ref="H-001")
    nova=LIVE_CONTEXT_PATH.parent
    if nova.exists() and nova.is_symlink(): raise ValueError("live context directory must not be a symlink")
    nova.mkdir(mode=0o700,exist_ok=True); os.chmod(nova,0o700)
    if LIVE_CONTEXT_PATH.exists() and LIVE_CONTEXT_PATH.is_symlink(): raise ValueError("live context path must not be a symlink")
    context={"schema_version":1,"run_id":run,"mode":"live","db":str(db)}
    fd,tmp=tempfile.mkstemp(prefix=".live-context-",dir=str(nova)); os.fchmod(fd,0o600)
    with os.fdopen(fd,"w") as h: json.dump(context,h,sort_keys=True); h.flush(); os.fsync(h.fileno())
    os.replace(tmp,LIVE_CONTEXT_PATH); os.chmod(LIVE_CONTEXT_PATH,0o600)
    return dict(context,dataset_sha256=digest,context_path=str(LIVE_CONTEXT_PATH))
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--db",required=True); p.add_argument("--run-id"); a=p.parse_args(); print(json.dumps(prepare_live_run(a.db,a.run_id),sort_keys=True))
