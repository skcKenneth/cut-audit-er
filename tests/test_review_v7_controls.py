"""Known-law correctness fixtures, not additional natural-data experiments."""
from copy import deepcopy
from fractions import Fraction as F
import inspect
import json
from pathlib import Path

import pytest

from scripts.review_v7 import controls as c, evaluate as e


SPECS = json.loads((Path(__file__).parents[1]/'configs/review_v7_controls.json').read_text())['cases']


@pytest.fixture(scope='module')
def results():
    return {s['id']: (c.audit_initial_decision(c.visible_case(s))) for s in SPECS}


@pytest.mark.parametrize('spec', SPECS, ids=lambda s: s['id'])
def test_visible_candidate_pool_certificate_and_cold_isolation(spec, results):
    first = results[spec['id']]
    second = c.audit_initial_decision(c.visible_case(spec))
    assert c.semantic(first) == c.semantic(second)
    assert first['positive_pool_certificate'] and not first['fallback']
    assert first['new_oracle_answers'] == 0
    assert first['scored_count'] <= 64
    assert first['pool_count'] >= first['scored_count']


@pytest.mark.parametrize('spec', SPECS, ids=lambda s: s['id'])
def test_exact_evaluation_identity_and_expected_winner(spec, results):
    decision = results[spec['id']]
    out = e.evaluate_case(spec, decision)
    summary = out['summary']
    assert F(summary['expected_hindsight_gap']) == F(summary['evpi']) + F(summary['expected_decision_gap'])
    expected_gap = {'bayes_null_100': F(0), 'path_aligned': F(0),
                    'path_reversal': F(3,20), 'two_edge_batch': F(7,8)}
    assert F(summary['expected_decision_gap']) == expected_gap[spec['id']]
    for r in out['actions']:
        assert F(r['expected_value']) == (F(r['expected_fp_removed'])-F(r['expected_fn_added']))/r['depth']
        assert F(r['both_exact']) == F(r['expected_value'])
        assert F(r['expected_value'])-F(r['proxy_exact']) == F(r['probability_approximation_term'])+F(r['conditional_approximation_term'])


def test_path_complete_marginals_and_isolated_conditioning(results):
    spec = SPECS[2]
    out = e.evaluate_case(spec, results[spec['id']])
    assert out['summary']['world_count'] == 8
    rows = out['actions']
    assert [F(r['expected_value']) for r in rows] == [F(21,20), F(6,5), F(21,20)]
    assert [F(r['proxy_exact']) for r in rows] == [F(20979,40000), F(9531,20000), F(20979,40000)]
    assert all(r['depth'] == 1 and F(r['probability_approximation_term']) == 0 for r in rows)
    assert all(F(r['conditional_same_sum']) == 0 for r in rows)


def test_matching_analytic_no_enumeration(results):
    out = e.evaluate_case(SPECS[0], results['bayes_null_100'])
    assert not out['worlds'] and not out['world_actions']
    assert F(out['summary']['positive_hindsight_probability']) == F(9,10)*(1-F(91,100)**99)
    assert F(out['summary']['expected_decision_gap']) == 0
    with pytest.raises(ValueError, match='analytic'):
        e.reference_worlds(SPECS[0], results['bayes_null_100']['visible'])


def test_two_edge_expected_decomposition_and_committed_positive(results):
    out = e.evaluate_case(SPECS[3], results['two_edge_batch'])
    q = next(r for r in out['actions'] if r['action'] == [['A0','B0'], ['A1','B1']])
    assert F(q['proxy_exact']) == -F(3,64)
    assert F(q['expected_value']) == F(9,8)
    assert F(q['probability_only']) == -F(3,16)
    assert F(q['conditional_only']) == F(9,32)
    assert F(out['summary']['evpi']) == F(3,16)
    assert F(out['summary']['positive_hindsight_probability']) == F(1,4)
    positive = [r for r in out['world_actions'] if r['action_id'] == q['action_id'] and r['events'][0]['answer']]
    assert positive and all(r['cost'] == 2 and len(r['events']) == 2 and r['gain'] == 0 for r in positive)
    negative = [r for r in out['world_actions'] if r['action_id'] == q['action_id'] and not r['events'][0]['answer']]
    assert all(r['events'][0]['loss'] == r['before']['loss'] and r['gain'] == 9 for r in negative)


@pytest.mark.parametrize('key', ['gold', 'reference', 'headroom', 'selected_world', 'result'])
def test_visible_spec_rejects_hidden_inputs(key):
    spec = {**SPECS[1], key: {}}
    with pytest.raises(ValueError, match='realized gold'):
        c.visible_case(spec)


def test_evaluator_world_changes_do_not_modify_visible_or_selector(results):
    original = deepcopy(results['path_reversal'])
    digest = c.fingerprint(c.semantic(original))
    for world in e.reference_worlds(SPECS[2], original['visible']):
        e.realized_batch(original['visible'], world['reference'], original['selected_action'])
        assert c.fingerprint(c.semantic(original)) == digest
    assert 'reference' not in inspect.signature(c.audit_initial_decision).parameters
    assert 'evaluate' not in inspect.getsource(c)
    # No selector is invoked by the reference-only module.
    assert 'select_covered_plan' not in inspect.getsource(e)


@pytest.mark.parametrize('tamper', ['weight', 'membership', 'marginal', 'duplicate'])
def test_invalid_world_laws_fail(tamper):
    visible = c.visible_case(SPECS[1]); worlds = e.reference_worlds(SPECS[1], visible)
    if tamper == 'weight': worlds[0]['weight'] = '0'
    elif tamper == 'membership': worlds[0]['reference'].pop('v0')
    elif tamper == 'marginal': worlds[-1]['reference'] = {n:'same' for n in visible['nodes']}
    else: worlds[-1]['id'] = worlds[0]['id']
    with pytest.raises(ValueError): e.validate_worlds(visible, worlds)


def test_source_hash_missing_candidate_and_zero_cost(results):
    corrupted = deepcopy(results['path_reversal']); corrupted['visible_sha256'] = '0'*64
    with pytest.raises(ValueError, match='hash'): e.evaluate_case(SPECS[2], corrupted)
    corrupted = deepcopy(results['path_reversal']); corrupted['candidates'].pop()
    with pytest.raises(ValueError, match='Missing'): e.evaluate_case(SPECS[2], corrupted)
    visible = results['path_reversal']['visible']
    ref = e.reference_worlds(SPECS[2], visible)[0]['reference']
    noop = e.realized_batch(visible, ref, [])
    assert noop['cost'] == 0 and F(noop['value']) == 0
    with pytest.raises(ValueError, match='budget'):
        e.realized_batch(visible, ref, visible['edges'][:2])


def test_zero_probability_condition_remains_undefined():
    spec = {**SPECS[1], 'error_probabilities': ['0','1/2','0']}
    decision = c.audit_initial_decision(c.visible_case(spec))
    out = e.evaluate_case(spec, decision)
    zero = [r for r in out['actions'] if F(r['exact_all_negative']) == 0]
    assert zero and all(r['conditional_same_sum'] is None and r['conditional_only'] is None for r in zero)
    assert all(F(r['expected_value']) == 0 for r in zero)
