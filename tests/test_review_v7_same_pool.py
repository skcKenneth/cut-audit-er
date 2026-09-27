from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts.review_v7 import same_pool as s


def fixture(values=(4.,1.), bounds=(5.,2.), count=1):
    plans=[[[str(i),str(i+1)]] for i in range(len(values))]
    legal=plans; scored=plans[:count]; positive=count>0 and max(values[:count])>0
    strict=bool(positive and count<len(plans) and max(values[:count])>max(bounds[count:]))
    kind='empty_searched_pool' if not plans else 'all_searched_candidates_scored' if count==len(plans) else 'strict_upper_bound_separation' if strict else 'score_limit_uncertified'
    certified=bool(plans and (count==len(plans) or strict))
    win=min(range(count),key=lambda i:(-values[i],plans[i])) if count else None
    action=plans[win] if positive else [['f','g']]
    records=[dict(edges=q,proxy=v,utility=v,success_product=1.,upper_bound=b,upper_bound_finite=True,
                  was_scored=i<count,unscored_reason='scored' if i<count else 'strict_upper_bound_pruned' if strict else 'score_limit_unscored')
             for i,(q,v,b) in enumerate(zip(plans,values,bounds))]
    trace=dict(validated_order=legal,scored_order=scored,screening_order=legal,selected_plan=action if positive else [],
               score_records=[{k:r[k] for k in ('edges','proxy','utility','success_product')} for r in records[:count]])
    info=dict(candidate_trace=trace,candidate_actions=len(plans),scored_candidate_actions=count,
              unscored_candidate_actions=len(plans)-count,surrogate_certificate_status=kind,surrogate_argmax_certified=certified)
    audit=dict(status='passed',searched_pool_complete_audit=True,candidates=records,pool_count=len(plans),scored_count=count,
               certificate_status=kind,pool_argmax_certified=certified,certificate_for_selected_positive=positive and certified,
               fallback=not positive,selected_action=action,graph_wide_bonds_complete=False,diagnostic_score_accesses=12,diagnostic_seconds=.2)
    public={k:audit[k] for k in ('status','pool_count','scored_count','certificate_status','pool_argmax_certified','certificate_for_selected_positive','fallback','graph_wide_bonds_complete')}
    public.update(state=1,unique_state=1,phase='natural',dataset='fixture',budget=2,batch=1)
    return public,audit,dict(candidate_trace=trace,selection_info=info,planned_action=action)


def test_strict_exclusion_is_same_pool_count_not_speedup():
    row=s.reconcile(*fixture()); summary=s.summarize([row])
    assert row['strict_pruned_count']==1 and row['same_pool_additional_full_scores']==1
    assert row['scored_fraction']==.5 and row['positive_certificate']
    assert summary['speedup_claim'] is False and summary['gold_loaded'] is False


def test_all_scored_and_nonpositive_fallback_kept_distinct():
    row=s.reconcile(*fixture(values=(-1.,-2.),bounds=(1.,0.),count=2))
    assert row['certificate_status']=='all_searched_candidates_scored'
    assert row['fallback'] and row['pool_argmax_certified'] and not row['positive_certificate']
    assert row['strict_pruned_count']==0


def test_empty_pool_zero_denominator_is_missing_not_zero_fraction():
    row=s.reconcile(*fixture(values=(),bounds=(),count=0))
    assert row['scored_fraction'] is None and row['fallback']


def test_unseparated_score_limit_is_not_strict_pruning():
    row=s.reconcile(*fixture(values=(1.,1.),bounds=(3.,2.),count=1))
    assert row['score_limit_unscored_count']==1 and row['strict_pruned_count']==0
    assert not row['positive_certificate']


@pytest.mark.parametrize('problem',['count','reason','trace','score','bound','tie','certificate','coverage','missing'])
def test_reject_inconsistent_saved_sources(problem):
    public,audit,batch=fixture()
    if problem=='count': public['pool_count']=3
    if problem=='reason': audit['candidates'][1]['unscored_reason']='score_limit_unscored'
    if problem=='trace': batch['candidate_trace']['scored_order'].append([['z','zz']])
    if problem=='score': batch['candidate_trace']['score_records'][0]['proxy']=3.
    if problem=='bound': audit['candidates'][0]['upper_bound']=3.
    if problem=='tie': batch['planned_action']=[['1','2']]
    if problem=='certificate': public['certificate_status']='all_searched_candidates_scored'
    if problem=='coverage': public['graph_wide_bonds_complete']=True
    if problem=='missing': audit['searched_pool_complete_audit']=False
    with pytest.raises(ValueError): s.reconcile(public,audit,batch)


def test_hash_pin_and_escaping_source_fail(tmp_path):
    path=tmp_path/'source.json';path.write_text('{}')
    assert s.checked(tmp_path,'source.json',s.sha(path))==path
    with pytest.raises(ValueError,match='hash'): s.checked(tmp_path,'source.json','0'*64)
    with pytest.raises(ValueError,match='Unsafe'): s.checked(tmp_path,'../source.json','0'*64)


def test_fresh_output_and_descriptor_hash_enforced_before_reads(tmp_path):
    p=tmp_path/'pin.json';p.write_text('{}');out=tmp_path/'out';out.mkdir()
    with pytest.raises(ValueError,match='Fresh'):s.run(p,s.sha(p),out,root=tmp_path)
    with pytest.raises(ValueError,match='descriptor hash'):s.run(p,'0'*64,tmp_path/'fresh',root=tmp_path)
