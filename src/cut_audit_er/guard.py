"""Protocol-integrity guard, NOT a security boundary against a malicious agent."""
from __future__ import annotations
from pathlib import Path
import hashlib,json

def protocol_hash(root: Path) -> str:
    h=hashlib.sha256()
    paths=[]
    for folder in ("src","configs"):
        paths.extend(p for p in (root/folder).rglob("*") if p.suffix in (".py",".json"))
    paths.extend(p for name in ("EXPERIMENT_PROTOCOL.md","THEORY.md","NOVELTY_MATRIX.md")
                 if (p := root/"research"/name).exists())
    for p in sorted(paths):
        h.update(p.relative_to(root).as_posix().encode());h.update(b"\0");h.update(p.read_bytes())
    return h.hexdigest()

def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

def require_approval(root: Path,input_sha256: str|None=None,run_config: dict|None=None) -> None:
    p=root/"research/HUMAN_APPROVAL.json"
    if not p.exists():
        raise PermissionError("Confirmatory evaluation is locked; supervisor approval is required")
    a=json.loads(p.read_text())
    if a.get("approved") is not True or a.get("protocol_sha256")!=protocol_hash(root):
        raise PermissionError("Missing approval or source/config changed after protocol lock")
    if a.get("scope") != "confirmatory_evaluation_only":
        raise PermissionError("Invalid approval scope")
    if run_config is not None and config_hash(run_config) not in a.get("approved_run_config_sha256",[]):
        raise PermissionError("Run settings are not covered by this approval")
    if not a.get("approved_by") or not a.get("approved_on"):
        raise PermissionError("Approval must identify the actual supervisor and date")
    if input_sha256 is not None and input_sha256 not in a.get("approved_dataset_sha256",[]):
        raise PermissionError("Dataset file is not covered by this approval")
