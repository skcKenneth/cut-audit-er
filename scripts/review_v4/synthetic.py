"""Frozen 90-run synthetic mechanism study and separate paired-gold diagnosis.

The acquisition engine is unchanged. Analyze/check buy no answers: all gold
quantities stay in offline reconstruction, never in a selector's arguments.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from itertools import combinations, groupby
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import time

import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from cut_audit_er.bounded_planner import build_plan_pool, completion_score
from cut_audit_er.natural import bounded_audit
from cut_audit_er.policies import select_action
from cut_audit_er.scores import PairScores
from cut_audit_er.telemetry import recover_journal
from scripts.conference_improvement.finite_budget import diagnose_graph

SESSION = 'outputs/session_20260927_v4/synthetic'
PROTOCOL = 'research/review_v4/SYNTHETIC_PROTOCOL.md'
CONFIG = 'configs/review_v4_synthetic.json'
METHODS = ('edge_betweenness', 'cut_plan_fixed', 'cut_plan_fixed_singleton')
BUDGETS = (1, 2, 3, 4, 6)
PROFILES = ('uniform', 'ranked')
REFERENCES = ('H0', 'H9')
ENV = {'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1',
       'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def blob(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def value_hash(value):
    return hashlib.sha256(blob(value)).hexdigest()


def contained(root, name):
    root = Path(root).resolve()
    pure = PurePosixPath(name)
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name
            and not pure.is_absolute() and str(pure) == name
            and all(p not in ('.', '..') for p in pure.parts), 'Unsafe relative path')
    path = root / name
    require(not any(p.is_symlink() for p in (path, *path.parents) if p != root.parent),
            'Symlink is not a frozen input')
    require(path.resolve().is_relative_to(root), 'Path outside workspace')
    return path


def write(path, value, *, checkpoint=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint:
        temporary = path.with_suffix(path.suffix + '.tmp')
        with temporary.open('xb') as handle:
            handle.write(blob(value))
        temporary.replace(path)
    else:
        with path.open('xb') as handle:
            handle.write(blob(value))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_hashes(root, pins):
    require(isinstance(pins, dict) and pins, 'Empty source hash mapping')
    for name, expected in pins.items():
        path = contained(root, name)
        require(path.is_file() and digest(path) == expected, 'Source hash mismatch: ' + name)


def expected_config():
    return {'schema': 'cut-audit-review-v4-synthetic-config-v1',
            'phase': 'constructed_synthetic_mechanism', 'boundary_widths': [1, 2, 3],
            'score_profiles': list(PROFILES), 'references': list(REFERENCES),
            'methods': list(METHODS), 'budgets': list(BUDGETS), 'worker_seconds': 30,
            'outer_seconds': 900, 'seed': 7, 'noise': 0, 'lambda': 1,
            'max_plan_depth': 4, 'candidate_cap': 64, 'cpu_threads': 1,
            'python_hash_seed': '0', 'formal_test_access': False, 'new_fits': 0,
            'source_downloads': 0, 'acquisition_runs': 90,
            'offline_reference_evaluations': 180, 'maximum_paid_answers': 288,
            'protocol': PROTOCOL, 'output': SESSION + '/study'}


def validate_config(cfg):
    expected = expected_config()
    require(set(cfg) == set(expected), 'Prespecified configuration keys differ')
    for key, value in expected.items():
        require(type(cfg[key]) is type(value) and cfg[key] == value,
                'Prespecified setting differs: ' + key)
    require(blob(cfg) == blob(expected), 'Prespecified nested value types differ')
    return cfg


def slots():
    return [{'id': f'k{k}_{profile}_{method}_B{budget}', 'k': k,
             'score_profile': profile, 'method': method, 'budget': budget,
             'status': 'not_started'}
            for budget in BUDGETS for k in (1, 2, 3)
            for profile in PROFILES for method in METHODS]


def visible_recipe(k, profile):
    """Only declared observable construction arguments; no reference/gold input."""
    require(type(k) is int and k in (1, 2, 3) and profile in PROFILES,
            'Unknown fixed visible construction')
    nodes = [f'r{i}' for i in range(9)]
    edges = set()
    matrix = np.full((9, 9), .10)
    np.fill_diagonal(matrix, 1.)
    for offset in (0, 3, 6):
        for i, j in combinations(range(offset, offset + 3), 2):
            edges.add((nodes[i], nodes[j]))
            matrix[i, j] = matrix[j, i] = .95
    for i in range(k):
        score = .70 if profile == 'uniform' else (.80, .70, .60)[i]
        for offset in (0, 3):
            u, v = i + offset, i + offset + 3
            edges.add((nodes[u], nodes[v]))
            matrix[u, v] = matrix[v, u] = score
    return {'schema': 'cut-audit-synthetic-visible-v1', 'k': k,
            'score_profile': profile, 'nodes': nodes,
            'edges': [list(e) for e in sorted(edges)], 'scores': matrix.tolist(),
            'contains_gold': False}


def reference_recipe(reference):
    require(reference in REFERENCES, 'Unknown fixed reference')
    return {f'r{i}': ('A' if reference == 'H9' and i >= 6 else 'ABC'[i // 3])
            for i in range(9)}


def load_visible(value):
    require(value == visible_recipe(value['k'], value['score_profile']),
            'Frozen visible construction differs')
    scores = PairScores(tuple(value['nodes']), value['scores'])
    graph = nx.Graph()
    graph.add_nodes_from(value['nodes'])
    for u, v in value['edges']:
        graph.add_edge(u, v, p=float(scores.matrix[scores.index[u], scores.index[v]]))
    return graph, scores


def answer_table(graph, truth):
    require(set(graph) == set(truth), 'Reference membership differs')
    return [(u, v, truth[u] == truth[v]) for u, v in sorted(tuple(sorted(e)) for e in graph.edges)]


def source_names(root):
    names = {p.relative_to(root).as_posix() for p in (root / 'src/cut_audit_er').glob('*.py')}
    return names | {'scripts/review_v4/synthetic.py', 'tests/test_review_v4_synthetic.py',
                    'scripts/conference_improvement/finite_budget.py',
                    'scripts/structural_study/assets.py', 'scripts/run_logged.py', CONFIG, PROTOCOL}


def create_freeze(root, config, output, snapshot, validation):
    root = Path(root).resolve()
    config, output, snapshot, validation = [Path(p).resolve() for p in (config, output, snapshot, validation)]
    require(all(p.is_relative_to(root) for p in (config, output, snapshot, validation)),
            'Freeze path outside workspace')
    if output.exists() or snapshot.exists():
        raise FileExistsError('Preserve existing freeze and snapshot')
    validate_config(read(config))
    receipt = read(validation)
    require(receipt.get('exit_code') == 0 and receipt.get('timed_out') is False,
            'Successful bounded validation command receipt required')
    require(receipt.get('cpu_threads') == 1 and receipt.get('python_hash_seed') == '0',
            'Validation did not pin CPU/hash environment')
    names = source_names(root) | {config.relative_to(root).as_posix(), validation.relative_to(root).as_posix()}
    for name, expected in receipt.get('output_sha256', {}).items():
        path = contained(validation.parent, name)
        require(digest(path) == expected, 'Validation output hash mismatch')
        names.add(path.relative_to(root).as_posix())
    hashes = {name: digest(contained(root, name)) for name in sorted(names)}
    snapshot.mkdir(parents=True)
    for name in sorted(source_names(root) | {config.relative_to(root).as_posix()}):
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
        require(digest(target) == hashes[name], 'Snapshot copy mismatch')
    inputs = {}
    for k in (1, 2, 3):
        for profile in PROFILES:
            name = f'inputs/k{k}_{profile}.json'
            value = visible_recipe(k, profile)
            graph, _ = load_visible(value)
            require(answer_table(graph, reference_recipe('H0')) == answer_table(graph, reference_recipe('H9')),
                    'Paired references disagree on eligible query answers')
            write(snapshot / name, value)
            inputs[name] = digest(snapshot / name)
    for reference in REFERENCES:
        name = f'offline_references/{reference}.json'
        write(snapshot / name, {'reference': reference, 'truth': reference_recipe(reference),
                                'scope': 'Offline reference; never a selector argument'})
        inputs[name] = digest(snapshot / name)
    frozen = {'schema': 'cut-audit-review-v4-synthetic-freeze-v1',
              'created_utc': datetime.now(timezone.utc).isoformat(),
              'formal_test_access': False, 'human_approval_claimed': False,
              'before_formal_synthetic_outcomes': True,
              'config_path': config.relative_to(root).as_posix(),
              'source_snapshot': snapshot.relative_to(root).as_posix(),
              'files_sha256': hashes, 'snapshot_inputs_sha256': inputs,
              'validation': validation.relative_to(root).as_posix(), 'planned_slots': slots()}
    write(output, frozen)
    return frozen


def validate_freeze(root, config, frozen):
    require(frozen.get('schema') == 'cut-audit-review-v4-synthetic-freeze-v1'
            and frozen.get('planned_slots') == slots()
            and frozen.get('config_path') == Path(config).resolve().relative_to(root).as_posix(),
            'Synthetic freeze identity differs')
    check_hashes(root, frozen['files_sha256'])
    require(source_names(root) <= frozen['files_sha256'].keys(), 'Freeze omits execution source')
    snapshot = contained(root, frozen['source_snapshot'])
    check_hashes(snapshot, {name: frozen['files_sha256'][name] for name in source_names(root)})
    check_hashes(snapshot, frozen['snapshot_inputs_sha256'])
    return snapshot


def run_study(root, config, freeze_path, out):
    root = Path(root).resolve()
    config, freeze_path, out = [Path(p).resolve() for p in (config, freeze_path, out)]
    require(all(p.is_relative_to(root) for p in (config, freeze_path, out)), 'Execution path outside workspace')
    cfg = validate_config(read(config))
    require(out == root / cfg['output'], 'Use the one prespecified destination')
    frozen = read(freeze_path)
    snapshot = validate_freeze(root, config, frozen)
    require(all(os.environ.get(k) == v for k, v in ENV.items()), 'Pin CPU and hash environment before startup')
    consumed = root / SESSION / 'execution_consumed.json'
    if out.exists() or consumed.exists():
        raise FileExistsError('Preserve consumed study; formal reruns are prohibited')
    write(consumed, {'freeze_sha256': digest(freeze_path), 'planned_acquisitions': 90,
                     'started_utc': datetime.now(timezone.utc).isoformat(), 'retries_allowed': False})
    out.mkdir(parents=True)
    shutil.copyfile(freeze_path, out / 'freeze.json')
    shutil.copyfile(config, out / 'config.json')
    for name in frozen['snapshot_inputs_sha256']:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot / name, target)
    assets = {(k, profile): load_visible(read(out / f'inputs/k{k}_{profile}.json'))
              for k in (1, 2, 3) for profile in PROFILES}
    suite = {'schema': 'cut-audit-review-v4-synthetic-suite-v1', 'status': 'running',
             'runs': slots(), 'freeze_sha256': digest(freeze_path), 'config_sha256': digest(config),
             'formal_test_access': False, 'data_kind': 'constructed_synthetic',
             'planned_acquisitions': 90, 'planned_offline_evaluations': 180,
             'maximum_paid_answers': 288, 'worker_seconds': 30, 'outer_seconds': 900,
             'new_fits': 0, 'source_downloads': 0,
             'environment': {'python': platform.python_version(), **ENV},
             'counting_scope': 'One physical acquisition, two dependent offline gold evaluations',
             'timing_scope': 'Fixed-order descriptive costs; suite deadline checked between workers'}
    started = time.perf_counter()
    def checkpoint():
        suite['acquisition_elapsed_seconds'] = time.perf_counter() - started
        write(out / 'suite.json', suite, checkpoint=True)
    checkpoint()
    try:
        for slot in suite['runs']:
            remaining = cfg['outer_seconds'] - (time.perf_counter() - started)
            if remaining <= 0:
                slot.update(reason='suite_limit_before_launch')
                checkpoint()
                continue
            validate_freeze(root, config, frozen)
            graph, scores = assets[slot['k'], slot['score_profile']]
            identity = {'run_id': slot['id'], 'method': slot['method'],
                        'requested_budget': slot['budget'], 'k': slot['k'],
                        'score_profile': slot['score_profile'], 'data_kind': 'constructed_synthetic',
                        'visible_sha256': digest(out / f"inputs/k{slot['k']}_{slot['score_profile']}.json"),
                        'freeze_sha256': digest(freeze_path)}
            slot['status'] = 'running'
            checkpoint()
            journal = out / 'journals' / (slot['id'] + '.jsonl')
            result = bounded_audit(dict(g=graph, scores=scores, truth=reference_recipe('H0'),
                                   method=slot['method'], budget=slot['budget'], seed=7, noise=0.,
                                   fn_weight=1., max_width=2, shortlist=24, match_threshold=.6),
                                   min(30, remaining), journal, identity)
            result['identity'] = identity
            target = out / 'runs' / (slot['id'] + '.json')
            write(target, result)
            slot.update(status=result['status'], path=target.relative_to(out).as_posix(),
                        sha256=digest(target), journal=journal.relative_to(out).as_posix(),
                        journal_sha256=digest(journal) if journal.exists() else None,
                        worker_wall_seconds=result['worker_wall_seconds'])
            if result['status'] != 'completed':
                slot['reason'] = result.get('error', result['status'])
            checkpoint()
            validate_freeze(root, config, frozen)
            require(not result.get('cleanup_worker_still_alive'), 'Worker remains alive; stop all further acquisition')
        suite['status'] = 'completed' if all(s['status'] == 'completed' for s in suite['runs']) else 'completed_with_missing'
        checkpoint()
    except BaseException as exc:
        for slot in suite['runs']:
            if slot['status'] in ('not_started', 'running'):
                slot.update(reason='suite_aborted_before_complete_result')
        suite.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        checkpoint()
        raise
    return suite


def partition(graph):
    return sorted(sorted(group) for group in nx.connected_components(graph))


def pair_metrics(graph, truth):
    """Independent direct-pair count; includes true pairs across components."""
    require(set(graph) == set(truth), 'Reference membership differs')
    group = {n: i for i, nodes in enumerate(partition(graph)) for n in nodes}
    fp = fn = 0
    for u, v in combinations(sorted(graph), 2):
        connected, match = group[u] == group[v], truth[u] == truth[v]
        fp += int(connected and not match)
        fn += int(match and not connected)
    return {'fp': fp, 'fn': fn, 'loss': fp + fn}


def analytic_loss(k, reference, budget):
    if reference == 'H0':
        return 27 if budget < k else 9 if budget < 2 * k else 0
    require(reference == 'H9', 'Unknown fixed reference')
    return 18 if budget < 2 * k else 9


def independent_bound(graph, truth, budget):
    negative = sorted(tuple(sorted(e)) for e in graph.edges if truth[e[0]] != truth[e[1]])
    require(len(graph) <= 16 and graph.number_of_edges() <= 16, 'Independent bound cap exceeded')
    candidates = []
    for size in range(min(budget, len(negative)) + 1):
        for removed in combinations(negative, size):
            after = graph.copy()
            after.remove_edges_from(removed)
            metrics = pair_metrics(after, truth)
            candidates.append((metrics['loss'], size, removed, metrics))
    best = min(candidates, key=lambda row: row[:3])
    return {**best[3], 'spent': best[1], 'removed_edges': [list(e) for e in best[2]]}


def bound_evidence(k, reference):
    graph, _ = load_visible(visible_recipe(k, 'uniform'))
    truth = reference_recipe(reference)
    report = diagnose_graph(graph, truth, max_budget=6)
    for row in report['curve']:
        brute = independent_bound(graph, truth, row['budget'])
        witness = report['witnesses'][row['exact_witness_id']]
        require(row['status'] == 'exact' and row['exact_loss'] == brute['loss']
                == analytic_loss(k, reference, row['budget'])
                and row['exact_fp'] == brute['fp'] and row['exact_fn'] == brute['fn']
                and witness['removed_edges'] == [tuple(e) for e in brute['removed_edges']],
                'Independent/analytic bound or deletion witness differs')
    return {'k': k, 'reference': reference, 'independent_check': 'passed',
            'analytic_check': 'passed', 'diagnostic': report}


def opportunities(graph, truth, verified, remaining):
    """Exhaustive all-negative bonds, separate from any generated candidate pool."""
    initial = pair_metrics(graph, truth)
    result = []
    for component in sorted(tuple(sorted(c)) for c in nx.connected_components(graph)):
        local = graph.subgraph(component).copy()
        negative = sorted(tuple(sorted(e)) for e in local.edges
                          if truth[e[0]] != truth[e[1]] and tuple(sorted(e)) not in verified)
        for size in range(1, min(4, remaining, len(negative)) + 1):
            for deleted in combinations(negative, size):
                retained = local.copy()
                retained.remove_edges_from(deleted)
                parts = partition(retained)
                if len(parts) != 2:
                    continue
                side = set(parts[0])
                if any((u in side) == (v in side) for u, v in deleted):
                    continue
                after = graph.copy()
                after.remove_edges_from(deleted)
                metrics = pair_metrics(after, truth)
                result.append({'edges': [list(e) for e in deleted], 'depth': size,
                               'fp_removed': initial['fp'] - metrics['fp'],
                               'fn_added': metrics['fn'] - initial['fn'],
                               'loss_gain': initial['loss'] - metrics['loss']})
    return sorted(result, key=lambda r: (r['depth'], r['edges']))


def candidate_trace(graph, scores, verified, remaining, method, observations):
    """Visible-only diagnostic with fresh counters/cache; never alters selection."""
    reads = scores.copy()
    plans, partitions, probabilities, weighted, info = build_plan_pool(
        graph, reads, verified, remaining, diagnostic_raw=True)
    raw = [tuple(tuple(e) for e in plan) for plan in info['raw_plan_edges']]
    ranked = sorted(raw, key=lambda q: (-sum(weighted[e] for e in q) / len(q), len(q), q))
    scored = [] if method == METHODS[0] else [p for p in plans if method != METHODS[2] or len(p) == 1]
    utility = []
    for plan in scored:
        value, gain, success = completion_score(plan, partitions[plan], reads, probabilities, observations, 1.)
        utility.append({'edges': plan, 'proxy': value, 'utility': gain, 'success_product': success})
    utility.sort(key=lambda row: (-row['proxy'], len(row['edges']), row['edges']))
    eligible = sorted(tuple(sorted(e)) for e in graph.edges if tuple(sorted(e)) not in verified)
    bc = {tuple(sorted(e)): v for e, v in nx.edge_betweenness_centrality(graph).items()}
    bc_order = sorted(eligible, key=lambda e: (-bc[e] * (1 - probabilities[e]), e))
    return {'generated_lexicographic': sorted(raw), 'prerank_order': ranked,
            'capped_order': ranked[:64], 'validated_order': plans, 'scored_order': scored,
            'utility_rank_order': utility, 'bc_eligible_order': bc_order,
            'pool_scope': 'counterfactual_not_used_by_BC' if method == METHODS[0] else 'method_common_pool',
            'diagnostic_score_accesses': reads.calls, 'depth_cap': min(4, remaining)}


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items()
                if not k.endswith('_seconds') and k not in ('seconds', 'topology_cache')}
    if isinstance(value, (tuple, list)):
        return [semantic(v) for v in value]
    return value


def replay_run(visible, run):
    """Gold-independent selector replay followed by two offline evaluations."""
    graph, scores = load_visible(visible)
    method, budget = run['method'], run['requested_budget']
    require(method in METHODS and budget in BUDGETS and run.get('complete') is True,
            'Only completed prespecified acquisition results can be endpoints')
    truth = {reference: reference_recipe(reference) for reference in REFERENCES}
    require(answer_table(graph, truth['H0']) == answer_table(graph, truth['H9']), 'Paired answers differ')
    stored_answers = {(u, v): answer for u, v, answer in answer_table(graph, truth['H0'])}
    state, observed, batches, events, states = {}, {}, [], [], []
    reads = scores.copy()
    rng = np.random.default_rng(7)
    def capture(spent):
        parts = partition(graph)
        return {'spent': spent, 'edges': [list(e) for e in sorted(tuple(sorted(e)) for e in graph.edges)],
                'partition': parts, 'partition_sha256': value_hash(parts),
                'references': {ref: pair_metrics(graph, labels) for ref, labels in truth.items()}}
    states.append(capture(0))
    grouped = [(batch, list(group)) for batch, group in groupby(run['decisions'], key=lambda d: d['batch'])]
    for batch, group in grouped:
        require(batch == len(batches) + 1 and group, 'Paid batch gap')
        remaining = budget - len(observed)
        candidate = candidate_trace(graph, scores, set(observed), remaining, method, observed)
        action, info = select_action(graph, reads, set(observed), remaining, method, rng,
                                    1., 2, 24, .6, observed, 7, state)
        require(action is not None and tuple(tuple(d['pair']) for d in group) == action,
                'Stored complete batch differs from selector replay')
        require(semantic(info) == semantic(group[0]['selection_info']), 'Selector semantic metadata differs')
        opportunity = {ref: opportunities(graph, labels, set(observed), remaining)
                       for ref, labels in truth.items()}
        batches.append({'batch': batch, 'spent_before': len(observed), 'remaining': remaining,
                        'selected_action': action, 'selection_info': info, 'candidates': candidate,
                        'offline_opportunities': opportunity,
                        'logical_accesses_cumulative': reads.calls,
                        'new_oracle_answers': 0})
        for decision in group:
            edge = tuple(decision['pair'])
            answer = decision['observed_match']
            require(decision['spent'] == len(observed) + 1 and type(answer) is bool
                    and edge not in observed and graph.has_edge(*edge)
                    and edge in stored_answers and answer == stored_answers[edge],
                    'Invalid stored paid answer')
            before = states[-1]
            observed[edge] = answer
            if not answer:
                graph.remove_edge(*edge)
            after = capture(len(observed))
            category = ('positive' if answer else 'negative_split'
                        if len(after['partition']) > len(before['partition']) else 'negative_no_split')
            events.append({'spent': len(observed), 'batch': batch, 'u': edge[0], 'v': edge[1],
                           'answer': answer, 'category': category,
                           'partition_before_sha256': before['partition_sha256'],
                           'partition_after_sha256': after['partition_sha256']})
            states.append(after)
    stop = 'budget_exhausted'
    if len(observed) < budget:
        action, info = select_action(graph, reads, set(observed), budget - len(observed), method,
                                    rng, 1., 2, 24, .6, observed, 7, state)
        require(action is None, 'Replay would continue beyond archived completion')
        stop = info.get('reason', 'no_action')
    require(len(observed) == run['spent'] <= budget and reads.calls == run['score_accesses']
            and stop == run['stop_reason'], 'Replay cost or stop reason differs')
    require(len(run['trace']) == len(states), 'Archived trace length differs')
    for saved, replayed in zip(run['trace'], states):
        require(saved['spent'] == replayed['spent'] and
                all(saved[key] == replayed['references']['H0'][key] for key in ('fp', 'fn', 'loss')),
                'Acquisition metrics differ from independent replay')
    for ref in REFERENCES:
        final = states[-1]['references'][ref]
        require(final['loss'] >= analytic_loss(visible['k'], ref, budget), 'Endpoint below exact bound')
        require(states[0]['references'][ref]['fp'] - final['fp'] >= 0 and final['fn'] >= 0,
                'Invalid closure conservation')
    return {'schema': 'cut-audit-review-v4-synthetic-replay-v1', 'method': method,
            'requested_budget': budget, 'k': visible['k'], 'score_profile': visible['score_profile'],
            'new_oracle_answers': 0, 'acquisition_paid_answers': len(observed),
            'logical_score_accesses': reads.calls, 'stop_reason': stop,
            'batches': batches, 'events': events, 'states': states,
            'diagnostic_score_accesses': sum(b['candidates']['diagnostic_score_accesses'] for b in batches)}


def check_study(study):
    study = Path(study).resolve()
    suite = read(study / 'suite.json')
    require(suite.get('schema') == 'cut-audit-review-v4-synthetic-suite-v1', 'Wrong study schema')
    require(digest(study / 'freeze.json') == suite['freeze_sha256']
            and digest(study / 'config.json') == suite['config_sha256'], 'Study freeze/config hash mismatch')
    validate_config(read(study / 'config.json'))
    frozen = read(study / 'freeze.json')
    require(frozen.get('planned_slots') == slots(), 'Frozen acquisition inventory differs')
    check_hashes(study, frozen['snapshot_inputs_sha256'])
    require(len(suite['runs']) == 90, 'Acquisition inventory incomplete')
    for expected, actual in zip(slots(), suite['runs']):
        require(all(actual.get(k) == expected[k] for k in expected if k != 'status'), 'Acquisition order/identity differs')
        if 'path' in actual:
            path = contained(study, actual['path'])
            require(digest(path) == actual['sha256'], 'Acquisition result hash mismatch')
            result = read(path)
            require(result['status'] == actual['status'], 'Acquisition status differs')
            identity = result['identity']
            require(identity['run_id'] == actual['id'] and identity['method'] == actual['method']
                    and identity['requested_budget'] == actual['budget']
                    and identity['k'] == actual['k'] and identity['score_profile'] == actual['score_profile']
                    and identity['visible_sha256'] == digest(study / f"inputs/k{actual['k']}_{actual['score_profile']}.json")
                    and identity['freeze_sha256'] == suite['freeze_sha256'], 'Acquisition binding differs')
            if actual.get('journal_sha256') is not None:
                journal = contained(study, actual['journal'])
                require(digest(journal) == actual['journal_sha256'], 'Journal hash mismatch')
                recovered = recover_journal(journal, identity)
                if actual['status'] == 'completed':
                    require(recovered['decisions'] == result['run']['decisions']
                            and recovered['trace'] == result['run']['trace'], 'Journal/result contents differ')
            else:
                require(actual['status'] != 'completed', 'Completed result lacks journal')
        else:
            require(actual['status'] == 'not_started' and actual.get('reason'), 'Missing outcome without reason')
    return suite


def csv_write(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='raise')
        writer.writeheader()
        writer.writerows(rows)


def first_divergence(left, right):
    for index, pair in enumerate(zip(left, right), 1):
        if (pair[0]['u'], pair[0]['v'], pair[0]['answer']) != (pair[1]['u'], pair[1]['v'], pair[1]['answer']):
            return index
    return min(len(left), len(right)) + 1 if len(left) != len(right) else None


def analyze(study, out):
    study, out = Path(study).resolve(), Path(out).resolve()
    suite = check_study(study)
    if out.exists():
        raise FileExistsError('Preserve existing analysis; use a fresh directory')
    out.mkdir(parents=True)
    acquisitions, endpoints, events, states, batches, opps, bounds, missing = ([] for _ in range(8))
    replays = {}
    for k in (1, 2, 3):
        for ref in REFERENCES:
            bound = bound_evidence(k, ref)
            write(out / 'bounds' / f'k{k}_{ref}.json', bound)
            for row in bound['diagnostic']['curve']:
                bounds.append({'k': k, 'reference': ref, 'budget': row['budget'],
                               'exact_loss': row['exact_loss'], 'exact_fp': row['exact_fp'],
                               'exact_fn': row['exact_fn'], 'witness_spend': row['feasible_deleted_edges'],
                               'status': 'exact', 'independent_check': 'passed'})
    for slot in suite['runs']:
        common = {'run_id': slot['id'], 'k': slot['k'], 'score_profile': slot['score_profile'],
                  'method': slot['method'], 'budget': slot['budget']}
        acquisition = {**common, 'status': slot['status'], 'spent': None, 'selector_seconds': None,
                       'audit_seconds': None, 'worker_wall_seconds': slot.get('worker_wall_seconds'),
                       'logical_score_accesses': None, 'explicit_multi_batches': None,
                       'paid_lower_bound': 0, 'paid_upper_bound': slot['budget'], 'paid_exact': False,
                       'process_start_seconds': None, 'result_wait_seconds': None,
                       'payload_receive_seconds': None, 'cleanup_seconds': None}
        result = read(study / slot['path']) if 'path' in slot else None
        if result is not None:
            acquisition.update({key: result.get('worker_timing', {}).get(key) for key in
                                ('process_start_seconds', 'result_wait_seconds', 'payload_receive_seconds', 'cleanup_seconds')})
        if slot['status'] != 'completed':
            if slot['status'] == 'not_started':
                acquisition.update(paid_lower_bound=0, paid_upper_bound=0, paid_exact=True)
            elif result is not None:
                progress = result.get('checkpoint_telemetry', {})
                lower, upper = progress.get('paid_count_lower_bound'), progress.get('paid_count_upper_bound')
                if type(lower) is int and type(upper) is int:
                    require(0 <= lower <= upper <= slot['budget'], 'Invalid incomplete paid-cost bounds')
                    acquisition.update(paid_lower_bound=lower, paid_upper_bound=upper, paid_exact=lower == upper)
            missing.append({**common, 'status': slot['status'], 'reason': slot.get('reason', 'missing_result')})
            acquisitions.append(acquisition)
            for ref in REFERENCES:
                endpoints.append({**common, 'reference': ref, 'status': slot['status'], 'reused_acquisition': True,
                                  'fp': None, 'fn': None, 'loss': None, 'initial_fp': 27 if ref == 'H0' else 18,
                                  'initial_fn': 0, 'exact_bound': analytic_loss(slot['k'], ref, slot['budget']),
                                  'gap_to_bound': None})
            continue
        run = result['run']
        replayed = replay_run(read(study / f"inputs/k{slot['k']}_{slot['score_profile']}.json"), run)
        replayed.update(run_id=slot['id'], acquisition_sha256=slot['sha256'],
                        visible_sha256=result['identity']['visible_sha256'])
        replays[slot['id']] = replayed
        write(out / 'replays' / (slot['id'] + '.json'), replayed)
        acquisition.update(spent=run['spent'], selector_seconds=run['selection_seconds'],
                           audit_seconds=run['seconds'], logical_score_accesses=run['score_accesses'],
                           paid_lower_bound=run['spent'], paid_upper_bound=run['spent'], paid_exact=True,
                           explicit_multi_batches=sum(len(b['selected_action']) > 1 for b in replayed['batches']))
        acquisitions.append(acquisition)
        for event in replayed['events']:
            events.append({**common, **event})
        for ref in REFERENCES:
            initial = replayed['states'][0]['references'][ref]
            final = replayed['states'][-1]['references'][ref]
            bound = analytic_loss(slot['k'], ref, slot['budget'])
            endpoints.append({**common, 'reference': ref, 'status': 'completed', 'reused_acquisition': True,
                              **final, 'initial_fp': initial['fp'], 'initial_fn': initial['fn'],
                              'exact_bound': bound, 'gap_to_bound': final['loss'] - bound})
            for index, state in enumerate(replayed['states']):
                metric = state['references'][ref]
                before = replayed['states'][max(0, index - 1)]['references'][ref]
                states.append({**common, 'reference': ref, 'spent': state['spent'], **metric,
                               'components': len(state['partition']), 'partition_sha256': state['partition_sha256'],
                               'fp_removed': before['fp'] - metric['fp'], 'fn_added': metric['fn'] - before['fn'],
                               'loss_reduction': before['loss'] - metric['loss']})
        for batch in replayed['batches']:
            candidate = batch['candidates']
            entry = {**common, 'batch': batch['batch'], 'spent_before': batch['spent_before'],
                     'selected_depth': len(batch['selected_action']),
                     'fallback': batch['selection_info'].get('fallback_trigger', ''),
                     'diagnostic_score_accesses': candidate['diagnostic_score_accesses'],
                     'pool_scope': candidate['pool_scope']}
            for stage, key in [('generated', 'generated_lexicographic'), ('capped', 'capped_order'),
                               ('validated', 'validated_order'), ('scored', 'scored_order')]:
                entry[stage + '_count'] = len(candidate[key])
                entry[stage + '_multi_count'] = sum(len(p) > 1 for p in candidate[key])
            batches.append(entry)
            sets = {key: {tuple(tuple(e) for e in p) for p in candidate[key]}
                    for key in ('generated_lexicographic', 'capped_order', 'validated_order', 'scored_order')}
            for ref in REFERENCES:
                for opportunity in batch['offline_opportunities'][ref]:
                    key = tuple(tuple(e) for e in opportunity['edges'])
                    opps.append({**common, 'reference': ref, 'batch': batch['batch'],
                                 'spent_before': batch['spent_before'], 'edges_json': json.dumps(opportunity['edges']),
                                 **{k: opportunity[k] for k in ('depth', 'fp_removed', 'fn_added', 'loss_gain')},
                                 'in_generated': key in sets['generated_lexicographic'],
                                 'in_capped': key in sets['capped_order'], 'in_validated': key in sets['validated_order'],
                                 'in_scored': key in sets['scored_order'],
                                 'selected': set(key) == set(batch['selected_action']),
                                 'pool_scope': candidate['pool_scope']})
    contrasts = []
    indexed = {(r['k'], r['score_profile'], r['reference'], r['budget'], r['method']): r for r in endpoints}
    for k in (1, 2, 3):
        for profile in PROFILES:
            for ref in REFERENCES:
                for budget in BUDGETS:
                    raw = indexed[k, profile, ref, budget, METHODS[1]]
                    for comparator in (METHODS[2], METHODS[0]):
                        other = indexed[k, profile, ref, budget, comparator]
                        complete = raw['status'] == other['status'] == 'completed'
                        contrasts.append({'k': k, 'score_profile': profile, 'reference': ref, 'budget': budget,
                                          'contrast': 'raw_minus_' + comparator,
                                          'status': 'complete' if complete else 'missing_comparator',
                                          **{'delta_' + metric: raw[metric] - other[metric] if complete else None
                                             for metric in ('fp', 'fn', 'loss')},
                                          'first_paid_divergence': first_divergence(replays[raw['run_id']]['events'],
                                                                                 replays[other['run_id']]['events']) if complete else None})
    common_cols = ['run_id', 'k', 'score_profile', 'method', 'budget']
    tables = {'acquisitions': (acquisitions, common_cols + ['status', 'spent', 'selector_seconds', 'audit_seconds',
              'worker_wall_seconds', 'logical_score_accesses', 'explicit_multi_batches',
              'paid_lower_bound', 'paid_upper_bound', 'paid_exact', 'process_start_seconds',
              'result_wait_seconds', 'payload_receive_seconds', 'cleanup_seconds']),
              'endpoints': (endpoints, common_cols + ['reference', 'status', 'reused_acquisition', 'fp', 'fn', 'loss',
              'initial_fp', 'initial_fn', 'exact_bound', 'gap_to_bound']),
              'events': (events, common_cols + ['spent', 'batch', 'u', 'v', 'answer', 'category',
              'partition_before_sha256', 'partition_after_sha256']),
              'states': (states, common_cols + ['reference', 'spent', 'fp', 'fn', 'loss', 'components',
              'partition_sha256', 'fp_removed', 'fn_added', 'loss_reduction']),
              'batches': (batches, common_cols + ['batch', 'spent_before', 'selected_depth', 'fallback',
              'diagnostic_score_accesses', 'pool_scope'] + [stage + suffix for stage in ('generated', 'capped', 'validated', 'scored')
              for suffix in ('_count', '_multi_count')]),
              'opportunities': (opps, common_cols + ['reference', 'batch', 'spent_before', 'edges_json', 'depth',
              'fp_removed', 'fn_added', 'loss_gain', 'in_generated', 'in_capped', 'in_validated', 'in_scored', 'selected', 'pool_scope']),
              'bounds': (bounds, ['k', 'reference', 'budget', 'exact_loss', 'exact_fp', 'exact_fn', 'witness_spend', 'status', 'independent_check']),
              'contrasts': (contrasts, ['k', 'score_profile', 'reference', 'budget', 'contrast', 'status',
              'delta_fp', 'delta_fn', 'delta_loss', 'first_paid_divergence']),
              'missing': (missing, common_cols + ['status', 'reason'])}
    for name, (rows, columns) in tables.items():
        csv_write(out / (name + '.csv'), rows, columns)
    lower = sum(row['paid_lower_bound'] for row in acquisitions)
    upper = sum(row['paid_upper_bound'] for row in acquisitions)
    report = {'schema': 'cut-audit-review-v4-synthetic-analysis-v1', 'status': 'passed',
              'study_suite_sha256': digest(study / 'suite.json'), 'freeze_sha256': suite['freeze_sha256'],
              'planned_acquisitions': 90, 'completed_acquisitions': len(replays),
              'offline_reference_evaluations': 2 * len(replays),
              'completed_run_paid_answers': len(events),
              'physical_paid_answers': lower if lower == upper else None,
              'total_paid_lower_bound': lower, 'total_paid_upper_bound': upper,
              'events_scope': 'Completed-run physical answers only; incomplete paid bounds remain in acquisitions.csv',
              'new_oracle_answers_in_analysis': 0, 'independent_experimental_units_claimed': False,
              'table_rows': {name: len(rows) for name, (rows, _) in tables.items()},
              'source_sha256': digest(Path(__file__)),
              'files_sha256': {p.relative_to(out).as_posix(): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    write(out / 'manifest.json', report)
    return report


def check_analysis(study, analysis):
    suite = check_study(study)
    analysis = Path(analysis).resolve()
    report = read(analysis / 'manifest.json')
    require(report['study_suite_sha256'] == digest(Path(study) / 'suite.json')
            and report['freeze_sha256'] == suite['freeze_sha256'], 'Analysis source binding differs')
    check_hashes(analysis, report['files_sha256'])
    actual = {p.relative_to(analysis).as_posix() for p in analysis.rglob('*') if p.is_file()}
    require(actual == set(report['files_sha256']) | {'manifest.json'}, 'Analysis has missing or unlisted files')
    # Rebuild every projection from original paid receipts, not from the CSVs
    # being checked. This catches inconsistent tables even if someone updates
    # their manifest hash. Temporary outputs are strictly offline diagnosis.
    with tempfile.TemporaryDirectory(prefix='cut_audit_v4_synthetic_check_') as temporary:
        rebuilt_path = Path(temporary) / 'analysis'
        rebuilt = analyze(study, rebuilt_path)
        require(set(rebuilt['files_sha256']) == set(report['files_sha256']),
                'Analysis projection inventory differs')
        for name in rebuilt['files_sha256']:
            saved, expected = analysis / name, rebuilt_path / name
            if saved.suffix == '.csv':
                require(saved.read_bytes() == expected.read_bytes(), 'CSV projection differs: ' + name)
            else:
                require(semantic(read(saved)) == semantic(read(expected)), 'Saved replay/bound changed: ' + name)
        for key in ('completed_acquisitions', 'offline_reference_evaluations', 'physical_paid_answers',
                    'completed_run_paid_answers', 'total_paid_lower_bound', 'total_paid_upper_bound',
                    'new_oracle_answers_in_analysis', 'table_rows', 'independent_experimental_units_claimed'):
            require(report[key] == rebuilt[key], 'Analysis accounting differs: ' + key)
    completed = rebuilt['completed_acquisitions']
    return {'status': 'passed', 'completed_acquisitions': completed,
            'offline_reference_evaluations': completed * 2, 'new_oracle_answers': 0,
            'files_verified': len(report['files_sha256'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    freezing = sub.add_parser('freeze')
    for name in ('config', 'out', 'snapshot', 'validation'):
        freezing.add_argument('--' + name, required=True, type=Path)
    running = sub.add_parser('run')
    for name in ('config', 'freeze', 'out'):
        running.add_argument('--' + name, required=True, type=Path)
    analysis = sub.add_parser('analyze')
    analysis.add_argument('--study', required=True, type=Path)
    analysis.add_argument('--out', required=True, type=Path)
    checking = sub.add_parser('check')
    checking.add_argument('--study', required=True, type=Path)
    checking.add_argument('--analysis', required=True, type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        result = create_freeze(ROOT, args.config, args.out, args.snapshot, args.validation)
        result = {'status': 'frozen', 'files': len(result['files_sha256']), 'acquisitions': 90}
    elif args.action == 'run':
        suite = run_study(ROOT, args.config, args.freeze, args.out)
        result = {'status': suite['status'], 'completed': sum(r['status'] == 'completed' for r in suite['runs'])}
    elif args.action == 'analyze':
        full = analyze(args.study, args.out)
        result = {key: full[key] for key in ('status', 'completed_acquisitions', 'offline_reference_evaluations', 'physical_paid_answers')}
    else:
        result = check_analysis(args.study, args.analysis)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if args.action == 'run' and result['status'] != 'completed':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
