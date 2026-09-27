"""Reconcile saved V6 Full pools, original scoring traces and public counts.

No selector, score computation, evaluator reference or acquisition is executed.
Counts describe the same reached state and searched pool, not a speedup.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = 'publication_v6/evidence/manifest.json'
AUDIT = 'outputs/session_20260927_v6/visible/manifest.json'
INPUTS = 'outputs/session_20260927_v6/inputs/visible_inputs/manifest.json'
FIELDS = ('state','unique_state','phase','dataset','budget','batch','status','certificate_status',
          'pool_count','scored_count','strict_pruned_count','score_limit_unscored_count',
          'positive_certificate','pool_argmax_certified','fallback','graph_wide_bonds_complete',
          'same_pool_additional_full_scores','scored_fraction','diagnostic_score_accesses','diagnostic_seconds')


def require(value, message):
    if not value: raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''): digest.update(chunk)
    return digest.hexdigest()


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def blob(data): return (json.dumps(data, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def checked(root, name, pin):
    root = Path(root).resolve(); relative = Path(name)
    require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe source path')
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file() and sha(path) == pin, 'Source hash mismatch: '+name)
    return path


def manifest(path, pin):
    path = Path(path); require(sha(path) == pin, 'Manifest hash mismatch')
    data = read(path); require(bool(data.get('files_sha256')), 'Missing manifest payload pins')
    for name, value in data['files_sha256'].items(): checked(path.parent, name, value)
    return data


def scalar(value):
    if value in ('True','False'): return value == 'True'
    if value == '': return None
    try: return json.loads(value)
    except (ValueError,TypeError): return value


def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return [{k:scalar(v) for k,v in row.items()} for row in csv.DictReader(stream)]


def plan(value): return tuple(sorted(tuple(sorted(edge)) for edge in value))


def reconcile(public, audit, batch):
    """Check counts and semantics independently of the historical exporter."""
    require(public['status'] == audit['status'] == 'passed', 'Incomplete state; cannot assert same-pool comparison')
    require(audit['searched_pool_complete_audit'] is True, 'Pool audit incomplete')
    trace, info = batch['candidate_trace'], batch['selection_info']
    require(trace == info['candidate_trace'], 'Trace copies differ')
    records = audit['candidates']; candidates = [plan(c['edges']) for c in records]
    legal = [plan(q) for q in trace['validated_order']]
    scored = [plan(q) for q in trace['scored_order']]
    require(len(candidates) == len(set(candidates)) and candidates == legal, 'Full pool identity/order mismatch')
    require(len(scored) == len(set(scored)) and set(scored) <= set(legal), 'Scored candidate identity mismatch')
    lookup = dict(zip(candidates, records)); n, k = len(legal), len(scored)
    require(k <= 64, 'Original complete-score limit exceeded')
    saved_scores = {plan(c['edges']):c for c in trace['score_records']}
    require(len(saved_scores) == len(trace['score_records']) == k and set(saved_scores)==set(scored), 'Score records mismatch')
    for q,c in saved_scores.items():
        require(all(c[key]==lookup[q][key] for key in ('proxy','utility','success_product')), 'Original computed score differs')
    require(n == public['pool_count'] == audit['pool_count'] == info['candidate_actions'], 'Pool count mismatch')
    require(k == public['scored_count'] == audit['scored_count'] == info['scored_candidate_actions'], 'Scored count mismatch')
    require(n-k == info['unscored_candidate_actions'], 'Unscored count mismatch')
    require(all(c['was_scored'] is (q in set(scored)) for q,c in lookup.items()), 'Candidate scoring flags mismatch')
    require(all(math.isfinite(c['proxy']) for c in records), 'Nonfinite proxy')
    require(all(not c['upper_bound_finite'] or c['proxy'] <= c['upper_bound'] for c in records), 'Upper bound violated')
    require([plan(q) for q in trace['screening_order']][:k] == scored, 'Scoring prefix differs')
    expected = sorted(legal, key=lambda q: (-lookup[q]['upper_bound'] if lookup[q]['upper_bound_finite'] else -math.inf, len(q), q))
    require([plan(q) for q in trace['screening_order']] == expected, 'Bound order/tie differs')
    if scored:
        winner = min(scored, key=lambda q: (-lookup[q]['proxy'], len(q), q))
        best = lookup[winner]['proxy']
    else: winner, best = None, None
    missing = [q for q in legal if q not in set(scored)]
    max_bound = max((lookup[q]['upper_bound'] if lookup[q]['upper_bound_finite'] else math.inf for q in missing), default=None)
    strict = bool(winner and best > 0 and missing and best > max_bound)
    kind = ('empty_searched_pool' if not n else 'all_searched_candidates_scored' if not missing
            else 'strict_upper_bound_separation' if strict else 'score_limit_uncertified')
    certified = bool(n and (not missing or strict))
    positive = bool(winner and best > 0)
    require(kind == public['certificate_status'] == audit['certificate_status'] == info['surrogate_certificate_status'], 'Certificate status mismatch')
    require(certified == audit['pool_argmax_certified'] == public['pool_argmax_certified'] == info['surrogate_argmax_certified'], 'Certificate Boolean mismatch')
    require((positive and certified) == audit['certificate_for_selected_positive'] == public['certificate_for_selected_positive'], 'Positive certificate mismatch')
    require((not positive) == audit['fallback'] == public['fallback'], 'Fallback mismatch')
    require(audit['selected_action'] == batch['planned_action'], 'Actual planned action differs')
    if positive:
        require(plan(audit['selected_action']) == winner == plan(trace['selected_plan']), 'Selected action/tie mismatch')
    if certified:
        require(winner == min(legal, key=lambda q: (-lookup[q]['proxy'],len(q),q)), 'Same-pool argmax mismatch')
    reasons = Counter(c['unscored_reason'] for c in records)
    require(set(reasons) <= {'scored','strict_upper_bound_pruned','score_limit_unscored'}, 'Unknown candidate omission reason')
    require(reasons['scored'] == k and reasons['strict_upper_bound_pruned'] == (n-k if strict else 0)
            and reasons['score_limit_unscored'] == (n-k if missing and not strict else 0), 'Unscored reasons mismatch')
    require(audit['graph_wide_bonds_complete'] == public['graph_wide_bonds_complete'], 'Graph coverage mismatch')
    row = {name:public[name] for name in ('state','unique_state','phase','dataset','budget','batch','status')}
    row.update(certificate_status=kind,pool_count=n,scored_count=k,
               strict_pruned_count=reasons['strict_upper_bound_pruned'],score_limit_unscored_count=reasons['score_limit_unscored'],
               positive_certificate=positive and certified,pool_argmax_certified=certified,fallback=not positive,
               graph_wide_bonds_complete=audit['graph_wide_bonds_complete'],same_pool_additional_full_scores=n-k,
               scored_fraction=k/n if n else None,diagnostic_score_accesses=audit['diagnostic_score_accesses'],
               diagnostic_seconds=audit['diagnostic_seconds'])
    return row


def summarize(rows):
    groups = []
    for phase in ('natural','synthetic'):
        rr = [r for r in rows if r['phase'] == phase]
        counts = {key:sum(r[key] for r in rr) for key in ('pool_count','scored_count','strict_pruned_count','score_limit_unscored_count')}
        groups.append(dict(phase=phase,states=len(rr),**counts,
                           positive_certificate_states=sum(r['positive_certificate'] for r in rr),
                           fallback_states=sum(r['fallback'] for r in rr),
                           all_scored_states=sum(r['certificate_status']=='all_searched_candidates_scored' for r in rr),
                           strict_pruned_states=sum(r['certificate_status']=='strict_upper_bound_separation' for r in rr),
                           uncertified_states=sum(r['certificate_status']=='score_limit_uncertified' for r in rr),
                           graph_wide_bonds_complete_states=sum(r['graph_wide_bonds_complete'] for r in rr)))
    return {'schema':'cut-audit-v7-same-pool-summary-v1','states':len(rows),'groups':groups,
            'scope':'Saved Full reached states and the same searched pool; dependent budgets; counts are not independent opportunities.',
            'counterfactual':'One complete proxy evaluation for every legal pool member versus original recorded complete scores.',
            'excluded_costs_from_count':'Generation, legality, numeric scans, upper bounds, sorting, caches and fallback still cost computation.',
            'speedup_claim':False,'new_acquisitions':0,'new_score_computations':0,'gold_loaded':False}


def run(source_manifest, source_hash, out, root=ROOT):
    out=Path(out); require(not out.exists(), 'Fresh same-pool output directory required')
    source_manifest=Path(source_manifest); require(sha(source_manifest)==source_hash,'Source descriptor hash mismatch')
    sources=read(source_manifest); require(sources['schema']=='cut-audit-v7-same-pool-sources-v1','Source descriptor schema')
    require(set(sources['files_sha256'])=={PUBLIC,AUDIT,INPUTS},'Fixed source manifest inventory differs')
    loaded={name:manifest(checked(root,name,pin),pin) for name,pin in sources['files_sha256'].items()}
    pm,am,im=loaded[PUBLIC],loaded[AUDIT],loaded[INPUTS]
    require(pm['source_visible_manifest_sha256']==sources['files_sha256'][AUDIT]
            and am['source_manifest_sha256']==sources['files_sha256'][INPUTS], 'Source chain mismatch')
    for name,pin in im['source_receipts'].items(): checked(root,name,pin)
    require(am['planned_states']==am['completed_states']==301 and am['technical_mismatch_count']==0
            and am['phase_counts']=={'natural':241,'synthetic':60}, 'Fixed audit scope mismatch')
    public=csv_rows(Path(root)/Path(PUBLIC).parent/'visible_states.csv')
    jobs={r['id']:r for r in im['jobs']};slots={r['id']:r for r in am['rows']}
    require(len(public)==len(jobs)==len(slots)==301 and set(r['id'] for r in public)==set(jobs)==set(slots),'State inventory mismatch')
    rows=[]; replays={}
    for row in public:
        job=jobs[row['id']]; slot=slots[row['id']]
        require(all(row[k]==job[k]==slot[k] for k in ('phase','dataset','budget','batch')),'State metadata mismatch')
        replayname=job['replay']
        if replayname not in replays: replays[replayname]=read(Path(root)/Path(INPUTS).parent/replayname)
        replay=replays[replayname]
        require(replay['run_id']==row['run_id'] and replay['complete'] is True, 'Raw replay incomplete/mislinked')
        batches=[b for b in replay['batches'] if b['batch']==job['batch']]
        require(len(batches)==1,'Missing/duplicate raw batch')
        audit=read(Path(root)/Path(AUDIT).parent/slot['result_file'])
        rows.append(reconcile(row,audit,batches[0]))
    summary=summarize(rows); out.mkdir(parents=True)
    with (out/'same_pool_states.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    (out/'same_pool_summary.json').write_bytes(blob(summary))
    result={'schema':'cut-audit-v7-same-pool-v1','status':'PASS','source_manifest_sha256':source_hash,
            'files_sha256':{p.name:sha(p) for p in sorted(out.iterdir())},'program_sha256':sha(Path(__file__)),
            'independent_check':'Saved candidate identities, scoring prefix, strict bounds, tie rules, counts and fallback reconciled; no scores recomputed.',
            'new_acquisitions':0,'new_score_computations':0}
    (out/'manifest.json').write_bytes(blob(result)); return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-manifest',type=Path,required=True)
    p.add_argument('--source-manifest-sha256',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); print(blob(run(a.source_manifest,a.source_manifest_sha256,a.out)).decode())
