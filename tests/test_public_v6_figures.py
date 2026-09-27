"""Finite public plotting tests; constructed outcomes are never study evidence."""
import importlib.util
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


f=module('make_figures_v6')
site=module('build_site_v6')


def constructed_evaluations():
    rows=[];state=0
    for dataset,n in zip(f.DATASETS,(73,84,84)):
        for _ in range(n):
            state+=1
            rows.append({'state':state,'dataset':dataset,'phase':'natural','reference':'natural',
                         'single_batch_oracle_gap':0.,'selected_gain_per_query':0.,'best_known_gain_per_query':0.})
    for k in (1,2,3):
        for profile in ('uniform','ranked'):
            for _ in range(10):
                state+=1
                for reference in ('H0','H9'):
                    rows.append({'state':state,'dataset':f'k{k}_{profile}','phase':'synthetic','reference':reference,
                                 'single_batch_oracle_gap':1.,'selected_gain_per_query':0.,'best_known_gain_per_query':1.})
    return rows


def test_all_fixed_groups_preserved_and_missing_not_zero():
    rows=constructed_evaluations();rows[0]['single_batch_oracle_gap']=None
    rows[1]['gap_scope']='lower_bound_over_known_candidates_plus_actual_plus_noop'
    groups=f.evaluation_groups(rows)
    assert len(groups)==15 and sum(g['planned'] for g in groups)==361
    assert groups[0]['planned']==73 and groups[0]['evaluated']==72 and groups[0]['unknown']==1
    assert groups[0]['partial_lower_bounds']==1
    assert sum(g['positive'] for g in groups)==120


def test_hash_mismatch_rejected_before_render(tmp_path):
    (tmp_path/'table.csv').write_text('changed')
    (tmp_path/'manifest.json').write_text(json.dumps({'files_sha256':{'table.csv':'a'*64}}))
    with pytest.raises(ValueError,match='hash mismatch'):f.check_manifest(tmp_path)


def test_natural_projection_has_all_63_slots_and_zero_full_raw():
    f.style();fig,projection=f.natural(f.table(ROOT/'historical/v5/evidence','acquisitions'))
    try:
        assert len(projection['acquisitions'])==63
        assert {r['dataset'] for r in projection['acquisitions']}==set(f.DATASETS)
        assert len(projection['contrasts'])==18
        assert all(r['delta_loss']==0 for r in projection['contrasts'] if r['control']=='cut_plan_fixed')
    finally:plt.close(fig)


def test_cost_uses_four_contemporaneous_arms_and_separate_units():
    legacy=ROOT/'historical/v5/evidence';f.style()
    fig,projection=f.cost(f.table(legacy,'acquisitions'),f.table(legacy,'batches'))
    try:
        assert len(projection['acquisitions'])==36
        by_method={r['method']:r for r in projection['totals']}
        assert by_method['cut_plan_fixed']['full_scores']==15416
        assert by_method['cut_plan_cover_fixed']['full_scores']==256
        assert by_method['cut_plan_fixed']['logical_score_accesses']==3617360
        assert by_method['cut_plan_cover_fixed']['logical_score_accesses']==13213720
        assert all(r['completed']==r['slots']==9 and r['nested_timers_not_summed'] for r in by_method.values())
    finally:plt.close(fig)


def test_constructed_gap_figure_retains_inventory_and_text_bounds(tmp_path):
    f.style();fig,projection=f.realized_gap(constructed_evaluations())
    (tmp_path/'data').mkdir()
    result=f.save(fig,tmp_path,'constructed_fixture',projection)
    assert result['minimum_font_pt']>=8 and result['text_bounds_within_canvas']
    assert projection['points_plotted']==361 and len(projection['groups'])==15


def test_contract_vector_render_is_byte_deterministic(tmp_path):
    outputs=[]
    for name in ('first','second'):
        folder=tmp_path/name;(folder/'data').mkdir(parents=True);f.style()
        fig,projection=f.contract();result=f.save(fig,folder,'constructed_contract',projection)
        outputs.append(result['files_sha256'])
    assert outputs[0]==outputs[1]


@pytest.mark.parametrize('name',['natural','cost'])
def test_historical_public_figure_text_bounds(name,tmp_path):
    legacy=ROOT/'historical/v5/evidence';f.style()
    if name=='natural':fig,projection=f.natural(f.table(legacy,'acquisitions'))
    else:fig,projection=f.cost(f.table(legacy,'acquisitions'),f.table(legacy,'batches'))
    (tmp_path/'data').mkdir()
    result=f.save(fig,tmp_path,name,projection)
    assert result['minimum_font_pt']>=8 and result['text_bounds_within_canvas']


def test_bilingual_site_content_escapes_text_and_has_six_figures():
    assert len(site.FIGURES)==6
    text=site.bilingual('<example>','繁體中文','h2')
    assert '&lt;example&gt;' in text and '<example>' not in text
    assert 'localStorage' in site.JS and 'fetch(' not in site.JS
    assert '@media(max-width:720px)' in site.CSS
