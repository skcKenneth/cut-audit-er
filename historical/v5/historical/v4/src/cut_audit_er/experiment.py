from __future__ import annotations
from pathlib import Path
import csv,hashlib,json,os,platform,subprocess,time
from importlib.metadata import version
import numpy as np
from .audit import run_audit
from .synthetic import synthetic_graph
from .policies import METHODS, DEFAULT_METHODS
from .guard import require_approval,protocol_hash

def metadata(root: Path,config: dict) -> dict:
    try:
        commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,stderr=subprocess.DEVNULL,text=True).strip()
    except (OSError,subprocess.CalledProcessError):
        commit=None
    return {"python":platform.python_version(),"platform":platform.platform(),
            "python_hash_seed":os.environ.get("PYTHONHASHSEED"),
            "versions":{n:version(n) for n in ("numpy","networkx","pandas","scikit-learn")},
            "git_commit":commit,"protocol_sha256":protocol_hash(root),
            "config_sha256":hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
            "config":config}

def save_runs(out: Path,runs: list[dict],meta: dict):
    out.mkdir(parents=True,exist_ok=True)
    if (out/"runs.json").exists():
        raise FileExistsError("Output already exists; use a fresh directory, do not overwrite evidence")
    (out/"runs.json").write_text(json.dumps({"metadata":meta,"runs":runs},indent=2),encoding="utf-8")
    rows=[]
    for r in runs:
        rows.append({k:r.get(k) for k in ("dataset","regime","seed","method","requested_budget","spent","noise","loss_reduction","seconds","score_accesses")}|r["final"])
    if rows:
        with (out/"summary.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    label=f"{meta.get('data_kind','UNKNOWN').upper()} — {meta.get('phase','UNKNOWN').upper()} EVIDENCE"
    (out/"README.md").write_text(f"# {label}\n\n{len(runs)} runs. This output is not evidence of novelty, acceptance, or superiority to published methods.\n",encoding="utf-8")

def run_experiment(root: Path,cfg: dict,out: Path):
    if cfg.get("phase","development")=="test":
        require_approval(root,run_config=cfg)
    seeds=cfg.get("seeds",[7]);regimes=cfg.get("regimes",["double_bridge"])
    methods=cfg.get("methods",list(DEFAULT_METHODS))
    if not seeds or len(seeds)!=len(set(seeds)) or not set(methods)<=set(METHODS):
        raise ValueError("Invalid seeds or methods")
    runs=[];start=time.perf_counter()
    for seed in seeds:
        for regime in regimes:
            g,s,truth=synthetic_graph(seed,regime,cfg.get("n_entities",8))
            for method in methods:
                if time.perf_counter()-start>cfg.get("max_wall_seconds",1800):
                    raise TimeoutError("Compute cap reached; no automatic budget escalation")
                r=run_audit(g,s,truth,method,cfg.get("budget",12),seed,cfg.get("oracle_noise",0),
                            cfg.get("fn_weight",1),cfg.get("max_width",2),cfg.get("shortlist",24))
                r.update(dataset="synthetic_graph",regime=regime);runs.append(r)
    meta=metadata(root,cfg)|{"phase":cfg.get("phase","development"),"data_kind":"synthetic_mechanism_stress_test"}
    save_runs(out,runs,meta)
    return runs
