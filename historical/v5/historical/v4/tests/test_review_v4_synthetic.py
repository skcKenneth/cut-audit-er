"""Bounded constructed fixtures only; never execute the formal 90-slot study."""
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path

import networkx as nx
import pytest

from cut_audit_er.audit import run_audit
from cut_audit_er.telemetry import AuditJournal
from scripts.review_v4 import synthetic as s


@pytest.mark.parametrize('k', (1, 2, 3))
@pytest.mark.parametrize('profile', s.PROFILES)
def test_visible_recipe_and_paired_answer_identity(k, profile):
    visible = s.visible_recipe(k, profile)
    graph, scores = s.load_visible(visible)
    assert len(graph) == 9 and graph.number_of_edges() == 9 + 2 * k <= 15
    assert list(graph) == sorted(graph)
    assert list(graph.edges) == sorted(graph.edges)
    assert not any(graph.nodes[node] for node in graph)
    assert all(set(data) == {'p'} for _, _, data in graph.edges(data=True))
    assert visible['contains_gold'] is False and scores.calls == 0
    zero, positive = s.reference_recipe('H0'), s.reference_recipe('H9')
    assert s.answer_table(graph, zero) == s.answer_table(graph, positive)
    assert sum(not answer for _, _, answer in s.answer_table(graph, zero)) == 2 * k
    assert s.pair_metrics(graph, zero) == {'fp': 27, 'fn': 0, 'loss': 27}
    assert s.pair_metrics(graph, positive) == {'fp': 18, 'fn': 0, 'loss': 18}
    retained = graph.copy()
    retained.remove_edges_from((u, v) for u, v, answer in s.answer_table(graph, zero) if not answer)
    assert s.pair_metrics(retained, zero)['fn'] == 0
    assert s.pair_metrics(retained, positive)['fn'] == 9
    assert s.visible_recipe(k, profile) == visible


@pytest.mark.parametrize('reference', s.REFERENCES)
@pytest.mark.parametrize('k', (1, 2, 3))
def test_three_independent_bound_descriptions_agree(k, reference):
    report = s.bound_evidence(k, reference)
    curve = report['diagnostic']['curve']
    assert len(curve) == 7
    values = [row['exact_loss'] for row in curve]
    assert values == sorted(values, reverse=True)
    assert values == [s.analytic_loss(k, reference, b) for b in range(7)]
    assert report['diagnostic']['components'][0]['enumerated_subsets'] == 2 ** (2 * k)


def test_independent_pair_metric_and_bound_include_cross_component_true_pairs():
    graph = nx.Graph([('a1', 'b')])
    graph.add_node('a2')
    truth = {'a1': 'a', 'a2': 'a', 'b': 'b'}
    assert s.pair_metrics(graph, truth) == {'fp': 1, 'fn': 1, 'loss': 2}
    assert s.independent_bound(graph, truth, 0)['loss'] == 2
    assert s.independent_bound(graph, truth, 1) == {
        'fp': 0, 'fn': 1, 'loss': 1, 'spent': 1, 'removed_edges': [['a1', 'b']]}


def test_headroom_is_not_multiedge_opportunity_or_positive_immediate_gain():
    one, _ = s.load_visible(s.visible_recipe(1, 'ranked'))
    two, _ = s.load_visible(s.visible_recipe(2, 'ranked'))
    h9_single = s.opportunities(one, s.reference_recipe('H9'), set(), 4)
    h0_multi = s.opportunities(two, s.reference_recipe('H0'), set(), 4)
    h9_multi = s.opportunities(two, s.reference_recipe('H9'), set(), 4)
    assert len(h9_single) == 2 and all(r['depth'] == 1 and r['loss_gain'] == 0 for r in h9_single)
    assert len(h0_multi) == 2 and all(r['depth'] == 2 and r['loss_gain'] == 18 for r in h0_multi)
    assert len(h9_multi) == 2 and all(r['depth'] == 2 and r['loss_gain'] == 0 for r in h9_multi)
    assert s.opportunities(two, s.reference_recipe('H0'), set(), 1) == []
    removed = [tuple(e) for e in h9_multi[0]['edges']]
    two.remove_edges_from(removed)
    later = s.opportunities(two, s.reference_recipe('H9'), set(removed), 2)
    assert len(later) == 1 and later[0]['loss_gain'] == 9


def test_exact_paid_grid_not_independent_reference_replications():
    grid = s.slots()
    assert len(grid) == len({r['id'] for r in grid}) == 90
    assert sum(r['budget'] for r in grid) == 288
    assert [(r['budget'], r['k'], r['score_profile'], r['method']) for r in grid] == [
        (budget, k, profile, method) for budget in (1, 2, 3, 4, 6)
        for k in (1, 2, 3) for profile in ('uniform', 'ranked') for method in s.METHODS]
    assert s.validate_config(s.read(s.ROOT / s.CONFIG)) == s.expected_config()


@pytest.mark.parametrize('key,value', [('worker_seconds', 31), ('outer_seconds', 901),
    ('budgets', [1, 2, 3, 6]), ('formal_test_access', True), ('candidate_cap', 65),
    ('max_plan_depth', 5), ('seed', 8), ('lambda', 2), ('noise', .05),
    ('source_downloads', 1), ('new_fits', 1), ('acquisition_runs', 180),
    ('output', 'outputs/other'), ('cpu_threads', 2), ('worker_seconds', 30.),
    ('budgets', [True, 2, 3, 4, 6])])
def test_changed_protocol_setting_is_rejected(key, value):
    config = s.expected_config()
    config[key] = value
    with pytest.raises(ValueError, match='Prespecified'):
        s.validate_config(config)


@pytest.mark.parametrize('method', s.METHODS)
def test_complete_replay_gold_isolation_cost_and_cold_cache(method, monkeypatch):
    visible = s.visible_recipe(2, 'ranked')
    graph, scores = s.load_visible(visible)
    first = run_audit(graph, scores, s.reference_recipe('H0'), method, 4, match_threshold=.6)
    other_gold = run_audit(graph, scores, s.reference_recipe('H9'), method, 4, match_threshold=.6)
    assert s.semantic(first['decisions']) == s.semantic(other_gold['decisions'])
    assert first['score_accesses'] == other_gold['score_accesses']
    assert first['stop_reason'] == other_gold['stop_reason']
    def prohibit(*args, **kwargs):
        pytest.fail('Offline replay must never make a new oracle query')
    monkeypatch.setattr('cut_audit_er.oracle.BudgetedOracle.query', prohibit)
    replay = s.replay_run(visible, first)
    assert replay['new_oracle_answers'] == 0
    assert replay['acquisition_paid_answers'] == 4
    assert len(replay['events']) == 4 and len(replay['states']) == 5
    assert replay['logical_score_accesses'] == first['score_accesses']
    assert first['initial']['fp'] != other_gold['initial']['fp']
    assert s.semantic(s.replay_run(visible, first)) == s.semantic(replay)
    for reference in s.REFERENCES:
        states = [row['references'][reference] for row in replay['states']]
        fp_removed = sum(a['fp'] - b['fp'] for a, b in zip(states, states[1:]))
        fn_added = sum(b['fn'] - a['fn'] for a, b in zip(states, states[1:]))
        assert states[0]['loss'] - states[-1]['loss'] == fp_removed - fn_added
    assert scores.calls == 0 and graph.number_of_edges() == 13


def test_post_cap_singleton_filter_retains_common_generation_order():
    graph, scores = s.load_visible(s.visible_recipe(2, 'ranked'))
    raw = s.candidate_trace(graph, scores, set(), 4, s.METHODS[1], {})
    single = s.candidate_trace(graph, scores, set(), 4, s.METHODS[2], {})
    for key in ('generated_lexicographic', 'prerank_order', 'capped_order', 'validated_order'):
        assert raw[key] == single[key]
    assert single['scored_order'] == [p for p in raw['validated_order'] if len(p) == 1]
    assert raw['depth_cap'] == single['depth_cap'] == 4
    assert any(len(p) == 2 for p in raw['scored_order'])
    assert single['scored_order'] == []
    assert len(raw['capped_order']) <= 64


def test_paid_positive_non_split_negative_and_fixed_batch_commitment():
    visible = s.visible_recipe(2, 'ranked')
    graph, scores = s.load_visible(visible)
    negative = run_audit(graph, scores, s.reference_recipe('H0'), s.METHODS[1], 2, match_threshold=.6)
    replay = s.replay_run(visible, negative)
    assert [r['category'] for r in replay['events']] == ['negative_no_split', 'negative_split']
    # Software-only alternative oracle checks the existing fixed-batch contract.
    positive = run_audit(graph, scores, {n: 'one' for n in graph}, s.METHODS[1], 2, match_threshold=.6)
    assert positive['spent'] == 2
    assert all(d['observed_match'] and d['batch'] == 1 for d in positive['decisions'])
    assert positive['initial'] == {**positive['final'], 'spent': 0}
    assert positive['trace'][1]['n_edges'] == positive['trace'][2]['n_edges']


def test_positive_paid_event_after_all_wrong_edges_and_empty_opportunities():
    visible = s.visible_recipe(1, 'uniform')
    graph, scores = s.load_visible(visible)
    run = run_audit(graph, scores, s.reference_recipe('H0'), s.METHODS[0], 3, match_threshold=.6)
    replay = s.replay_run(visible, run)
    assert [row['category'] for row in replay['events']] == ['negative_split', 'negative_split', 'positive']
    assert replay['states'][-1]['partition'] == replay['states'][-2]['partition']
    assert replay['batches'][-1]['offline_opportunities'] == {'H0': [], 'H9': []}
    assert len(replay['events']) == 3 and replay['acquisition_paid_answers'] == 3


@pytest.mark.parametrize('corruption', ('answer', 'pair', 'spent', 'batch', 'score_accesses', 'stop_reason'))
def test_replay_rejects_corrupt_stored_receipts(corruption):
    visible = s.visible_recipe(2, 'ranked')
    graph, scores = s.load_visible(visible)
    run = run_audit(graph, scores, s.reference_recipe('H0'), s.METHODS[1], 2, match_threshold=.6)
    if corruption == 'answer': run['decisions'][0]['observed_match'] = True
    elif corruption == 'pair': run['decisions'][0]['pair'] = ['r0', 'r8']
    elif corruption == 'spent': run['decisions'][0]['spent'] = 2
    elif corruption == 'batch': run['decisions'][0]['batch'] = 3
    elif corruption == 'score_accesses': run['score_accesses'] += 1
    else: run['stop_reason'] = 'invented'
    with pytest.raises(ValueError):
        s.replay_run(visible, run)


@pytest.mark.parametrize('name', ('../escape', '/absolute', 'C:/escape', 'a\\b', 'a/./b', 'a//b'))
def test_frozen_paths_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError, match='Unsafe'):
        s.contained(tmp_path, name)


def test_source_hash_wrong_or_missing_rejected(tmp_path):
    path = tmp_path / 'source.py'
    path.write_text('one', encoding='utf-8')
    pins = {'source.py': s.digest(path)}
    s.check_hashes(tmp_path, pins)
    path.write_text('two', encoding='utf-8')
    with pytest.raises(ValueError, match='Source hash mismatch'):
        s.check_hashes(tmp_path, pins)
    with pytest.raises(ValueError, match='Source hash mismatch'):
        s.check_hashes(tmp_path, {'absent.py': '0' * 64})
    with pytest.raises(ValueError, match='Empty'):
        s.check_hashes(tmp_path, {})


def frozen_fixture(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    s.write(config, s.expected_config())
    source = tmp_path / 'fixture_source.py'
    source.write_text('immutable fixture', encoding='utf-8')
    monkeypatch.setattr(s, 'source_names', lambda root: {'fixture_source.py'})
    validation = tmp_path / 'validation.json'
    s.write(validation, {'exit_code': 0, 'timed_out': False, 'cpu_threads': 1,
                         'python_hash_seed': '0', 'output_sha256': {}})
    frozen = tmp_path / 'freeze.json'
    snapshot = tmp_path / 'snapshot'
    s.create_freeze(tmp_path, config, frozen, snapshot, validation)
    for key, value in s.ENV.items():
        monkeypatch.setenv(key, value)
    return config, frozen, snapshot, tmp_path / s.SESSION / 'study'


def test_freeze_and_runner_reject_modified_sources_before_launch(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    (tmp_path / 'fixture_source.py').write_text('changed', encoding='utf-8')
    monkeypatch.setattr(s, 'bounded_audit', lambda *a, **kw: pytest.fail('must not launch'))
    with pytest.raises(ValueError, match='Source hash mismatch'):
        s.run_study(tmp_path, config, frozen, out)
    assert not out.exists()


def test_mock_missing_slots_once_only_and_180_missing_evaluations(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    calls = []
    def worker(arguments, seconds, journal, identity):
        calls.append((identity['run_id'], seconds))
        return {'status': 'timeout', 'error': 'MOCK finite timeout', 'worker_wall_seconds': .001,
                'cleanup_worker_still_alive': False}
    monkeypatch.setattr(s, 'bounded_audit', worker)
    suite = s.run_study(tmp_path, config, frozen, out)
    assert [row[0] for row in calls] == [row['id'] for row in s.slots()]
    assert all(0 < seconds <= 30 for _, seconds in calls)
    assert suite['status'] == 'completed_with_missing'
    with pytest.raises(FileExistsError, match='Preserve consumed'):
        s.run_study(tmp_path, config, frozen, out)
    analysis = tmp_path / 'analysis'
    report = s.analyze(out, analysis)
    assert report['completed_acquisitions'] == report['offline_reference_evaluations'] == 0
    assert report['table_rows']['endpoints'] == 180 and report['table_rows']['missing'] == 90
    assert report['completed_run_paid_answers'] == 0
    assert report['physical_paid_answers'] is None
    assert (report['total_paid_lower_bound'], report['total_paid_upper_bound']) == (0, 288)
    assert s.check_analysis(out, analysis)['status'] == 'passed'


def test_mock_one_completed_slot_exports_full_replay_and_hashes(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    count = 0
    def worker(arguments, seconds, journal, identity):
        nonlocal count
        count += 1
        if count > 1:
            return {'status': 'timeout', 'error': 'MOCK missing', 'worker_wall_seconds': 0.,
                    'cleanup_worker_still_alive': False}
        with AuditJournal(journal, identity) as writer:
            run = run_audit(**arguments, checkpoint_callback=writer)
        return {'status': 'completed', 'run': run, 'worker_wall_seconds': .1,
                'worker_timing': {key: .01 for key in ('process_start_seconds', 'result_wait_seconds',
                                 'payload_receive_seconds', 'cleanup_seconds')},
                'cleanup_worker_still_alive': False}
    monkeypatch.setattr(s, 'bounded_audit', worker)
    s.run_study(tmp_path, config, frozen, out)
    report = s.analyze(out, tmp_path / 'analysis')
    assert report['completed_acquisitions'] == 1 and report['offline_reference_evaluations'] == 2
    assert report['completed_run_paid_answers'] == 1
    assert report['physical_paid_answers'] is None
    assert report['total_paid_lower_bound'] == 1 and report['total_paid_upper_bound'] == 288
    assert s.check_analysis(out, tmp_path / 'analysis')['status'] == 'passed'
    path = tmp_path / 'analysis' / 'endpoints.csv'
    path.write_text(path.read_text(encoding='utf-8') + 'corrupt\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Source hash mismatch'):
        s.check_analysis(out, tmp_path / 'analysis')


def test_csv_edit_with_updated_hash_is_still_rejected(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(s, 'bounded_audit', lambda *a, **kw: {
        'status': 'timeout', 'error': 'MOCK missing', 'worker_wall_seconds': 0.,
        'cleanup_worker_still_alive': False})
    s.run_study(tmp_path, config, frozen, out)
    destination = tmp_path / 'analysis'
    s.analyze(out, destination)
    target = destination / 'endpoints.csv'
    target.write_text(target.read_text(encoding='utf-8').replace(',27,0,', ',28,0,', 1), encoding='utf-8', newline='')
    manifest = s.read(destination / 'manifest.json')
    manifest['files_sha256']['endpoints.csv'] = s.digest(target)
    s.write(destination / 'manifest.json', manifest, checkpoint=True)
    with pytest.raises(ValueError, match='CSV projection differs'):
        s.check_analysis(out, destination)


def test_suite_deadline_preserves_every_unstarted_slot(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    times = iter([0., 0.])
    monkeypatch.setattr(s.time, 'perf_counter', lambda: next(times, 901.))
    monkeypatch.setattr(s, 'bounded_audit', lambda *a, **kw: pytest.fail('suite already expired'))
    suite = s.run_study(tmp_path, config, frozen, out)
    assert suite['status'] == 'completed_with_missing'
    assert len(suite['runs']) == 90
    assert all(r['status'] == 'not_started' and r['reason'] == 'suite_limit_before_launch' for r in suite['runs'])


def test_unstopped_worker_aborts_next_launch_and_keeps_failure(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    called = []
    def failed(*args, **kwargs):
        called.append(1)
        return {'status': 'cleanup_failed', 'error': 'MOCK worker alive',
                'worker_wall_seconds': 0., 'cleanup_worker_still_alive': True}
    monkeypatch.setattr(s, 'bounded_audit', failed)
    with pytest.raises(ValueError, match='Worker remains alive'):
        s.run_study(tmp_path, config, frozen, out)
    suite = s.read(out / 'suite.json')
    assert called == [1] and suite['status'] == 'failed'
    assert suite['runs'][0]['status'] == 'cleanup_failed'
    assert all(r['status'] == 'not_started' and r['reason'] == 'suite_aborted_before_complete_result'
               for r in suite['runs'][1:])


def test_environment_and_snapshot_hash_fail_before_acquisition(tmp_path, monkeypatch):
    config, frozen, snapshot, out = frozen_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv('OMP_NUM_THREADS', '2')
    monkeypatch.setattr(s, 'bounded_audit', lambda *a, **kw: pytest.fail('invalid freeze/environment'))
    with pytest.raises(ValueError, match='Pin CPU'):
        s.run_study(tmp_path, config, frozen, out)
    monkeypatch.setenv('OMP_NUM_THREADS', '1')
    (snapshot / 'inputs/k1_uniform.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Source hash mismatch'):
        s.run_study(tmp_path, config, frozen, out)
    assert not out.exists()


def test_gold_is_absent_from_visible_function_signature():
    import inspect
    assert list(inspect.signature(s.visible_recipe).parameters) == ['k', 'profile']
    assert 'truth' not in inspect.signature(s.candidate_trace).parameters
    assert 'reference' not in inspect.signature(s.candidate_trace).parameters
