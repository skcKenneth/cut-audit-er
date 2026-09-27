from __future__ import annotations
from pathlib import Path
import hashlib
import numpy as np
import pandas as pd

REQUIRED=("record_id","entity_id","text")

def validate_records(df: pd.DataFrame) -> pd.DataFrame:
    if not set(REQUIRED)<=set(df.columns):
        raise ValueError(f"CSV requires {REQUIRED}; extra columns are ignored by the matcher")
    d=df.copy()
    for c in REQUIRED:
        if d[c].isna().any():
            raise ValueError(f"Missing {c}")
        d[c]=d[c].astype(str)
        if d[c].str.strip().eq("").any():
            raise ValueError(f"Blank {c}")
    if d.record_id.duplicated().any():
        raise ValueError("Duplicate record_id")
    if len(d)<20 or d.entity_id.nunique()<20:
        raise ValueError("Need at least 20 distinct entities")
    return d

def load_csv(path: str|Path) -> pd.DataFrame:
    return validate_records(pd.read_csv(path,dtype=str,keep_default_na=False))

def entity_splits(df: pd.DataFrame,seed: int=7,holdout_seed: int=7) -> dict[str,pd.DataFrame]:
    """Reserve one common test population before varying development splits.

    With default seeds, every partition exactly matches the original seed-7
    split. Other development seeds shuffle only its non-test entities. Changing
    holdout_seed defines a new prospective holdout; it cannot undo prior exposure.
    """
    d=validate_records(df)
    keys=np.array(sorted(d.entity_id.unique()))
    rng=np.random.default_rng(holdout_seed);rng.shuffle(keys)
    n=len(keys);a,b,c=int(.45*n),int(.60*n),int(.80*n)
    pool=keys[:c].copy();holdout=keys[c:].copy()
    # Preserve the historical seed-7 train/calibration/development graph identity.
    if seed!=holdout_seed:
        np.random.default_rng(seed).shuffle(pool)
    chunks=(*np.split(pool,[a,b]),holdout)
    result={name:d[d.entity_id.isin(k)].reset_index(drop=True)
            for name,k in zip(("train","calibration","development","test"),chunks)}
    sets=[set(x.entity_id) for x in result.values()]
    if any(sets[i]&sets[j] for i in range(4) for j in range(i+1,4)):
        raise AssertionError("Entity leakage")
    return result

def split_manifest(splits: dict[str,pd.DataFrame]) -> dict:
    return {name:{"records":len(d),"entities":d.entity_id.nunique(),
                  "record_ids_sha256":hashlib.sha256("\n".join(sorted(d.record_id)).encode()).hexdigest(),
                  "entity_ids_sha256":hashlib.sha256("\n".join(sorted(d.entity_id.unique())).encode()).hexdigest()}
            for name,d in splits.items()}
