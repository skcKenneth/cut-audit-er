"""Whitelist V6 scalar evidence; no pairs, topology, labels or record scores."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.review_v5 import study as s
from scripts.review_v6.audit_runner import checked_manifest

KEY=('id','run_id','dataset','budget','batch','phase')
VISIBLE=('certificate_status','certificate_for_selected_positive','pool_argmax_certified',
         'searched_pool_complete_audit','graph_wide_bonds_complete','pool_max_proxy','selected_proxy',
         'max_unscored_upper_bound','strict_margin','scored_count','pool_count',
         'diagnostic_score_accesses','diagnostic_seconds','fallback')
EVALUATION=('reference','fallback','selected_positive_certificate','single_batch_oracle_gap',
            'gap_fraction','gap_scope','best_known_gain_per_query','covered_fp','total_fp',
            'fp_coverage','zero_fp_denominator','candidate_occurrences','offline_seconds',
            'selected_fp_removed','selected_fn_added','selected_loss_gain','selected_query_cost',
            'selected_negative_answers','selected_positive_answers','selected_gain_per_query')
VALUE=('reference','depth','was_scored','selected','unscored_reason','fp_removed','fn_added',
       'loss_gain','query_cost','negative_answers','positive_answers','gain_per_query')


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, columns):
    with Path(path).open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def number(value):
    if value in ('',None): return None
    if isinstance(value,(int,float,bool,list,dict)): return value
    if value in ('True','False'):return value=='True'
    try:return json.loads(value)
    except (ValueError,TypeError):return value


def export(visible, evaluator, out, *, root=ROOT):
    visible,evaluator,out=Path(visible),Path(evaluator),Path(out)
    s.require(not out.exists(),'Fresh public evidence directory required')
    vm=checked_manifest(visible/'manifest.json',s.digest(visible/'manifest.json'),root=root)
    em=checked_manifest(evaluator/'manifest.json',s.digest(evaluator/'manifest.json'),root=root)
    s.require(em['source_manifest_sha256']==s.digest(visible/'manifest.json'),'Evaluator source mismatch')
    slots=read_csv(visible/'states.csv')
    summaries={r['id']:r for r in read_csv(visible/'summary.csv')}
    evaluations=read_csv(evaluator/'summary.csv')
    eval_status={r['id']:r for r in read_csv(evaluator/'states.csv')}
    s.require(len(slots)==301 and len({r['id'] for r in slots})==301,'Fixed physical state inventory differs')
    # Public ordinals link tables, never original record identities or partitions.
    index={r['id']:i+1 for i,r in enumerate(slots)}
    unique={}; visible_rows=[]
    for slot in slots:
        key=slot['id']; summary=summaries.get(key,{})
        statehash=summary.get('state_sha256')
        if statehash and statehash not in unique: unique[statehash]=len(unique)+1
        row={name:slot.get(name,'') for name in KEY}
        row.update(state=index[key],unique_state=unique.get(statehash,''),status=slot['status'])
        row.update({name:summary.get(name,'') for name in VISIBLE})
        visible_rows.append(row)
    evaluation_rows=[]
    lookup={(r['id'],r['reference']):r for r in evaluations}
    for slot in slots:
        refs=('H0','H9') if slot['phase']=='synthetic' else ('natural',)
        for reference in refs:
            row={name:slot.get(name,'') for name in KEY}
            found=lookup.get((slot['id'],reference),{})
            row.update(state=index[slot['id']],reference=reference,
                       status=found.get('status',eval_status.get(slot['id'],{}).get('status','unknown')))
            row.update({name:found.get(name,'') for name in EVALUATION if name!='reference'})
            evaluation_rows.append(row)
    histogram=Counter()
    for row in read_csv(evaluator/'candidates.csv'):
        histogram[(index[row['id']],*(row.get(k,'') for k in VALUE))]+=1
    hist_rows=[dict(zip(('state',*VALUE),key),count=count) for key,count in sorted(histogram.items())]
    out.mkdir(parents=True)
    write_csv(out/'visible_states.csv',visible_rows,(*KEY,'state','unique_state','status',*VISIBLE))
    write_csv(out/'evaluation_states.csv',evaluation_rows,(*KEY,'state','status',*EVALUATION))
    write_csv(out/'candidate_value_histogram.csv',hist_rows,('state',*VALUE,'count'))
    groups=defaultdict(list)
    for row in evaluation_rows:groups[row['dataset'],row['reference']].append(row)
    grouped=[]
    for (dataset,reference),rr in sorted(groups.items()):
        complete=[r for r in rr if r['single_batch_oracle_gap']!='']
        grouped.append({'dataset':dataset,'reference':reference,'planned_states':len(rr),
                        'evaluated_states':len(complete),'unknown_states':len(rr)-len(complete),
                        'positive_realized_gap_states':sum(float(r['single_batch_oracle_gap'])>0 for r in complete),
                        'zero_realized_gap_states':sum(float(r['single_batch_oracle_gap'])==0 for r in complete),
                        'certified_positive_states':sum(number(r['selected_positive_certificate']) is True for r in complete),
                        'certified_positive_gap_states':sum(number(r['selected_positive_certificate']) is True and float(r['single_batch_oracle_gap'])>0 for r in complete),
                        'fallback_states':sum(number(r['fallback']) is True for r in complete),
                        'maximum_realized_gap':max((float(r['single_batch_oracle_gap']) for r in complete),default=None)})
    public_summary={'schema':'cut-audit-v6-scalar-evidence-summary','physical_states':len(slots),
                    'reference_slots':len(evaluation_rows),'unique_visible_states':len(unique),
                    'visible_status_counts':dict(Counter(r['status'] for r in visible_rows)),
                    'graph_wide_bonds_complete_states':sum(number(r['graph_wide_bonds_complete']) is True for r in visible_rows),
                    'deduplicated_reference_summary':[
                        {'phase':phase,'reference':reference,
                         'unique_evaluated_states':len({unique[summaries[r['id']]['state_sha256']] for r in evaluation_rows if r['phase']==phase and r['reference']==reference and r['single_batch_oracle_gap']!=''}),
                         'unique_positive_gap_states':len({unique[summaries[r['id']]['state_sha256']] for r in evaluation_rows if r['phase']==phase and r['reference']==reference and r['single_batch_oracle_gap']!='' and float(r['single_batch_oracle_gap'])>0})}
                        for phase,reference in (('natural','natural'),('synthetic','H0'),('synthetic','H9'))],
                    'groups':grouped,'new_acquisitions':0,'new_oracle_answers':0,
                    'scope':'Full-reached states; dependent budgets/references. Hindsight single-batch gaps, not expected regret.',
                    'candidate_identity_revalidation_possible':False}
    s.write(out/'summary.json',public_summary)
    external_path=root/'outputs/session_20260927_v6/external/final_manifest.json'
    external=s.read(external_path)
    s.require(external['status']=='blocked_download' and len(external['runs'])==21
              and external['acquisitions_started']==0,'Unexpected external outcome requires explicit export review')
    external_fields=('id','dataset','method','budget','status','reason','fp','fn','loss','paid_queries')
    write_csv(out/'external_endpoints.csv',external['runs'],external_fields)
    status_keys=('status','planned_slots','acquisitions_started','acquisitions_completed',
                 'archive_downloads','new_model_fits','paid_queries','v5_progression_gate_changed',
                 'sealed_test_access','alternative_benchmark_used','provider_receipt_sha256')
    s.write(out/'external_status.json',{**{k:external[k] for k in status_keys},
        'provider_url':'https://github.com/merialdo/research.alaska',
        'provider_issue_url':'https://github.com/merialdo/research.alaska/issues/2',
        'source_final_manifest_sha256':s.digest(external_path),
        'scope':'V6 external branch not executed. V5 gate exclusions remain historical.'})
    manifest={'schema':'cut-audit-v6-public-scalar-evidence','created_utc':s.utc(),
              'source_visible_manifest_sha256':s.digest(visible/'manifest.json'),
              'source_evaluator_manifest_sha256':s.digest(evaluator/'manifest.json'),
              'files_sha256':{p.name:s.digest(p) for p in sorted(out.iterdir())},
              'redaction':'No record/pair IDs, reference mapping, topology, partition hashes, pair scores, raw text or local absolute paths.',
              'histogram_scope':'Candidate outcome groups within a batch; count is multiplicity, not independent opportunity.',
              'new_oracle_answers':0}
    s.write(out/'manifest.json',manifest)
    return public_summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--visible',type=Path,required=True);p.add_argument('--evaluator',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(s.blob(export(a.visible,a.evaluator,a.out)).decode())
