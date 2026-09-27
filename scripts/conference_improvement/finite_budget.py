"""Offline clairvoyant finite-budget diagnosis; never imported by a selector.

For each original connected component with n <= 16 and m <= 16, enumerate
every subset of gold-negative original edges.  Query discovery costs are absent:
the resulting optimum is an optimistic endpoint diagnostic, NOT a policy bound
that an adaptive agent can necessarily attain. All gold-positive edges remain.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

import networkx as nx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.structural_study.assets import AssetLoader, DOMAINS, SEEDS, PILOT_ROLES

SESSION = 'outputs/session_20260926_conference'
WDC_ARCHIVE = 'CUT_AUDIT_ER_NEW_DOMAIN_AND_PAPER_HANDOFF.zip'
WDC_SHA256 = '338fde650f51516faabc362562cfb32df138c431e774c1eb0839343689ddabae'
WDC_BASE = 'outputs/session_20260923_new_domain/'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def json_hash(value):
    return digest_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False).encode('utf-8'))


def sha(path):
    return digest_bytes(Path(path).read_bytes())


def contained(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(path.is_relative_to(root), 'Path outside diagnostic workspace')
    return path


def checked_bytes(path, expected):
    blob = Path(path).read_bytes()
    require(digest_bytes(blob) == expected, 'Input SHA256 mismatch: '+str(path))
    return blob


def _pairs(graph):
    return sorted(tuple(sorted(edge)) for edge in graph.edges)


def validate_graph(graph, truth):
    require(isinstance(graph, nx.Graph) and not graph.is_directed() and
            not graph.is_multigraph(), 'Only a simple undirected graph is allowed')
    require(not nx.number_of_selfloops(graph), 'Self-loops are not record pairs')
    require(all(isinstance(n, str) and n for n in graph), 'Record IDs must be nonempty strings')
    require(set(graph) == set(truth), 'Truth must map exactly the permitted graph records')
    require(all(isinstance(v, str) and v for v in truth.values()), 'Entity IDs must be nonempty strings')


def graph_hash(graph):
    # Edge probabilities are irrelevant to this structural, gold-only diagnostic.
    return json_hash({'nodes': sorted(graph), 'edges': _pairs(graph)})


def _choose2(n):
    return n*(n-1)//2


def _metrics(nodes, edges, truth, removed=()):
    """Small DSU computation independent of production metrics/evaluation code."""
    parent = {n: n for n in nodes}
    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    removed = set(removed)
    for u, v in edges:
        if (u, v) not in removed:
            a, b = find(u), find(v)
            if a != b:
                parent[b] = a
    groups = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    predicted = sum(_choose2(len(g)) for g in groups.values())
    tp = sum(sum(_choose2(c) for c in Counter(truth[n] for n in g).values())
             for g in groups.values())
    gold_pairs = sum(_choose2(c) for c in Counter(truth[n] for n in nodes).values())
    return {'fp': predicted-tp, 'fn': gold_pairs-tp, 'loss': predicted+gold_pairs-2*tp}


def _state_key(state):
    return state['loss'], len(state['removed']), state['removed']


def _component(graph, truth, index, max_budget, max_nodes, max_edges):
    nodes, edges = sorted(graph), _pairs(graph)
    initial = _metrics(nodes, edges, truth)
    eligible = len(nodes) <= max_nodes and len(edges) <= max_edges
    result = {'component_index': index, 'node_ids_sha256': json_hash(nodes),
              'topology_sha256': graph_hash(graph), 'nodes': len(nodes), 'edges': len(edges),
              'eligibility_uses': 'original visible node and edge counts only',
              'eligible': eligible, 'initial': initial}
    if not eligible:
        reasons = []
        if len(nodes) > max_nodes: reasons.append('node_cap_exceeded')
        if len(edges) > max_edges: reasons.append('edge_cap_exceeded')
        result.update(status='skipped_visible_cap', reasons=reasons,
                      enumerated_subsets=0, best_exact_spend=[],
                      loss_curve=[initial['loss']]+[None]*max_budget,
                      witness_spend_curve=[0]+[None]*max_budget)
        return result, {}
    negative = [e for e in edges if truth[e[0]] != truth[e[1]]]
    best = {}
    enumerated = 0
    for mask in range(1 << len(negative)):
        spent = mask.bit_count()
        if spent > max_budget:
            continue
        removed = tuple(e for i, e in enumerate(negative) if mask & (1 << i))
        state = {**_metrics(nodes, edges, truth, removed), 'removed': removed}
        enumerated += 1
        if spent not in best or _state_key(state) < _state_key(best[spent]):
            best[spent] = state
    loss_curve, spend_curve = [], []
    incumbent = None
    for budget in range(max_budget+1):
        if budget in best and (incumbent is None or _state_key(best[budget]) < _state_key(incumbent)):
            incumbent = best[budget]
        loss_curve.append(incumbent['loss'])
        spend_curve.append(len(incumbent['removed']))
    result.update(status='exact', original_negative_edges=len(negative),
                  enumerated_subsets=enumerated,
                  best_exact_spend=[{'spent': b, 'fp': s['fp'], 'fn': s['fn'],
                                     'loss': s['loss'], 'removed_edges': list(s['removed'])}
                                    for b, s in sorted(best.items())],
                  loss_curve=loss_curve, witness_spend_curve=spend_curve,
                  witness_rule='Lookup best_exact_spend by witness_spend_curve[B]; ties prefer fewer deletions then lexical pairs')
    return result, best


def diagnose_graph(graph, truth, *, max_budget=48, max_nodes=16, max_edges=16):
    """Return exact component curves, witnesses, and an honest graph-level DP.

When any component exceeds the visible cap, global B>0 optimum is missing.
The separately named interval uses zero loss for skipped components as its
optimistic lower bound and leaves them untouched for its feasible upper bound.
Neither interval endpoint is labeled a complete-graph exact optimum.
"""
    validate_graph(graph, truth)
    for name, value, limit in (('max_budget', max_budget, 48), ('max_nodes', max_nodes, 16),
                                ('max_edges', max_edges, 16)):
        require(type(value) is int and 0 <= value <= limit, f'{name} outside fixed resource limit')
    initial = _metrics(sorted(graph), _pairs(graph), truth)
    groups = sorted((tuple(sorted(g)) for g in nx.connected_components(graph)))
    total_gold_pairs = sum(_choose2(c) for c in Counter(truth.values()).values())
    within_gold_pairs = sum(sum(_choose2(c) for c in Counter(truth[n] for n in g).values()) for g in groups)
    cross_fn = total_gold_pairs-within_gold_pairs
    components = []
    dp = {0: {'fp': 0, 'fn': 0, 'loss': 0, 'removed': ()}}
    skipped_fp = skipped_fn = 0
    for index, nodes in enumerate(groups):
        component, frontier = _component(graph.subgraph(nodes), truth, index, max_budget, max_nodes, max_edges)
        components.append(component)
        if not component['eligible']:
            skipped_fp += component['initial']['fp']
            skipped_fn += component['initial']['fn']
            continue
        updated = {}
        for previous_spent, previous in dp.items():
            for component_spent, state in frontier.items():
                spent = previous_spent+component_spent
                if spent > max_budget:
                    continue
                candidate = {k: previous[k]+state[k] for k in ('fp', 'fn', 'loss')}
                candidate['removed'] = tuple(sorted(previous['removed']+state['removed']))
                if spent not in updated or _state_key(candidate) < _state_key(updated[spent]):
                    updated[spent] = candidate
        dp = updated
    skipped = sum(not c['eligible'] for c in components)
    curve, witnesses = [], {}
    incumbent = None
    for budget in range(max_budget+1):
        if budget in dp and (incumbent is None or _state_key(dp[budget]) < _state_key(incumbent)):
            incumbent = dp[budget]
        removed = incumbent['removed']
        witness_id = json_hash(removed)
        witnesses.setdefault(witness_id, {'removed_edges': list(removed), 'spent': len(removed)})
        feasible = {'fp': incumbent['fp']+skipped_fp,
                    'fn': incumbent['fn']+skipped_fn+cross_fn,
                    'loss': incumbent['loss']+skipped_fp+skipped_fn+cross_fn}
        exact = not skipped or budget == 0
        row = {'budget': budget, 'status': 'exact' if exact else 'missing_due_to_skipped_components',
               'exact_loss': feasible['loss'] if exact else None,
               'exact_fp': feasible['fp'] if exact else None,
               'exact_fn': feasible['fn'] if exact else None,
               'exact_witness_id': witness_id if exact else None,
               'optimistic_lower_bound': feasible['loss'] if exact else incumbent['loss']+cross_fn,
               'feasible_upper_bound': feasible['loss'], 'feasible_fp': feasible['fp'], 'feasible_fn': feasible['fn'],
               'feasible_witness_id': witness_id, 'feasible_deleted_edges': len(removed)}
        curve.append(row)
    return {'schema': 'cut-audit-offline-finite-budget-graph-v1',
            'scope': 'clairvoyant offline exposed-graph diagnosis; not an adaptive policy guarantee',
            'topology_sha256': graph_hash(graph),
            'permitted_gold_mapping_sha256': json_hash(sorted(truth.items())),
            'max_budget': max_budget, 'visible_component_caps': {'nodes': max_nodes, 'edges': max_edges},
            'nodes': len(graph), 'edges': graph.number_of_edges(), 'initial': initial,
            'initial_cross_component_fn': cross_fn, 'components_total': len(components),
            'components_exact': len(components)-skipped, 'components_skipped': skipped,
            'initial_fp_in_skipped_components': skipped_fp,
            'status': 'exact' if not skipped else 'partial_component_diagnosis',
            'curve': curve, 'witnesses': witnesses, 'components': components,
            'new_policy_runs': 0, 'new_oracle_queries': 0, 'model_fits': 0, 'formal_test_access': False,
            'assumptions': {'perfect_oracle': True, 'gold_positive_edges_retained': True,
                            'original_edges_only': True, 'node_preserving': True, 'lambda': 1,
                            'oracle_answers_known_offline_without_discovery_cost': True}}


def load_wdc_asset(root):
    """Pin archived observable graph and extract only its exposed evaluation gold.

The old WDC normalized file is read locally for ID/entity columns only. No text
is retained or exported, and no train/calibration/completion mapping is returned.
"""
    root = Path(root).resolve()
    archive = contained(root, WDC_ARCHIVE)
    checked_bytes(archive, WDC_SHA256)
    receipts = {WDC_ARCHIVE: WDC_SHA256}
    with zipfile.ZipFile(archive) as zipped:
        manifest = json.loads(zipped.read('MANIFEST.json'))['files']
        def member(relative):
            blob = zipped.read(relative)
            require(relative in manifest and digest_bytes(blob) == manifest[relative]['sha256']
                    and len(blob) == manifest[relative]['bytes'], 'Archived member hash mismatch')
            receipts[WDC_ARCHIVE+'::'+relative] = digest_bytes(blob)
            return json.loads(blob)
        freeze = member(WDC_BASE+'scientific_freeze.json')
        require(freeze['formal_test_access'] is False, 'WDC scope claims formal-test access')
        cfg = member(freeze['config_path'])
        members = member(WDC_BASE+'study/memberships.json')
        original_members = member(freeze['cohort_manifest_path'])
        for relative in (freeze['config_path'], freeze['cohort_manifest_path']):
            require(receipts[WDC_ARCHIVE+'::'+relative] == freeze['files_sha256'][relative],
                    'WDC config/cohort bytes differ from scientific freeze')
        require(members == original_members, 'Archived WDC role membership differs from cohort freeze')
        base = WDC_BASE+'study/evaluation_observable_graph/'
        saved = member(base+'observable_graph.json')
        hashes = member(base+'hashes.json')
        require(hashes['observable_graph.json'] == receipts[WDC_ARCHIVE+'::'+base+'observable_graph.json'],
                'Observable graph hash differs from graph receipt')
        expected = freeze['files_sha256'][cfg['normalized_csv']]
        require(expected == cfg['normalized_sha256'] == members['normalized_data_sha256'],
                'WDC normalized identity differs across frozen artifacts')
        normalized = contained(root, cfg['normalized_csv'])
        blob = checked_bytes(normalized, expected)
        receipts[cfg['normalized_csv']] = expected
        role = members['roles']['evaluation']
        allowed = set(role['record_ids'])
        require(role['status'] == 'eligible' and len(allowed) == role['records'] and
                saved['contains_gold_or_text'] is False and
                set(saved['nodes']) == set(saved['record_ids']) == allowed,
                'Observable graph does not equal the frozen evaluation role')
        require(json_hash(role['record_ids']) == role['record_ids_sha256'] and
                json_hash(role['entity_ids']) == role['entity_ids_sha256'], 'Role membership hash mismatch')
        truth = {}
        reader = csv.DictReader(io.StringIO(blob.decode('utf-8'), newline=''))
        require(reader.fieldnames is not None and {'record_id', 'entity_id'} <= set(reader.fieldnames),
                'Normalized ID/entity columns missing')
        for row in reader:
            if row['record_id'] in allowed:
                require(row['record_id'] not in truth, 'Duplicate permitted WDC record')
                truth[row['record_id']] = row['entity_id']
        require(set(truth) == allowed and set(truth.values()) == set(role['entity_ids']),
                'Incomplete or changed WDC evaluation gold mapping')
        graph = nx.Graph(); graph.add_nodes_from(sorted(allowed))
        for u, v, p in saved['edges']:
            require(u in allowed and v in allowed and u != v and not graph.has_edge(u, v),
                    'Invalid archived WDC graph edge')
            graph.add_edge(u, v)
        validate_graph(graph, truth)
    return graph, truth, {'graph_id': 'wdc:evaluation:20260923', 'role': 'evaluation',
                          'source_mode': 'archive_pinned_graph_and_frozen_normalized_eval_ID_entity_columns',
                          'source_receipts': receipts, 'new_queries': 0, 'new_fits': 0,
                          'test_records_loaded': False, 'text_exported': False}


def diagnostic_bundle(graph, truth, provenance):
    validate_graph(graph, truth)
    return {'schema': 'cut-audit-exposed-offline-diagnostic-input-v1',
            'scope': 'Previously exposed development/evaluation only; forbidden as a selector input',
            'contains_gold_reference_ids': True, 'contains_text': False, 'formal_test_records': False,
            'nodes': sorted(graph), 'edges': _pairs(graph),
            'reference_entity_ids': dict(sorted(truth.items())),
            'topology_sha256': graph_hash(graph),
            'gold_mapping_sha256': json_hash(sorted(truth.items())), 'provenance': provenance}


def load_diagnostic_bundle(path, expected_sha256):
    bundle = json.loads(checked_bytes(path, expected_sha256))
    require(bundle['schema'] == 'cut-audit-exposed-offline-diagnostic-input-v1' and
            bundle['contains_gold_reference_ids'] is True and bundle['contains_text'] is False and
            bundle['formal_test_records'] is False, 'Diagnostic bundle scope mismatch')
    nodes = bundle['nodes']; truth = bundle['reference_entity_ids']
    require(len(nodes) == len(set(nodes)), 'Duplicate diagnostic input node')
    graph = nx.Graph(); graph.add_nodes_from(nodes)
    for u, v in bundle['edges']:
        require(u in graph and v in graph and u != v and not graph.has_edge(u, v),
                'Invalid diagnostic input edge')
        graph.add_edge(u, v)
    validate_graph(graph, truth)
    require(graph_hash(graph) == bundle['topology_sha256'] and
            json_hash(sorted(truth.items())) == bundle['gold_mapping_sha256'],
            'Diagnostic bundle topology/gold mapping hash mismatch')
    return graph, truth, bundle['provenance']


def source_boundary(root):
    """Fail closed if production code imports this deliberately offline module."""
    checked = {}
    for path in sorted((Path(root)/'src').rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                     [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            require(not any('finite_budget' in n or 'conference_improvement' in n for n in names),
                    'Offline finite-budget diagnosis imported into production source')
        checked[path.relative_to(root).as_posix()] = sha(path)
    return {'production_files_checked': checked, 'offline_module_not_imported_by_production': True}


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def run_existing(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    require(out.is_relative_to(root), 'Output outside workspace')
    out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    sources = ['scripts/conference_improvement/finite_budget.py', 'scripts/structural_study/assets.py',
               'tests/test_conference_finite_budget.py']
    frozen = {p: sha(root/p) for p in sources}
    for relative in sources:
        target = out/'source_snapshot'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/relative, target)
    write(out/'execution_freeze.json', {'created_utc': datetime.now(timezone.utc).isoformat(),
          'files_sha256': frozen, 'planned_graphs': 11, 'max_budget': 48,
          'max_nodes_per_initial_component': 16, 'max_edges_per_initial_component': 16,
          'selection_uses_outcomes': False, 'test_access': False})
    write(out/'selector_boundary.json', source_boundary(root))
    planned = [dict(family='historical', dataset=d, seed=s, role='development') for d in DOMAINS for s in SEEDS]
    planned += [dict(family='pilot', dataset=d, seed=7, role=r) for d in DOMAINS for r in PILOT_ROLES]
    planned += [dict(family='wdc', dataset='wdc', seed=20260919, role='evaluation')]
    records, flat = [], []
    loader = None
    (out/'inputs').mkdir()
    for index, identity in enumerate(planned):
        record = {**identity, 'graph_index': index, 'status': 'missing_or_invalid'}
        try:
            if identity['family'] == 'wdc':
                graph, truth, provenance = load_wdc_asset(root)
            else:
                if loader is None: loader = AssetLoader(root)
                graph, truth, provenance = loader.load(**identity)
            input_path = out/'inputs'/f'graph_{index:02d}.json'
            write(input_path, diagnostic_bundle(graph, truth, provenance))
            record.update(input_bundle=input_path.relative_to(out).as_posix(), input_sha256=sha(input_path))
            result = diagnose_graph(graph, truth)
            filename = f'graph_{index:02d}.json'
            write(out/filename, {'identity': identity, 'provenance': provenance, 'diagnosis': result})
            record.update(status=result['status'], graph_id=provenance['graph_id'], result_path=filename,
                          result_sha256=sha(out/filename), nodes=result['nodes'], edges=result['edges'],
                          components_total=result['components_total'], components_exact=result['components_exact'],
                          components_skipped=result['components_skipped'],
                          initial_fp=result['initial']['fp'], initial_fn=result['initial']['fn'],
                          initial_fp_in_skipped_components=result['initial_fp_in_skipped_components'])
            flat.extend({'graph_index': index, 'graph_id': provenance['graph_id'], **r} for r in result['curve'])
        except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as exc:
            record['reason'] = f'{type(exc).__name__}: {exc}'
        records.append(record)
        write(out/f'progress_{index:02d}.json', record)
    if flat:
        with (out/'graph_curves.csv').open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(flat[0])); writer.writeheader(); writer.writerows(flat)
    for relative, expected in frozen.items():
        require(sha(root/relative) == expected, 'Offline diagnostic source changed during execution')
    source_boundary(root)
    missing = sum(r['status'] == 'missing_or_invalid' for r in records)
    summary = {'schema': 'cut-audit-offline-finite-budget-suite-v1',
               'status': 'completed_with_missing_assets' if missing else 'completed',
               'planned_graphs': 11, 'loaded_graphs': 11-missing, 'graphs': records,
               'all_budgets': list(range(49)), 'seconds': time.perf_counter()-start,
               'new_policy_runs': 0, 'new_queries': 0, 'new_fits': 0, 'formal_test_access': False,
               'claim_limit': 'Partial component diagnosis is not an exact whole-graph optimum; witnesses assume known gold negatives and omit discovery costs.'}
    write(out/'summary.json', summary)
    write(out/'outputs_sha256.json', {p.relative_to(out).as_posix(): sha(p)
          for p in sorted(out.rglob('*')) if p.is_file() and 'source_snapshot' not in p.parts})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--input-bundle', type=Path,
                        help='Replay one hash-bound exposed diagnostic input without external datasets')
    parser.add_argument('--input-sha256')
    args = parser.parse_args()
    out = args.out if args.out.is_absolute() else args.root/args.out
    if args.input_bundle is not None:
        require(bool(args.input_sha256), 'Portable replay requires expected input SHA256')
        graph, truth, provenance = load_diagnostic_bundle(args.input_bundle, args.input_sha256)
        out = out.resolve(); require(out.is_relative_to(args.root.resolve()), 'Output outside workspace')
        out.mkdir(parents=True, exist_ok=False)
        result = diagnose_graph(graph, truth)
        write(out/'diagnosis.json', {'input_sha256': args.input_sha256,
                                   'provenance': provenance, 'diagnosis': result})
        print(json.dumps({'status': result['status'], 'components_exact': result['components_exact'],
                          'components_skipped': result['components_skipped']}))
        return
    require(args.input_sha256 is None, 'Input hash supplied without diagnostic input')
    result = run_existing(args.root, out)
    print(json.dumps({k: result[k] for k in ('status', 'planned_graphs', 'loaded_graphs', 'seconds')}))
    raise SystemExit(0 if result['loaded_graphs'] == 11 else 2)


if __name__ == '__main__':
    main()
