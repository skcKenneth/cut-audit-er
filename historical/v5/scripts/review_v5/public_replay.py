"""V5 public saved-answer replay: observable aliases first, evaluator last.

Export is restricted to the two permitted DBLP graphs and constructed synthetic
fixtures. No WDC or ALASKA record, graph, score matrix or reference is exported.
Checking uses stored paid answers only, never an oracle or an unrecorded answer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from scripts.review_v5 import analysis as a, study as s
from scripts.review_v4.replay import observable, graph_from_observable, rename_value

SCHEMA = 'cut-audit-public-paid-replay-v5'
NATURAL_GRAPHS = {'dblp_acm': 'dblp_exposed', 'dblp_unused': 'dblp_unused'}
SYNTHETIC_GRAPHS = {f'k{k}_{p}' for k in (1,2,3) for p in ('uniform','ranked')}
STATUSES = frozenset(('completed','timeout','failed','incomplete','interrupted','cleanup_failed',
                      'not_started','not_started_limit','worker_error'))
CASE_KEYS = frozenset(('id','graph','method','budget','status','paid_lower_bound','paid_upper_bound','run','expected'))
COMPACT_CASE_KEYS = (CASE_KEYS - {'expected'}) | {'expected_sha256'}
INDEX_KEYS = (CASE_KEYS - {'run','expected'}) | {'has_run','recorded_paid_answers','case_file','expected_sha256'}
LAYOUT = 'compact-per-case-v1'
ENGINE_FILES = (
    '__init__.py','__main__.py','adapters.py','audit.py','bounded_planner.py',
    'calibrated_planner.py','cli.py','completion_calibration.py','cora_adapter.py',
    'covered_planner.py','data.py','experiment.py','graph.py','graphcr_adapter.py',
    'graphcr_native_cpu_reimplementation.py','guard.py','matcher.py','metrics.py',
    'natural.py','offline_structure.py','oracle.py','planner_workspace.py',
    'policies.py','policy_score_sensitivity.py','published_adapters.py',
    'reconstruction.py','revision_policies.py','scores.py','synthetic.py','telemetry.py')
SUPPORT_FILES = (
    'scripts/review_v5/public_replay.py','scripts/review_v5/analysis.py',
    'scripts/review_v5/study.py','scripts/review_v5/opportunities.py',
    'scripts/review_v4/replay.py','scripts/review_v4/synthetic.py',
    'scripts/conference_improvement/finite_budget.py','scripts/structural_study/assets.py',
    'tests/test_review_v5_planner.py','tests/test_review_v5_opportunities.py',
    'tests/test_review_v5_study.py','tests/test_review_v5_analysis.py',
    'tests/test_review_v5_ledger_independent.py','tests/test_review_v5_public_replay.py',
    'research/review_v5/NUMERIC_BOUND.md')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):sha.update(block)
    return sha.hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(s.blob(value))


def compact_save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        stream.write('\n')


def semantic_hash(value):
    """Hash every ordered semantic trace value; no rounding or field omission."""
    sha=hashlib.sha256()
    encoder=json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    for part in encoder.iterencode(value):sha.update(part.encode('utf-8'))
    return sha.hexdigest()


def iter_json_array(path, *, chunk_size=8*1024**2):
    """Read one legacy array element at a time, retaining no prior full case."""
    decoder=json.JSONDecoder();buffer='';eof=False
    with Path(path).open(encoding='utf-8') as stream:
        def more():
            nonlocal buffer,eof
            part=stream.read(chunk_size);buffer+=part;eof=not part
            require(len(buffer)<=256*1024**2,'Legacy individual case exceeds256MiB delivery-reader capacity')
        def nonspace():
            nonlocal buffer
            buffer=buffer.lstrip()
            while not buffer and not eof:more();buffer=buffer.lstrip()
        nonspace();require(buffer.startswith('['),'Legacy case array required');buffer=buffer[1:]
        first=True
        while True:
            nonspace()
            if buffer.startswith(']'):
                buffer=buffer[1:];nonspace();require(not buffer,'Trailing legacy case content');return
            if not first:
                require(buffer.startswith(','),'Legacy array separator missing');buffer=buffer[1:];nonspace()
            while True:
                try:value,end=decoder.raw_decode(buffer);break
                except json.JSONDecodeError:
                    if eof:raise
                    more()
            buffer=buffer[end:];first=False
            yield value


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def safe_path(root, name):
    require(isinstance(name,str) and name and not name.startswith('/')
            and ':' not in name and '\\' not in name
            and all(p not in ('','.','..') for p in name.split('/')), 'Unsafe bundle path')
    root=Path(root).resolve(); path=root/name
    require(not any(p.is_symlink() for p in (path,*path.parents) if p!=root.parent), 'Symlink in replay bundle')
    require(path.resolve().is_relative_to(root), 'Bundle path escapes root')
    return path


def validate_graph_keys(keys, kind):
    allowed = set(NATURAL_GRAPHS.values()) if kind=='dblp' else SYNTHETIC_GRAPHS if kind=='synthetic' else set()
    require(bool(keys) and set(keys)<=allowed, 'Only declared DBLP aliases or constructed synthetic inputs may be exported')


def visible_run(run, complete):
    """Strict allowlist removes private metadata and all evaluator metrics."""
    require(run.get('method') in s.NATURAL_METHODS, 'Unsupported V5 replay method')
    require(type(run.get('requested_budget')) is int and run['requested_budget']>=0, 'Invalid requested budget')
    for key, expected in (('seed',7),('noise',0),('fn_weight',1)):
        require(run.get(key,expected)==expected, 'Replay contract differs: '+key)
    decisions=[]
    for d in run.get('decisions',[]):
        require(set(('batch','pair','observed_match','spent','selection_info'))<=d.keys(), 'Paid event fields missing')
        decisions.append({k:a.semantic(d[k]) for k in ('batch','pair','observed_match','spent','selection_info')})
    value={'method':run['method'],'requested_budget':run['requested_budget'],
           'seed':7,'noise':0,'fn_weight':1,'complete':bool(complete),'decisions':decisions}
    if complete:
        require(run.get('complete') is True, 'Incomplete run cannot become a complete endpoint')
        for key in ('spent','score_accesses','stop_reason'):
            require(key in run, 'Complete saved run lacks '+key)
            value[key]=run[key]
    return value


def bundle_counts(cases):
    if cases and 'has_run' in cases[0]:
        return {'planned_cases':len(cases),'completed_cases':sum(c['status']=='completed' for c in cases),
                'prefix_cases':sum(c['has_run'] and c['status']!='completed' for c in cases),
                'missing_cases':sum(c['status']!='completed' for c in cases),
                'recorded_paid_answers':sum(c['recorded_paid_answers'] for c in cases),
                'paid_lower_bound':sum(c['paid_lower_bound'] for c in cases),
                'paid_upper_bound':sum(c['paid_upper_bound'] for c in cases)}
    return {'planned_cases':len(cases), 'completed_cases':sum(c['status']=='completed' for c in cases),
            'prefix_cases':sum(c['run'] is not None and c['status']!='completed' for c in cases),
            'missing_cases':sum(c['status']!='completed' for c in cases),
            'recorded_paid_answers':sum(len(c['run']['decisions']) if c['run'] else 0 for c in cases),
            'paid_lower_bound':sum(c['paid_lower_bound'] for c in cases),
            'paid_upper_bound':sum(c['paid_upper_bound'] for c in cases)}


def write_bundle(out, graphs, planned_cases, references, *, kind, label, source_hashes):
    """Alias and compare complete observable traces; preserve every planned slot.

    graphs maps permitted graph keys to (graph, PairScores). Each case has id,
    graph, method, budget, status, paid lower/upper bounds and optional saved run.
    References are graph -> reference-name -> node/entity mapping; they are used
    only after all original/alias selector traces have been compared.
    """
    out=Path(out); require(not out.exists(), 'Fresh public replay output required')
    validate_graph_keys(graphs,kind)
    require(set(references)==set(graphs), 'Evaluator graph inventory differs')
    require(source_hashes and all(re.fullmatch('[A-Za-z0-9_.-]+',k) and re.fullmatch('[0-9a-f]{64}',v)
                                 for k,v in source_hashes.items()), 'Public provenance must contain labelled hashes only')
    aliases={}; public={}; descriptions={}
    for key,(graph,scores) in graphs.items():
        aliases[key]={node:f'r{i:06d}' for i,node in enumerate(sorted(graph))} if kind=='dblp' else {n:n for n in graph}
        description=observable(graph,scores,aliases[key])
        public[key]=graph_from_observable(description,scores.matrix)
        descriptions[key]=description
    cases=[]; original_metrics={}
    for raw in planned_cases:
        require(isinstance(raw['id'],str) and re.fullmatch('[A-Za-z0-9_-]+',raw['id']), 'Unsafe public case ID')
        require(raw['id'] not in {c['id'] for c in cases}, 'Duplicate planned case')
        require(raw['graph'] in graphs and raw['method'] in s.NATURAL_METHODS, 'Case outside declared inputs')
        require(type(raw['budget']) is int and raw['budget']>=0, 'Invalid case budget')
        require(type(raw['paid_lower_bound']) is int and type(raw['paid_upper_bound']) is int
                and 0<=raw['paid_lower_bound']<=raw['paid_upper_bound']<=raw['budget'], 'Invalid physical paid bounds')
        require(raw['status'] in STATUSES, 'Unsupported preserved status')
        case={k:raw[k] for k in ('id','graph','method','budget','status','paid_lower_bound','paid_upper_bound')}
        case.update(run=None,expected=None)
        complete=raw['status']=='completed'; original=raw.get('run')
        require(not complete or original is not None, 'Completed case lacks paid run')
        if original is not None:
            trimmed=visible_run(original,complete)
            require(trimmed['method']==raw['method'] and trimmed['requested_budget']==raw['budget'], 'Saved run identity differs')
            original_replay=a.semantic(a.visible_replay(*graphs[raw['graph']],trimmed,complete=complete))
            renamed=rename_value(trimmed,aliases[raw['graph']])
            replay=a.semantic(a.visible_replay(*public[raw['graph']],renamed,complete=complete))
            require(rename_value(original_replay,aliases[raw['graph']])==replay, 'Aliases change full candidate/action/partition/cost replay')
            require(len(replay['events'])==case['paid_lower_bound'], 'Recorded answers differ from confirmed lower bound')
            if complete:
                require(case['paid_lower_bound']==case['paid_upper_bound']==trimmed['spent'], 'Completed physical cost not exact')
                if original.get('trace') is not None:
                    trace=original['trace']
                    require(len(trace)==trimmed['spent']+1, 'Complete source metric trace truncated')
                    if 'initial' in original: require(original['initial']==trace[0], 'Source initial metrics differ from trace')
                    if 'final' in original: require(original['final']==trace[-1], 'Source final metrics differ from trace')
                    if 'loss_reduction' in original:
                        require(original['loss_reduction']==trace[0]['loss']-trace[-1]['loss'], 'Source loss accounting differs')
            case.update(run=renamed,expected=replay)
            if original.get('trace') is not None:
                original_metrics[case['id']]=original['trace']
        else:
            require(case['paid_lower_bound']==0, 'Confirmed answers missing from prefix replay')
        cases.append(case)
    # Evaluate only after every selector-only original/alias equivalence passed.
    evaluation={'scope':'Offline evaluation after selector replay; never supplies an answer', 'references':{},'cases':{}}
    for key,refs in references.items():
        require(set(refs)==({'natural'} if kind=='dblp' else {'H0','H9'}), 'Reference inventory differs')
        graph=graphs[key][0]; converted={}
        for name,truth in refs.items():
            require(set(truth)==set(graph), 'Reference record membership differs')
            classes={e:f'e{i:06d}' for i,e in enumerate(sorted(set(truth.values())))}
            converted[name]={aliases[key][node]:classes[entity] for node,entity in truth.items()}
        evaluation['references'][key]=converted
    for case in cases:
        if case['run'] is None:
            continue
        values={}
        for name,truth in evaluation['references'][case['graph']].items():
            result=a.evaluate_replay(case['expected'],truth)
            if name==('natural' if kind=='dblp' else 'H0') and case['id'] in original_metrics:
                a.evaluate_replay(case['expected'],truth,original_metrics[case['id']])
            values[name]=result
        evaluation['cases'][case['id']]=values
    out.mkdir(parents=True)
    for key,description in descriptions.items():
        save(out/f'graphs/{key}/observable.json',description)
        np.save(out/f'graphs/{key}/scores.npy',graphs[key][1].matrix,allow_pickle=False)
    save(out/'cases.json',cases);save(out/'evaluator_reference.json',evaluation)
    files={p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest={'schema':SCHEMA,'kind':kind,'label':label,'graphs':sorted(graphs),
              'counts':bundle_counts(cases),'files_sha256':files,'source_hashes':source_hashes,
              'new_oracle_answers':0,'alias_validation':'Full candidate order, action, answers, batches, partition, stop and logical accesses',
              'cost_scope':'Acquisition counted once; paired references are dependent offline evaluations',
              'missing_scope':'Recorded prefixes are never independent requested-budget endpoints'}
    save(out/'manifest.json',manifest)
    return manifest


def check_bundle(folder, *, evaluate=True):
    folder=Path(folder); manifest=read(folder/'manifest.json')
    if manifest.get('layout')==LAYOUT:return check_compact_bundle(folder,evaluate=evaluate)
    require(manifest.get('schema')==SCHEMA and manifest.get('new_oracle_answers')==0, 'Wrong public replay manifest')
    validate_graph_keys(manifest['graphs'],manifest['kind'])
    require(len(set(manifest['graphs']))==len(manifest['graphs']), 'Duplicate graph declaration')
    expected={'cases.json','evaluator_reference.json'} | {
        f'graphs/{key}/{name}' for key in manifest['graphs'] for name in ('observable.json','scores.npy')}
    require(set(manifest['files_sha256'])==expected, 'Payload manifest must list every allowed file exactly')
    actual=set()
    for path in folder.rglob('*'):
        require(not path.is_symlink(), 'Symlink in replay bundle')
        if path.is_file(): actual.add(path.relative_to(folder).as_posix())
    require(actual==expected|{'manifest.json'}, 'Unlisted public replay file')
    for name,pin in manifest['files_sha256'].items():
        require(digest(safe_path(folder,name))==pin, 'Public replay source hash mismatch: '+name)
    graphs={key:graph_from_observable(read(folder/f'graphs/{key}/observable.json'),
              np.load(folder/f'graphs/{key}/scores.npy',allow_pickle=False)) for key in manifest['graphs']}
    if manifest['kind']=='dblp':
        require(all(re.fullmatch('r[0-9]{6}',node) for graph,_ in graphs.values() for node in graph),
                'Natural replay contains an original or malformed record ID')
    cases=read(folder/'cases.json');require(len({c['id'] for c in cases})==len(cases), 'Duplicate replay case IDs')
    require(bundle_counts(cases)==manifest['counts'], 'Planned/missing/cost inventory differs')
    checked={};started=time.perf_counter()
    for case in cases:
        require(set(case)==CASE_KEYS and case['status'] in STATUSES, 'Unexpected case fields or status')
        require(case['graph'] in graphs and case['method'] in s.NATURAL_METHODS, 'Undeclared public case')
        require(type(case['budget']) is int and type(case['paid_lower_bound']) is int
                and type(case['paid_upper_bound']) is int
                and 0<=case['paid_lower_bound']<=case['paid_upper_bound']<=case['budget'], 'Bad public paid bounds')
        if case['run'] is None:
            require(case['status']!='completed' and case['paid_lower_bound']==0 and case['expected'] is None,
                    'Missing case fabricated as completed')
            continue
        complete=case['status']=='completed'
        run=visible_run(case['run'],complete)
        require(run==case['run'] and run['method']==case['method'] and run['requested_budget']==case['budget'], 'Unlisted run data or case identity differs')
        replay=a.semantic(a.visible_replay(*graphs[case['graph']],run,complete=complete))
        require(replay==case['expected'], 'Public candidate/action/partition/cost replay differs')
        require(len(replay['events'])==case['paid_lower_bound'], 'Confirmed paid count differs')
        if complete: require(case['paid_upper_bound']==run['spent']==case['paid_lower_bound'], 'Complete paid count not exact')
        checked[case['id']]=replay
    if evaluate:
        # No selector receives this mapping, and no missing answer can use it.
        evaluator=read(folder/'evaluator_reference.json')
        require(set(evaluator['references'])==set(graphs) and set(evaluator['cases'])==set(checked), 'Evaluator inventory differs')
        for case in cases:
            if case['id'] not in checked: continue
            refs=evaluator['references'][case['graph']]
            require(set(refs)==({'natural'} if manifest['kind']=='dblp' else {'H0','H9'}), 'Evaluator references differ')
            require(set(evaluator['cases'][case['id']])==set(refs), 'Missing paired evaluation')
            for name,truth in refs.items():
                value=a.evaluate_replay(checked[case['id']],truth)
                require(value==evaluator['cases'][case['id']][name], 'Offline evaluator metrics differ')
    return {'status':'PASS',**manifest['counts'],'new_oracle_answers':0,'evaluator_checked':evaluate,
            'seconds':time.perf_counter()-started,'scope':'Saved-answer validation only, no new experiment'}


def compact_bundle(source,out):
    """Lossless delivery transform of an already original/alias-verified bundle."""
    source,out=Path(source),Path(out);require(not out.exists(),'Fresh compact output required')
    manifest=read(source/'manifest.json')
    require(manifest.get('schema')==SCHEMA and 'layout' not in manifest,'Expected original exported bundle')
    validate_graph_keys(manifest['graphs'],manifest['kind'])
    expected={'cases.json','evaluator_reference.json'}|{f'graphs/{k}/{n}' for k in manifest['graphs'] for n in ('observable.json','scores.npy')}
    require(set(manifest['files_sha256'])==expected,'Original bundle inventory differs')
    actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    require(actual==expected|{'manifest.json'},'Original bundle has unlisted files')
    for name,pin in manifest['files_sha256'].items():require(digest(safe_path(source,name))==pin,'Original bundle changed')
    out.mkdir(parents=True); index=[]; hashes={}
    for name in sorted(expected-{'cases.json'}):
        target=out/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
    for case in iter_json_array(source/'cases.json'):
        require(set(case)==CASE_KEYS and re.fullmatch('[A-Za-z0-9_-]+',case['id']),'Unexpected original case')
        require(case['id'] not in hashes,'Duplicate original case')
        require((case['run'] is None)==(case['expected'] is None),'Original expected/run inventory differs')
        pin=semantic_hash(case['expected']) if case['expected'] is not None else None
        data={k:v for k,v in case.items() if k!='expected'};data['expected_sha256']=pin
        name='cases/'+case['id']+'.json';compact_save(out/name,data)
        index.append({k:case[k] for k in CASE_KEYS-{'run','expected'}}|{
            'has_run':case['run'] is not None,'recorded_paid_answers':len(case['run']['decisions']) if case['run'] else 0,
            'case_file':name,'expected_sha256':pin})
        hashes[case['id']]=pin
    require(bundle_counts(index)==manifest['counts'],'Compaction changed case/cost inventory')
    compact_save(out/'cases.json',index)
    result={**manifest,'layout':LAYOUT,'semantic_hash_rule':'SHA256 of full semantic replay; UTF8 JSON sorted object keys, compact separators, exact scalar values and original array order',
        'compaction':{'original_manifest_sha256':digest(source/'manifest.json'),
            'original_cases_sha256':digest(source/'cases.json'),'full_expected_semantic_sha256':hashes,
            'scope':'Delivery transform only; all run inputs/candidate telemetry retained. Expected complete replay verified by canonical hash, not final loss alone.'},
        'files_sha256':{p.relative_to(out).as_posix():digest(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    compact_save(out/'manifest.json',result)
    return {'status':'PASS','counts':manifest['counts'],'original_bytes':sum(p.stat().st_size for p in source.rglob('*') if p.is_file()),
            'compact_bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),
            'original_manifest_sha256':digest(source/'manifest.json'),'compact_manifest_sha256':digest(out/'manifest.json'),
            'per_case_semantic_hashes':hashes,'new_oracle_answers':0,'selector_reexecution_during_transform':False}


def check_compact_bundle(folder,*,evaluate=True):
    folder=Path(folder);manifest=read(folder/'manifest.json');started=time.perf_counter()
    require(manifest.get('schema')==SCHEMA and manifest.get('layout')==LAYOUT and manifest.get('new_oracle_answers')==0,'Wrong compact replay manifest')
    validate_graph_keys(manifest['graphs'],manifest['kind']);index=read(folder/'cases.json')
    require(len({r['id'] for r in index})==len(index),'Duplicate replay case IDs')
    for row in index:
        require(set(row)==INDEX_KEYS and re.fullmatch('[A-Za-z0-9_-]+',row['id'])
                and row['case_file']=='cases/'+row['id']+'.json','Unexpected compact case index')
    expected={'cases.json','evaluator_reference.json'}|{r['case_file'] for r in index}|{
        f'graphs/{k}/{n}' for k in manifest['graphs'] for n in ('observable.json','scores.npy')}
    require(set(manifest['files_sha256'])==expected,'Compact manifest must list every allowed file')
    actual=set()
    for path in folder.rglob('*'):
        require(not path.is_symlink(),'Symlink in replay bundle')
        if path.is_file():actual.add(path.relative_to(folder).as_posix())
    require(actual==expected|{'manifest.json'},'Unlisted compact replay file')
    for name,pin in manifest['files_sha256'].items():require(digest(safe_path(folder,name))==pin,'Public replay source hash mismatch: '+name)
    require(bundle_counts(index)==manifest['counts'],'Planned/missing/cost inventory differs')
    require(manifest['compaction']['full_expected_semantic_sha256']=={r['id']:r['expected_sha256'] for r in index},'Preserved complete expectation hashes differ')
    graphs={k:graph_from_observable(read(folder/f'graphs/{k}/observable.json'),np.load(folder/f'graphs/{k}/scores.npy',allow_pickle=False)) for k in manifest['graphs']}
    if manifest['kind']=='dblp':require(all(re.fullmatch('r[0-9]{6}',n) for graph,_ in graphs.values() for n in graph),'Original record ID in natural bundle')
    checked={}
    for row in index:
        case=read(safe_path(folder,row['case_file']))
        require(set(case)==COMPACT_CASE_KEYS and case['status'] in STATUSES,'Unexpected compact case fields/status')
        require(all(case[k]==row[k] for k in CASE_KEYS-{'run','expected'}) and case['expected_sha256']==row['expected_sha256'],'Compact index/case identity differs')
        require(case['graph'] in graphs and case['method'] in s.NATURAL_METHODS,'Undeclared public case')
        require(type(case['budget']) is int and type(case['paid_lower_bound']) is int and type(case['paid_upper_bound']) is int
                and 0<=case['paid_lower_bound']<=case['paid_upper_bound']<=case['budget'],'Bad public paid bounds')
        require(row['has_run']==(case['run'] is not None) and row['recorded_paid_answers']==(len(case['run']['decisions']) if case['run'] else 0),'Compact run/paid index differs')
        if case['run'] is None:
            require(case['status']!='completed' and case['paid_lower_bound']==0 and case['expected_sha256'] is None,'Missing case fabricated as completed');continue
        complete=case['status']=='completed';run=visible_run(case['run'],complete)
        require(run==case['run'] and run['method']==case['method'] and run['requested_budget']==case['budget'],'Unlisted run data or case identity differs')
        replay=a.semantic(a.visible_replay(*graphs[case['graph']],run,complete=complete))
        require(semantic_hash(replay)==case['expected_sha256'],'Full candidate/action/partition/cost semantic replay hash differs')
        require(len(replay['events'])==case['paid_lower_bound'],'Confirmed paid count differs')
        if complete:require(case['paid_upper_bound']==run['spent']==case['paid_lower_bound'],'Complete paid count not exact')
        # Retain only evaluation inputs after the COMPLETE trace hash passed.
        # Full candidate/batch objects are discarded before the next case.
        checked[case['id']]={k:replay[k] for k in ('events','states','complete')}
        del replay,run,case
    if evaluate:
        evaluator=read(folder/'evaluator_reference.json')
        require(set(evaluator['references'])==set(graphs) and set(evaluator['cases'])==set(checked),'Evaluator inventory differs')
        for row in index:
            if row['id'] not in checked:continue
            refs=evaluator['references'][row['graph']]
            require(set(refs)==({'natural'} if manifest['kind']=='dblp' else {'H0','H9'}),'Evaluator references differ')
            require(set(evaluator['cases'][row['id']])==set(refs),'Missing paired evaluation')
            for name,truth in refs.items():require(a.evaluate_replay(checked[row['id']],truth)==evaluator['cases'][row['id']][name],'Offline evaluator metrics differ')
    return {'status':'PASS',**manifest['counts'],'layout':LAYOUT,'new_oracle_answers':0,'evaluator_checked':evaluate,
            'seconds':time.perf_counter()-started,'scope':'One-case saved-answer replay with complete semantic hash; no new experiment'}


def export_phase(phase, public_root, *, root=ROOT):
    """Export only verified saved final study artifacts; never launch a worker."""
    from cut_audit_er.telemetry import recover_journal
    root=Path(root).resolve();public_root=Path(public_root).resolve()
    frozen,snapshot=s.checked_freeze(root)
    study=root/s.SESSION/phase/'study';analysis=root/s.SESSION/phase/'analysis'
    manifest=read(analysis/'manifest.json');require(manifest.get('status')=='passed' and manifest['phase']==phase,'Analysis incomplete')
    s.check_hashes(analysis,manifest['files_sha256'])
    sources=read(analysis/'sources.json');s.check_hashes(study,sources['study_files_sha256'])
    require(sources['freeze_sha256']==digest(root/s.SESSION/'freeze.json'),'Analysis freeze differs')
    suite=read(study/'suite.json');rows,elapsed,pending=s.ledger_state(study,s.slots(phase))
    require(pending is None and rows==suite['runs'] and elapsed==suite['active_elapsed_seconds'],'Unfinished or changed ledger')
    require(phase in ('natural','synthetic'), 'Unsupported export phase')
    if phase=='natural':
        # Do not even load the excluded WDC matrix during public export.
        assets={}
        for name in NATURAL_GRAPHS:
            base=snapshot/'inputs/natural'/name
            assets[name]=graph_from_observable(read(base/'observable.json'),np.load(base/'scores.npy',allow_pickle=False))
    else:
        assets=s.load_phase_assets(snapshot,phase,include_truth=False)
    selected=set(NATURAL_GRAPHS) if phase=='natural' else SYNTHETIC_GRAPHS
    grouped={}
    for slot in rows:
        if slot['dataset'] not in selected: continue
        graph_key=NATURAL_GRAPHS[slot['dataset']] if phase=='natural' else slot['dataset']
        case={'id':slot['id'],'graph':graph_key,'method':slot['method'],'budget':slot['budget'],
              'status':slot['status'],'paid_lower_bound':0,'paid_upper_bound':0,'run':None}
        if slot.get('path'):
            path=s.relative(study,slot['path']);require(digest(path)==slot['sha256'],'Saved run hash differs')
            saved=read(path);require(saved['status']==slot['status'],'Saved status differs')
            recovery=recover_journal(study/'journals'/(slot['id']+'.jsonl'),saved['identity'])
            if slot['status']!='not_started_limit':
                case['paid_lower_bound']=recovery.get('paid_count_lower_bound') or 0
                high=recovery.get('paid_count_upper_bound');case['paid_upper_bound']=slot['budget'] if high is None else high
            if slot['status']=='completed': case['run']=saved['run']
            elif recovery.get('decisions'):
                case['run']={'method':slot['method'],'requested_budget':slot['budget'],**recovery}
        grouped.setdefault(graph_key,[]).append(case)
    reports=[]
    group_sets=[sorted(grouped)] if phase=='synthetic' else [[key] for key in sorted(grouped)]
    for keys in group_sets:
        name='synthetic' if phase=='synthetic' else keys[0]
        graphs={};references={}
        for key in keys:
            original=next((k for k,v in NATURAL_GRAPHS.items() if v==key),key)
            graphs[key]=assets[original][:2]
            if phase=='natural':
                references[key]={'natural':read(snapshot/f'inputs/natural/{original}/evaluator_reference.json')['reference']}
            else:
                references[key]={r:read(snapshot/f'inputs/synthetic/{r}.json')['reference'] for r in ('H0','H9')}
        cases=[case for row in rows for key in keys for case in grouped[key] if case['id']==row['id']]
        expected=150 if phase=='synthetic' else 21
        require(len(cases)==expected,'Public planned grid truncated')
        reports.append(write_bundle(public_root/'replay'/name,graphs,cases,references,
            kind='synthetic' if phase=='synthetic' else 'dblp',label='V5 '+name,
            source_hashes={'freeze':digest(root/s.SESSION/'freeze.json'),'study_suite':digest(study/'suite.json'),
                           'analysis_manifest':digest(analysis/'manifest.json')}))
    return {'status':'PASS','bundles':reports,'new_oracle_answers':0}


def compact_all(public_root,*,root=ROOT):
    root=Path(root).resolve();public=Path(public_root).resolve()
    require(public.is_relative_to(root),'Public compaction must remain inside the workspace')
    backup=root/s.SESSION/'public_replay_precompact'
    candidate=root/s.SESSION/'package_candidates/replay_compact'
    require(not backup.exists() and not candidate.exists(),'Fresh compaction preservation/candidate directories required')
    reports={}
    for name in ('synthetic','dblp_exposed','dblp_unused'):
        reports[name]=compact_bundle(public/'replay'/name,candidate/name)
    backup.mkdir(parents=True)
    for name in ('synthetic','dblp_exposed','dblp_unused'):
        source=(public/'replay'/name).resolve();target=(backup/name).resolve();new=(candidate/name).resolve()
        require(source.parent==(public/'replay').resolve() and target.is_relative_to(backup.resolve())
                and new.is_relative_to(candidate.resolve()) and not target.exists(),'Unsafe replay preservation move')
        source.rename(target);new.rename(source)
    return {'status':'PASS','bundles':reports,'backup_path':backup.relative_to(root).as_posix(),
            'all_original_bundles_preserved':True,'new_oracle_answers':0,
            'scope':'Exact full-semantic expectation hashing and compact case serialization; separate replay checks remain required'}


def promote_sources(root=ROOT, public_root=None, previous_receipt=None):
    """Explicit first-party dependency list; immutable historical/v4 is untouched."""
    root=Path(root).resolve();public=Path(public_root or root/'publication_v5').resolve()
    names=[f'src/cut_audit_er/{n}' for n in ENGINE_FILES]+list(SUPPORT_FILES)
    freeze_path=root/s.SESSION/'freeze.json'
    frozen=read(freeze_path) if freeze_path.is_file() else None
    previous=read(previous_receipt)['files_sha256'] if previous_receipt else {}
    pins={}
    for name in names:
        source=root/name;require(source.is_file() and not source.is_symlink(),'Missing first-party source: '+name)
        if frozen is not None and name in frozen['files_sha256']:
            require(digest(source)==frozen['files_sha256'][name], 'Frozen scientific source changed: '+name)
            snapshot=s.relative(root,frozen['source_snapshot'])/name
            require(snapshot.read_bytes()==source.read_bytes(), 'Public scientific source differs from frozen snapshot')
        target=public/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_bytes()!=source.read_bytes():
            require(name in ('scripts/review_v5/public_replay.py','tests/test_review_v5_public_replay.py')
                    and previous.get(name)==digest(target),'Public source already differs: '+name)
            preserved=root/s.SESSION/'public_replay_precompact'/'source'/name
            require(not preserved.exists(),'Prior delivery source already preserved')
            preserved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(target,preserved)
            shutil.copyfile(source,target)
        elif target.exists(): pass
        else: shutil.copyfile(source,target)
        pins[name]=digest(target)
    for name in ('scripts/__init__.py','scripts/review_v5/__init__.py','scripts/review_v4/__init__.py',
                 'scripts/conference_improvement/__init__.py','scripts/structural_study/__init__.py'):
        target=public/name;target.parent.mkdir(parents=True,exist_ok=True)
        source=root/name
        value=source.read_bytes() if source.is_file() else b''
        if frozen is not None and name in frozen['files_sha256']:
            require(hashlib.sha256(value).hexdigest()==frozen['files_sha256'][name], 'Frozen package initializer changed')
            require((s.relative(root,frozen['source_snapshot'])/name).read_bytes()==value,
                    'Package initializer differs from frozen snapshot')
        if target.exists(): require(target.read_bytes()==value,'Public package initializer differs: '+name)
        else:
            with target.open('xb') as stream:stream.write(value)
        pins[name]=digest(target)
    return {'status':'PASS','files_sha256':pins,'historical_v4_modified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','export','compact','promote-sources'))
    parser.add_argument('--bundle',type=Path);parser.add_argument('--phase',choices=('natural','synthetic'))
    parser.add_argument('--public-root',type=Path,default=ROOT/'publication_v5');parser.add_argument('--receipt',type=Path)
    parser.add_argument('--previous-receipt',type=Path)
    args=parser.parse_args()
    if args.action=='check':
        require(args.bundle is not None,'--bundle required');report=check_bundle(args.bundle)
    elif args.action=='export':
        require(args.phase is not None,'--phase required');report=export_phase(args.phase,args.public_root)
    elif args.action=='compact':report=compact_all(args.public_root)
    else: report=promote_sources(public_root=args.public_root,previous_receipt=args.previous_receipt)
    if args.receipt: save(args.receipt,report)
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':
    main()
