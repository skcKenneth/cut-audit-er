"""Finite scalar rendering checks; fixtures never become research evidence."""
import importlib.util
from pathlib import Path
import matplotlib.pyplot as plt
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


f=module('make_figures_v7');site=module('build_site_v7')


def constructed_controls():
    names=('bayes_null_100','path_aligned','path_reversal','two_edge_batch')
    summary={'cases':[dict(case=name,expected_decision_gap_float=x,expected_hindsight_gap_float=y) for name,x,y in zip(names,(0,0,.15,.875),(.9,.5,.65,1.0))]}
    actions=[dict(case=case,action_id=f'q{i:03}',proxy_float=.5 if i!=1 else .45,expected_value_float=1. if i!=1 else 1.2)
             for case in ('path_aligned','path_reversal') for i in range(3)]
    return summary,actions


def constructed_same_pool():
    return {'states':301,'groups':[dict(phase=phase,pool_count=n,scored_count=k) for phase,n,k in [('natural',73000,250),('synthetic',490,120)]]}


@pytest.mark.parametrize('name',['contract','natural','realized_gap','known_law','cost'])
def test_finite_figures_preserve_text_size_and_canvas_bounds(name,tmp_path):
    legacy=ROOT/'historical/v5/evidence';f.v6.style()
    if name=='contract':fig,data=f.contract()
    elif name=='natural':fig,data=f.natural(f.table(legacy,'acquisitions'))
    elif name=='realized_gap':
        rows=[dict(phase='natural',dataset=d,selected_gain_per_query=0,best_known_gain_per_query=1,single_batch_oracle_gap=1)
              for d,n in zip(f.DATASETS,(73,84,84)) for _ in range(n)]
        fig,data=f.realized_gap(rows)
    elif name=='known_law':fig,data=f.known_law(*constructed_controls())
    else:fig,data=f.cost(f.table(legacy,'acquisitions'),f.table(legacy,'batches'),constructed_same_pool())
    (tmp_path/'data').mkdir()
    record=f.v6.save(fig,tmp_path,name,data)
    assert record['minimum_font_pt']>=8 and record['text_bounds_within_canvas']
    if name=='natural':assert record['height_inches']<=2.6
    if name=='known_law':assert record['height_inches']<=3


def test_natural_projection_retains_zero_and_all_missing_cases():
    rows=f.table(ROOT/'historical/v5/evidence','acquisitions');f.v6.style()
    fig,data=f.natural(rows)
    try:
        assert len(data['all_natural_slots'])==63 and len(data['contrasts'])==18
        assert all(r['delta_loss']==0 for r in data['contrasts'] if r['control']=='cut_plan_fixed')
    finally:plt.close(fig)
    next(r for r in rows if r['phase']=='natural' and r['method']=='cut_plan_cover_fixed')['status']='timeout'
    fig,data=f.natural(rows)
    try:assert data['missing_slots']==1 and sum(r['delta_loss'] is None for r in data['contrasts'])==2
    finally:plt.close(fig)


def test_all_controls_required_and_no_natural_regret_claim():
    summary,actions=constructed_controls();summary['cases'].pop()
    with pytest.raises(ValueError,match='four'):f.known_law(summary,actions)
    assert 'known-law' in site.FIGURES[4][3].lower() or 'constructed controls' in site.FIGURES[4][3].lower()
    assert 'not decision-error rates' in site.FIGURES[3][3]


def test_site_stems_and_bilingual_strings():
    assert tuple(r[0] for r in site.FIGURES)==f.PLOT_NAMES
    assert 'fig05_synthetic' not in f.PLOT_NAMES
    assert '&lt;script&gt;' in site.bilingual('<script>','範例')
    assert 'localStorage' in site.JS and 'fetch(' not in site.JS
