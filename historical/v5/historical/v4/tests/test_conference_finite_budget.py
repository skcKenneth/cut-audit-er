"""Independent constructed tests; no benchmark text, selectors, or fitting."""
import ast
import hashlib
import itertools
import json
from pathlib import Path
import zipfile

import networkx as nx
import pytest

from scripts.conference_improvement import finite_budget as fb


def brute(graph, truth, budget):
    """Deliberately use NetworkX components and direct unordered-pair counting."""
    false = sorted(tuple(sorted(e)) for e in graph.edges if truth[e[0]] != truth[e[1]])
    best = None
    for count in range(min(budget, len(false))+1):
        for removed in itertools.combinations(false, count):
            retained = graph.copy(); retained.remove_edges_from(removed)
            labels = {n: i for i, nodes in enumerate(nx.connected_components(retained)) for n in nodes}
            fp = fn = 0
            for u, v in itertools.combinations(sorted(graph), 2):
                connected, match = labels[u] == labels[v], truth[u] == truth[v]
                fp += connected and not match
                fn += match and not connected
            candidate = (fp+fn, count, removed, fp, fn)
            if best is None or candidate[:3] < best[:3]: best = candidate
    return best


def verify_curve(graph, truth, result):
    previous = float('inf')
    for row in result['curve']:
        expected = brute(graph, truth, row['budget'])
        assert row['status'] == 'exact'
        assert (row['exact_loss'], row['exact_fp'], row['exact_fn']) == (expected[0], expected[3], expected[4])
        witness = result['witnesses'][row['exact_witness_id']]
        assert tuple(map(tuple, witness['removed_edges'])) == expected[2]
        assert witness['spent'] <= row['budget']
        assert all(truth[u] != truth[v] and graph.has_edge(u, v) for u, v in witness['removed_edges'])
        assert row['exact_loss'] <= previous
        previous = row['exact_loss']


def test_exhaustive_all_four_node_graphs_and_binary_truth_assignments():
    nodes = list('abcd'); edges = list(itertools.combinations(nodes, 2))
    for graph_bits in range(1 << len(edges)):
        graph = nx.Graph(); graph.add_nodes_from(nodes)
        graph.add_edges_from(e for i, e in enumerate(edges) if graph_bits & (1 << i))
        for truth_bits in range(1 << len(nodes)):
            truth = {n: str((truth_bits >> i) & 1) for i, n in enumerate(nodes)}
            result = fb.diagnose_graph(graph, truth, max_budget=3)
            verify_curve(graph, truth, result)


def test_cross_component_fn_is_constant_and_isolates_retained():
    graph = nx.Graph(); graph.add_nodes_from(['a1', 'a2', 'b']); graph.add_edge('a1', 'b')
    truth = {'a1': 'a', 'a2': 'a', 'b': 'b'}
    result = fb.diagnose_graph(graph, truth)
    assert result['nodes'] == 3 and result['initial_cross_component_fn'] == 1
    assert len(result['curve']) == 49
    assert result['curve'][0]['exact_loss'] == 2
    assert all(row['exact_loss'] == 1 for row in result['curve'][1:])
    verify_curve(graph, truth, result)


def test_false_edge_deletion_can_increase_fn_and_all_negative_deletion_is_not_optimal():
    graph = nx.star_graph(['b', 'a1', 'a2', 'a3', 'a4'])
    truth = {n: 'a' if n != 'b' else 'b' for n in graph}
    result = fb.diagnose_graph(graph, truth, max_budget=4)
    frontier = result['components'][0]['best_exact_spend']
    assert frontier[0]['loss'] == 4
    assert frontier[1]['fn'] == 3 and frontier[1]['loss'] == 6
    assert frontier[4]['fn'] == 6 and frontier[4]['loss'] == 6
    assert result['components'][0]['loss_curve'] == [4]*5
    assert all(r['feasible_deleted_edges'] == 0 for r in result['curve'])
    verify_curve(graph, truth, result)


def test_component_budget_dp_spends_where_it_reduces_most_loss():
    graph = nx.Graph([('a1', 'a2'), ('a2', 'b1'), ('b1', 'b2'), ('c', 'd')])
    truth = {'a1': 'a', 'a2': 'a', 'b1': 'b', 'b2': 'b', 'c': 'c', 'd': 'd'}
    result = fb.diagnose_graph(graph, truth, max_budget=3)
    assert result['curve'][0]['exact_loss'] == 5
    assert result['curve'][1]['exact_loss'] == 1
    assert result['curve'][2]['exact_loss'] == 0
    verify_curve(graph, truth, result)


def test_caps_never_disguise_partial_bound_as_full_exact():
    graph = nx.Graph([('a', 'b'), ('b', 'c'), ('x', 'y')])
    truth = {n: n for n in graph}
    result = fb.diagnose_graph(graph, truth, max_budget=3, max_nodes=2)
    assert result['components_skipped'] == 1
    assert result['curve'][0]['exact_loss'] == 4
    for row in result['curve'][1:]:
        assert row['exact_loss'] is None and row['exact_witness_id'] is None
        exact = brute(graph, truth, row['budget'])[0]
        assert row['optimistic_lower_bound'] <= exact <= row['feasible_upper_bound']
        assert row['feasible_upper_bound'] == 3
    skipped = next(c for c in result['components'] if not c['eligible'])
    assert skipped['loss_curve'] == [3, None, None, None]
    # Eligibility cannot change if all the same vertices have the same entity.
    same = fb.diagnose_graph(graph, {n: 'e' for n in graph}, max_budget=3, max_nodes=2)
    assert [c['eligible'] for c in same['components']] == [c['eligible'] for c in result['components']]


def test_graph_and_witness_hashes_ignore_insertion_order_and_probabilities():
    one = nx.Graph(); one.add_nodes_from(list('dcba')); one.add_edges_from([('b','a'),('c','d')], p=.1)
    two = nx.Graph(); two.add_nodes_from(list('abcd')); two.add_edges_from([('d','c'),('a','b')], p=.9)
    truth = {n:n for n in one}
    assert fb.diagnose_graph(one, truth, max_budget=2) == fb.diagnose_graph(two, truth, max_budget=2)


def test_empty_graph_and_zero_budget_are_exact():
    assert fb.diagnose_graph(nx.Graph(), {}, max_budget=0)['curve'][0]['exact_loss'] == 0
    graph = nx.complete_graph(list('abc'))
    result = fb.diagnose_graph(graph, {n:n for n in graph}, max_budget=0, max_edges=0)
    assert result['components_skipped'] == 1 and result['curve'][0]['exact_loss'] == 3


@pytest.mark.parametrize('case', ['directed', 'multi', 'self', 'missing', 'extra', 'id', 'entity'])
def test_invalid_graph_or_gold_mapping_rejected(case):
    graph = nx.Graph([('a','b')]); truth = {'a':'a','b':'b'}
    if case == 'directed': graph = nx.DiGraph(graph)
    if case == 'multi': graph = nx.MultiGraph(graph)
    if case == 'self': graph.add_edge('a','a')
    if case == 'missing': truth.pop('a')
    if case == 'extra': truth['c'] = 'c'
    if case == 'id': graph = nx.Graph([(1,2)]); truth = {1:'a',2:'b'}
    if case == 'entity': truth['a'] = ''
    with pytest.raises(ValueError): fb.diagnose_graph(graph, truth)


@pytest.mark.parametrize('arguments', [{'max_budget': 49}, {'max_budget': True}, {'max_nodes':17}, {'max_edges':17}])
def test_caps_cannot_escalate(arguments):
    with pytest.raises(ValueError): fb.diagnose_graph(nx.Graph(), {}, **arguments)


def test_input_hash_mismatch_and_missing_are_not_silent(tmp_path):
    path = tmp_path/'asset.json'; path.write_bytes(b'{}')
    assert fb.checked_bytes(path, hashlib.sha256(b'{}').hexdigest()) == b'{}'
    with pytest.raises(ValueError, match='SHA256'): fb.checked_bytes(path, '0'*64)
    with pytest.raises(FileNotFoundError): fb.checked_bytes(tmp_path/'missing', '0'*64)
    with pytest.raises(ValueError): fb.contained(tmp_path, '../outside')


def test_offline_module_has_no_selector_fit_or_production_metric_import():
    tree = ast.parse(Path(fb.__file__).read_text(encoding='utf-8'))
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any((m or '').startswith('cut_audit_er') for m in imports)
    calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert not any(n in calls for n in ('fit', 'predict', 'run_audit', 'bounded_audit', 'graph_for'))


def test_source_boundary_rejects_production_import(tmp_path):
    src = tmp_path/'src'; src.mkdir(); p = src/'fixture.py'
    p.write_text('x = 1\n')
    assert fb.source_boundary(tmp_path)['offline_module_not_imported_by_production']
    p.write_text('from scripts.conference_improvement import finite_budget\n')
    with pytest.raises(ValueError): fb.source_boundary(tmp_path)


def test_portable_input_replays_exactly_and_rejects_gold_corruption(tmp_path):
    graph = nx.Graph([('a','b')]); graph.add_node('isolate')
    truth = {'a':'a','b':'b','isolate':'a'}
    blob = json.dumps(fb.diagnostic_bundle(graph, truth, {'graph_id':'constructed'})).encode()
    path = tmp_path/'bundle.json'; path.write_bytes(blob)
    g, gold, provenance = fb.load_diagnostic_bundle(path, hashlib.sha256(blob).hexdigest())
    assert fb.diagnose_graph(g, gold) == fb.diagnose_graph(graph, truth)
    assert provenance == {'graph_id':'constructed'}
    corrupted = json.loads(blob); corrupted['reference_entity_ids']['a'] = 'different'
    path.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError, match='mapping hash'):
        fb.load_diagnostic_bundle(path, fb.sha(path))
    corrupted['formal_test_records'] = True; path.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError, match='scope'):
        fb.load_diagnostic_bundle(path, fb.sha(path))


def make_wdc_fixture(tmp_path, monkeypatch):
    raw = b'record_id,entity_id,text\na,e,never export this\nb,e,never export this either\nother,other-role,also excluded\n'
    normalized = tmp_path/'normalized.csv'; normalized.write_bytes(raw)
    h = hashlib.sha256(raw).hexdigest()
    role = {'record_ids':['a','b'], 'entity_ids':['e'], 'records':2, 'status':'eligible',
            'record_ids_sha256':fb.json_hash(['a','b']), 'entity_ids_sha256':fb.json_hash(['e'])}
    members = {'normalized_data_sha256':h, 'roles':{'evaluation':role}}
    cfg = {'normalized_csv':'normalized.csv', 'normalized_sha256':h}
    config_path = 'config.json'; cohort_path = 'cohort.json'
    saved = {'nodes':['a','b'], 'record_ids':['a','b'], 'edges':[['a','b',.7]], 'contains_gold_or_text':False}
    files = {}
    def add(path, value): files[path] = json.dumps(value).encode()
    add(config_path, cfg); add(cohort_path, members)
    add(fb.WDC_BASE+'study/memberships.json', members)
    base = fb.WDC_BASE+'study/evaluation_observable_graph/'
    add(base+'observable_graph.json', saved)
    add(base+'hashes.json', {'observable_graph.json':hashlib.sha256(files[base+'observable_graph.json']).hexdigest()})
    add(fb.WDC_BASE+'scientific_freeze.json', {'formal_test_access':False, 'config_path':config_path,
        'cohort_manifest_path':cohort_path, 'files_sha256':{'normalized.csv':h,
            config_path:hashlib.sha256(files[config_path]).hexdigest(),
            cohort_path:hashlib.sha256(files[cohort_path]).hexdigest()}})
    manifest = {'files':{p:{'sha256':hashlib.sha256(v).hexdigest(), 'bytes':len(v)} for p,v in files.items()}}
    archive = tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        for path, data in files.items(): zipped.writestr(path, data)
        zipped.writestr('MANIFEST.json', json.dumps(manifest))
    monkeypatch.setattr(fb, 'WDC_ARCHIVE', archive.name)
    monkeypatch.setattr(fb, 'WDC_SHA256', fb.sha(archive))
    return normalized


def test_wdc_extracts_exact_exposed_role_only_and_hashes_before_read(tmp_path, monkeypatch):
    normalized = make_wdc_fixture(tmp_path, monkeypatch)
    graph, truth, provenance = fb.load_wdc_asset(tmp_path)
    assert set(graph) == {'a','b'} and truth == {'a':'e','b':'e'}
    assert 'never export' not in json.dumps(fb.diagnostic_bundle(graph, truth, provenance))
    assert provenance['test_records_loaded'] is False and provenance['text_exported'] is False
    normalized.write_text('changed')
    with pytest.raises(ValueError, match='SHA256'):
        fb.load_wdc_asset(tmp_path)
    normalized.unlink()
    with pytest.raises(FileNotFoundError): fb.load_wdc_asset(tmp_path)


def test_missing_assets_keep_all_eleven_prespecified_rows(tmp_path, monkeypatch):
    for relative in ('scripts/conference_improvement/finite_budget.py', 'scripts/structural_study/assets.py',
                     'tests/test_conference_finite_budget.py'):
        path = tmp_path/relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# fixture\n')
    def unavailable(*args, **kwargs): raise ValueError('Missing constructed fixture input')
    monkeypatch.setattr(fb, 'AssetLoader', unavailable)
    monkeypatch.setattr(fb, 'load_wdc_asset', unavailable)
    result = fb.run_existing(tmp_path, tmp_path/'fresh')
    assert result['planned_graphs'] == 11 and result['loaded_graphs'] == 0
    assert len(result['graphs']) == 11 and all(r['status']=='missing_or_invalid' for r in result['graphs'])
    with pytest.raises(FileExistsError): fb.run_existing(tmp_path, tmp_path/'fresh')
