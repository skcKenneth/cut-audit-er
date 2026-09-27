"""Synthetic accounting fixtures; not research acquisitions or measured results."""
from copy import deepcopy
import pytest
from scripts.review_v6.validate_evidence import validate_rows


def fixture():
    visible=[]; evaluated=[]
    for state in range(1,302):
        phase='natural' if state<=241 else 'synthetic'
        visible.append({'state':str(state),'phase':phase,'pool_count':'1',
                        'searched_pool_complete_audit':'True'})
        for reference in (('natural',) if phase=='natural' else ('H0','H9')):
            evaluated.append({'state':str(state),'reference':reference,'single_batch_oracle_gap':''})
    evaluated[0].update(single_batch_oracle_gap='2.0',selected_query_cost='2',
        selected_fp_removed='2',selected_fn_added='0',selected_loss_gain='2',
        selected_negative_answers='1',selected_positive_answers='1',selected_gain_per_query='1.0',
        candidate_occurrences='1',best_known_gain_per_query='3.0',gap_fraction='[2,1]',
        total_fp='0',covered_fp='0',fp_coverage='')
    histogram=[{'state':'1','reference':'natural','count':'1','query_cost':'1',
        'fp_removed':'3','fn_added':'0','loss_gain':'3','negative_answers':'1','positive_answers':'0',
        'gain_per_query':'3.0'}]
    return visible,evaluated,histogram


def test_missing_reference_slots_remain_and_zero_denominator():
    result=validate_rows(*fixture())
    assert result['evaluated_reference_states']==1
    assert result['unknown_reference_states']==360
    assert result['positive_gap_reference_states']==1


@pytest.mark.parametrize('field,value,message',[
    ('loss_gain','4','conservation'),('positive_answers','1','payment'),
    ('gain_per_query','4','normalization'),('count','2','denominator'),
])
def test_corrupt_candidate_arithmetic_is_rejected(field,value,message):
    visible,evaluated,histogram=fixture();histogram[0][field]=value
    with pytest.raises(ValueError,match=message):validate_rows(visible,evaluated,histogram)


def test_unknown_state_cannot_hide_candidate_values():
    visible,evaluated,histogram=fixture();evaluated[0]['single_batch_oracle_gap']=''
    with pytest.raises(ValueError,match='Missing state'):validate_rows(visible,evaluated,histogram)


def test_noop_protects_against_negative_selected_gain():
    visible,evaluated,histogram=fixture()
    evaluated[0].update(selected_fp_removed='0',selected_fn_added='2',selected_loss_gain='-2',
        selected_gain_per_query='-1.0',single_batch_oracle_gap='1.0',best_known_gain_per_query='0.0',gap_fraction='[1,1]')
    histogram[0].update(fp_removed='0',fn_added='3',loss_gain='-3',gain_per_query='-3.0')
    assert validate_rows(visible,evaluated,histogram)['positive_gap_reference_states']==1


def test_exact_fraction_gap_must_match():
    visible,evaluated,histogram=fixture();evaluated[0]['gap_fraction']='[3,2]'
    with pytest.raises(ValueError,match='Exact gap'):validate_rows(visible,evaluated,histogram)


def test_zero_denominator_is_not_zero_percent():
    visible,evaluated,histogram=fixture();evaluated[0]['fp_coverage']='0.0'
    with pytest.raises(ValueError,match='coverage denominator'):validate_rows(visible,evaluated,histogram)


def test_all_fixed_slots_required():
    visible,evaluated,histogram=fixture()
    with pytest.raises(ValueError,match='inventory'):validate_rows(visible[:-1],evaluated,histogram)
