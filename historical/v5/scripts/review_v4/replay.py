"""Replay purchased answers without a gold oracle, preserving graph iteration order.

The evaluator reference is an independent optional file, never a selector input.
No missing answer may be obtained from that file. Runtime is validation cost.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time
import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from cut_audit_er.bounded_planner import build_plan_pool, completion_score
from cut_audit_er.policies import select_action
from cut_audit_er.scores import PairScores
from cut_audit_er.planner_workspace import PlannerWorkspace

METHODS = ('edge_betweenness','cut_plan_fixed','cut_plan_fixed_singleton')
PAYLOAD_FILES = frozenset(('observable.json', 'scores.npy', 'paid_cases.json',
                           'evaluator_reference.json'))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def semantic(value):
    if isinstance(value, dict):
        return {k:semantic(v) for k,v in value.items()
                if not k.endswith('_seconds') and k not in ('seconds','topology_cache','batch_timings')}
    if isinstance(value, (list,tuple)): return [semantic(v) for v in value]
    if isinstance(value, np.generic): return value.item()
    return value

def partition(graph):
    return sorted(sorted(c) for c in nx.connected_components(graph))

def observable(graph, scores, aliases=None):
    aliases = aliases or {v:v for v in graph}
    if set(aliases) != set(graph) or len(set(aliases.values())) != len(graph):
        raise ValueError('Invalid one-to-one alias mapping')
    if [aliases[n] for n in sorted(graph)] != sorted(aliases.values()):
        raise ValueError('Aliases change lexical tie order')
    return {'schema':'cut-audit-ordered-observable-v1',
            'nodes':[aliases[v] for v in graph],
            'adjacency':[[aliases[u], [[aliases[v],float(graph.edges[u,v]['p'])]
                for v in graph.adj[u]]] for u in graph],
            'score_ids':[aliases[v] for v in scores.ids],
            'contains_evaluator_reference':False}

def graph_from_observable(data, matrix):
    if data.get('schema') != 'cut-audit-ordered-observable-v1' or data.get('contains_evaluator_reference') is not False:
        raise ValueError('Unknown observable schema or mixed evaluator data')
    nodes = data['nodes']
    if len(set(nodes)) != len(nodes) or [r[0] for r in data['adjacency']] != nodes:
        raise ValueError('Node/adjacency order differs')
    graph = nx.Graph(); graph.add_nodes_from(nodes)
    wanted = {}
    for u, row in data['adjacency']:
        wanted[u] = [v for v,p in row]
        if len(set(wanted[u])) != len(wanted[u]): raise ValueError('Duplicate adjacency')
        for v,p in row:
            if v not in nodes or v == u or not 0 <= p <= 1:
                raise ValueError('Invalid observable edge')
            if graph.has_edge(u,v) and graph.edges[u,v]['p'] != p:
                raise ValueError('Asymmetric edge weights')
            graph.add_edge(u,v,p=p)
    # An undirected edge list cannot in general preserve every adjacency order.
    # Reorder each adjacency dictionary using its existing shared edge objects.
    for u in nodes:
        if set(wanted[u]) != set(graph.adj[u]): raise ValueError('Asymmetric adjacency')
        graph._adj[u] = {v:graph._adj[u][v] for v in wanted[u]}
    if [list(graph.adj[u]) for u in nodes] != [wanted[u] for u in nodes]:
        raise AssertionError('Adjacency order restoration failed')
    scores = PairScores(tuple(data['score_ids']), matrix)
    if set(scores.ids) != set(graph): raise ValueError('Score IDs differ')
    return graph,scores

def rename_value(value, aliases):
    if isinstance(value,str): return aliases.get(value,value)
    if isinstance(value,dict): return {aliases.get(k,k):rename_value(v,aliases) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [rename_value(v,aliases) for v in value]
    return value

def run_trace(graph, scores, archived_run):
    """Selector-only replay; this function has no truth/reference argument."""
    method,budget = archived_run['method'],archived_run['requested_budget']
    if method not in METHODS: raise ValueError('Unsupported replay method')
    if archived_run.get('complete') is not True: raise ValueError('Incomplete endpoint cannot be replayed as complete')
    if archived_run.get('fn_weight') != 1 or archived_run.get('noise') != 0:
        raise ValueError('Replay supports the declared noiseless lambda-one contract only')
    g=graph.copy(); reads=scores.copy(); observed={}; state={}
    rng=np.random.default_rng(archived_run.get('seed',7))
    groups=[(b,list(items)) for b,items in itertools.groupby(archived_run['decisions'],key=lambda d:d['batch'])]
    states=[partition(g)]; batches=[]; paid=[]; diagnostics=0
    diag_workspace=PlannerWorkspace()
    for index,(batch,records) in enumerate(groups,1):
        if batch != index or budget-len(observed)<1: raise ValueError('Invalid recorded batch')
        remaining=budget-len(observed)
        pool=None
        ds=scores.copy()
        if method != 'edge_betweenness':
            plans,parts,probabilities,weighted,info=build_plan_pool(
                g,ds,set(observed),remaining,diagnostic_raw=True,workspace=diag_workspace)
            raw=[tuple(tuple(e) for e in q) for q in info['raw_plan_edges']]
            ranked=sorted(raw,key=lambda q:(-sum(weighted[e] for e in q)/len(q),len(q),q))
            scored=[q for q in plans if method!='cut_plan_fixed_singleton' or len(q)==1]
            utilities=[]
            for q in scored:
                value,gain,success=completion_score(q,parts[q],ds,probabilities,observed,1.)
                utilities.append({'plan':q,'proxy':value,'utility':gain,'success_product':success})
            utilities.sort(key=lambda r:(-r['proxy'],len(r['plan']),r['plan']))
            pool={'generated_lexical':raw,'preranked':ranked,'capped':ranked[:64],
                  'validated':plans,'scored':scored,'utility_ranked':utilities}
        else:
            centrality=nx.edge_betweenness_centrality(g)
            candidates=[(tuple(sorted(e)),value*(1-ds.p(*e))) for e,value in centrality.items()
                        if tuple(sorted(e)) not in observed]
            pool={'bc_ranked':[{'pair':edge,'weighted_centrality':value}
                  for edge,value in sorted(candidates,key=lambda r:(-r[1],r[0]))]}
        diagnostics += ds.calls
        action,info=select_action(g,reads,set(observed),remaining,method,rng,1.,2,24,.6,observed,
                                 archived_run.get('seed',7),state)
        recorded=[tuple(d['pair']) for d in records]
        if action is None or list(action) != recorded:
            raise AssertionError('Selected action differs from recorded paid batch')
        if any(semantic(info) != semantic(record['selection_info']) for record in records):
            raise AssertionError('Selector metadata differs from archived batch')
        batches.append({'batch':batch,'paid_before':len(observed),'candidate_order':semantic(pool),
                        'selection_info':semantic(info),'action':semantic(action),
                        'logical_accesses_after_selection':reads.calls})
        for edge,decision in zip(action,records):
            if edge in observed or not g.has_edge(*edge): raise ValueError('Repeated/missing paid edge')
            answer=decision['observed_match']
            if not isinstance(answer,bool): raise ValueError('Non-Boolean paid answer')
            if decision['spent'] != len(observed)+1: raise ValueError('Paid event gap')
            observed[edge]=answer
            if not answer: g.remove_edge(*edge)
            paid.append({'spent':len(observed),'batch':batch,'pair':list(edge),'answer':answer})
            states.append(partition(g))
    if len(observed)==budget:
        stop='budget_exhausted'
    else:
        action,info=select_action(g,reads,set(observed),budget-len(observed),method,rng,1.,2,24,.6,
                                 observed,archived_run.get('seed',7),state)
        if action is not None: raise AssertionError('Replay requests an unrecorded answer')
        stop=info.get('reason','no_action')
    if stop != archived_run['stop_reason'] or reads.calls != archived_run['score_accesses']:
        raise AssertionError('Stop reason or logical accesses differ')
    if len(observed) != archived_run['spent']: raise AssertionError('Paid count differs')
    return {'method':method,'requested_budget':budget,'batches':batches,'paid':paid,
            'partitions':states,'stop_reason':stop,'logical_score_accesses':reads.calls,
            'diagnostic_score_accesses':diagnostics,'new_oracle_answers':0}

def write_bundle(out,graph,scores,runs,reference,*,label,source_hashes):
    """Export ordered aliases; no original IDs or reverse map are written."""
    out=Path(out)
    if out.exists(): raise FileExistsError('Fresh replay bundle required')
    aliases={n:f'r{i:06d}' for i,n in enumerate(sorted(graph))}
    obs=observable(graph,scores,aliases)
    public_graph,public_scores=graph_from_observable(obs,scores.matrix)
    cases=[]
    for run_id,run in runs:
        if not isinstance(run_id, str) or any(case['id'] == run_id for case in cases):
            raise ValueError('Replay case IDs must be unique strings')
        expected=run_trace(graph,scores,run)
        changed=rename_value(run,aliases)
        actual=run_trace(public_graph,public_scores,changed)
        if rename_value(expected,aliases) != actual:
            raise AssertionError('Alias transform changes full replay')
        cases.append({'id':run_id,'run':changed,'expected':actual})
    out.mkdir(parents=True)
    def save(name,value):
        (out/name).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save('observable.json',obs)
    np.save(out/'scores.npy',scores.matrix,allow_pickle=False)
    save('paid_cases.json',cases)
    classes={e:f'e{i:06d}' for i,e in enumerate(sorted(set(reference.values())))}
    save('evaluator_reference.json',{'scope':'Offline evaluation only; never selector input',
        'reference':{aliases[k]:classes[v] for k,v in reference.items()}})
    files={p.name:digest(p) for p in sorted(out.iterdir())}
    save('manifest.json',{'schema':'cut-audit-public-replay-v4','label':label,'files_sha256':files,
         'source_hashes':source_hashes,'cases':len(cases),'new_oracle_answers':0,
         'scope':'Replay of saved paid answers, not new experiments; original IDs/text omitted'})
    return {'status':'PASS','cases':len(cases),'files_sha256':files}

def check_bundle(folder):
    folder=Path(folder); manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'cut-audit-public-replay-v4': raise ValueError('Replay manifest schema differs')
    if set(manifest['files_sha256']) != PAYLOAD_FILES:
        raise ValueError('Replay manifest must hash all four payload files')
    for name,pin in manifest['files_sha256'].items():
        if Path(name).name!=name or digest(folder/name)!=pin: raise ValueError('Replay source hash mismatch')
    data=json.loads((folder/'observable.json').read_text(encoding='utf-8'))
    graph,scores=graph_from_observable(data,np.load(folder/'scores.npy',allow_pickle=False))
    cases=json.loads((folder/'paid_cases.json').read_text(encoding='utf-8'))
    ids = [case['id'] for case in cases]
    if (type(manifest.get('cases')) is not int or manifest['cases'] != len(cases)
            or any(not isinstance(case_id, str) for case_id in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('Replay case count or unique case IDs differ')
    started=time.perf_counter()
    for case in cases:
        actual=run_trace(graph,scores,case['run'])
        if actual!=case['expected']: raise AssertionError('Complete recorded replay differs')
    # Load labels only after all selector replays; never use them to supply answers.
    truth=json.loads((folder/'evaluator_reference.json').read_text(encoding='utf-8'))['reference']
    from cut_audit_er.metrics import evaluate
    for case in cases:
        g=graph.copy()
        metrics=[evaluate(g,truth,1.)]
        for event in case['expected']['paid']:
            if not event['answer']: g.remove_edge(*event['pair'])
            metrics.append(evaluate(g,truth,1.))
        run = case['run']
        trace = run['trace']
        if len(trace) != run['spent'] + 1 or len(metrics) != len(trace):
            raise AssertionError('Offline metric trace length differs')
        for spent, (row, expected) in enumerate(zip(metrics, trace)):
            if expected.get('spent') != spent or set(expected) != {'spent', *row}:
                raise AssertionError('Offline metric trace fields or paid sequence differ')
            for key, value in row.items():
                # Alias names can change set iteration and the final bit of B3
                # summation. Primary counts/loss and all integer fields stay exact.
                equal = (value == expected[key] if key in ('fp', 'fn', 'loss')
                         or isinstance(value, int) else
                         math.isclose(value, expected[key], rel_tol=1e-12, abs_tol=1e-12))
                if not equal: raise AssertionError('Offline metric replay differs')
        if run['initial'] != trace[0] or run['final'] != trace[-1]:
            raise AssertionError('Offline initial or final metrics differ from trace')
        if run['loss_reduction'] != trace[0]['loss'] - trace[-1]['loss']:
            raise AssertionError('Offline loss reduction violates conservation')
    return {'status':'PASS','cases':len(cases),'paid_answers_replayed':sum(c['run']['spent'] for c in cases),
            'new_oracle_answers':0,'seconds':time.perf_counter()-started}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--receipt',type=Path);args=p.parse_args();result=check_bundle(args.bundle)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        with args.receipt.open('x',encoding='utf-8') as f: json.dump(result,f,indent=2)
    print(json.dumps(result))

if __name__=='__main__': main()
