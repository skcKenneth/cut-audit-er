"""Synthetic mechanism tests; deliberately NOT realistic benchmark evidence."""
from __future__ import annotations
from itertools import combinations
import numpy as np
import pandas as pd
import networkx as nx
from .scores import PairScores

REGIMES=("bridge","double_bridge","dense","mixed","clean")

def synthetic_graph(seed: int=7, regime: str="double_bridge", n_entities: int=8,
                    min_size: int=3, max_size: int=6):
    if regime not in REGIMES or n_entities<2 or min_size<2 or max_size<min_size:
        raise ValueError("Invalid synthetic graph settings")
    rng=np.random.default_rng(seed)
    groups=[];truth={}
    for k in range(n_entities):
        group=[f"r{k:03d}_{j:03d}" for j in range(int(rng.integers(min_size,max_size+1)))]
        groups.append(group);truth.update({r:f"entity{k:03d}" for r in group})
    ids=tuple(truth);idx={r:i for i,r in enumerate(ids)}
    p=np.eye(len(ids));g=nx.Graph();g.add_nodes_from(ids)
    for u,v in combinations(ids,2):
        same=truth[u]==truth[v]
        prob=float(rng.beta(10,2) if same else rng.beta(1,9))
        p[idx[u],idx[v]]=p[idx[v],idx[u]]=prob
    for group in groups:
        # Connected within-entity graphs, with cycles and shortcut edges.
        for j,u in enumerate(group):
            v=group[(j+1)%len(group)]
            g.add_edge(u,v,p=float(p[idx[u],idx[v]]))
        for u,v in combinations(group,2):
            if rng.random()<.28:
                g.add_edge(u,v,p=float(p[idx[u],idx[v]]))
    if regime!="clean":
        for a,b in zip(groups[:-1],groups[1:]):
            count={"bridge":1,"double_bridge":2,"dense":min(len(a),len(b)),
                   "mixed":int(rng.integers(1,min(len(a),len(b))+1))}[regime]
            for j in range(count):
                u,v=a[j%len(a)],b[j%len(b)]
                # A simulated confidently wrong observed matcher score.
                p[idx[u],idx[v]]=p[idx[v],idx[u]]=float(rng.uniform(.58,.94))
                g.add_edge(u,v,p=float(p[idx[u],idx[v]]))
    return g,PairScores(ids,p),truth

def synthetic_records(seed: int=7,n_entities: int=80) -> pd.DataFrame:
    if n_entities<20:
        raise ValueError("Need >=20 entities for independent four-way splits")
    rng=np.random.default_rng(seed)
    words=["algebra","biology","forest","energy","records","learning","materials",
           "optics","water","quantum","design","analysis","spectra","database","mining"]
    rows=[]
    alphabet=list("abcdefghijklmnopqrstuvwxyz")
    for k in range(n_entities):
        distinctive="".join(rng.choice(alphabet,size=7))
        base=" ".join(rng.choice(words,size=3,replace=False))+" "+distinctive
        for j in range(int(rng.integers(3,6))):
            chars=list(base)
            for _ in range(int(rng.integers(0,5))):
                z=int(rng.integers(len(chars)));chars[z]=str(rng.choice(alphabet))
            rows.append({"record_id":f"record{k:03d}_{j}","entity_id":f"e{k:03d}",
                         "text":"".join(chars),"source":f"synthetic_source{j}"})
    return pd.DataFrame(rows)
