"""Load ten prespecified exposed graphs from existing archives without refitting.

Gold is returned ONLY for offline structural diagnostics. The loader never opens
raw/processed record datasets, calls a matcher/selector, or returns a sealed role.
Saved edge-only values are not a reconstruction of historical dense scores.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import networkx as nx


DOMAINS = ('affiliations', 'geographic_corrected')
SEEDS = (7, 17, 29)
PILOT_ROLES = ('completion_fit', 'exploratory_evaluation')
RANKING = 'reproducibility/ranking_20260915/results'
REVISION = 'reproducibility/revision_20260915/results'
PILOT = 'outputs/session_20260919_calibration'
ANCHOR_DIR = 'reproducibility/structural_20260919/asset_anchors'
ARCHIVES = {
    'ranking': {
        'archive': 'CUT_AUDIT_ER_RANKING_DIAGNOSIS_HANDOFF.zip',
        'archive_sha256': '9fb01f5fabfbd1e89e56ca988711486df832d4406894b0cfd16cfa86fec47d66',
        'manifest': 'ranking_manifest.json',
        'manifest_sha256': '391dd97a6b7e1d9a279477619e0f1054193d86a5b8cdb1940e78db4a2adf56e5',
    },
    'calibration': {
        'archive': 'CUT_AUDIT_ER_CALIBRATION_PILOT_HANDOFF.zip',
        'archive_sha256': '78eac322e08ae3ed5e2983dcc1ef6d6af911ffcd28c8cf124c3477f20c6c26b0',
        'manifest': 'calibration_manifest.json',
        'manifest_sha256': '4e7f5cb14af3b857b0741aa3a62af2f6b391ba584c5dc54acf09951c8a24280e',
    },
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _ids_hash(values):
    return _sha('\n'.join(sorted(values)).encode())


def _pair(edge):
    _require(len(edge) == 2 and all(isinstance(x,str) for x in edge), 'Invalid edge endpoints')
    _require(edge[0] != edge[1], 'Self-loop is not an unordered record pair')
    return tuple(sorted(edge))


def graph_fingerprint(graph, *, probabilities=True):
    edges = sorted((min(u,v),max(u,v),float(a['p'])) for u,v,a in graph.edges(data=True)) if probabilities else sorted(_pair(e) for e in graph.edges)
    return _sha(json.dumps({'nodes':sorted(graph),'edges':edges},sort_keys=True).encode())


def _make_graph(nodes, edges):
    _require(len(nodes) == len(set(nodes)), 'Duplicate node identity')
    graph = nx.Graph(); graph.add_nodes_from(sorted(nodes)); seen = set()
    for u,v,p in edges:
        e = _pair((u,v))
        _require(e not in seen, 'Duplicate physical edge')
        _require(u in graph and v in graph, 'Edge endpoint outside declared role')
        _require(isinstance(p,(int,float)) and math.isfinite(p) and 0 <= p <= 1, 'Invalid archived edge probability')
        graph.add_edge(*e,p=float(p));seen.add(e)
    return graph


def _truth_from_rows(rows, dataset, seed):
    # This archived metric table contains development rows only. Select one
    # complete case to include each record once, including all initial isolates.
    selected = [r for r in rows if r['method'] == 'cut_plan_fixed' and r['requested_budget'] == '12']
    _require(bool(selected), 'Missing B12 fixed record identities')
    _require(all(r['dataset'] == dataset and int(r['seed']) == seed for r in selected), 'Record-table identity mismatch')
    truth = {}
    for row in selected:
        node,entity = row['record_id'],row['entity_id']
        _require(bool(node) and bool(entity) and node not in truth, 'Duplicate or missing record/entity identity')
        truth[node] = entity
    return truth


def _check_membership(truth, expected):
    observed = {'records':len(truth),'entities':len(set(truth.values())),
                'record_ids_sha256':_ids_hash(truth),'entity_ids_sha256':_ids_hash(set(truth.values()))}
    _require(observed == expected, 'Allowed record/entity membership does not match frozen role')
    return observed


def _check_run_bindings(rows, fingerprint):
    _require(bool(rows), 'Missing historical run cases')
    completed=[r for r in rows if r['status']=='completed']
    _require(bool(completed), 'No completed graph-bound historical reference')
    _require(all(r['original_graph_fingerprint_sha256']==fingerprint for r in completed),
             'Completed historical runs not matched to graph')
    # A killed worker has no result metadata. Its absent fingerprint is unknown,
    # not a mismatch and not grounds to exclude this otherwise verified graph.
    _require(all(not r['original_graph_fingerprint_sha256'] or r['original_graph_fingerprint_sha256']==fingerprint for r in rows),
             'Historical run declares a different graph')
    _require(all(float(r['threshold'])==.6 and int(r['top_k'])==10 for r in rows),
             'Historical graph settings changed')


class AssetLoader:
    """Reusable archive-pinned reader; no evaluation is performed by this class."""
    def __init__(self, root):
        self.root = Path(root).resolve();self.manifests={};self.receipts={};self.archive_checks={}
        for name,spec in ARCHIVES.items():
            path = self._path(f'{ANCHOR_DIR}/{spec["manifest"]}')
            blob = path.read_bytes()
            _require(_sha(blob) == spec['manifest_sha256'], 'Pinned archive manifest changed: '+name)
            self.manifests[name] = json.loads(blob)['files']
            self.receipts[path.relative_to(self.root).as_posix()] = _sha(blob)
            archive = self._path(spec['archive'])
            if archive.is_file():
                _require(_sha(archive.read_bytes()) == spec['archive_sha256'], 'Historical archive changed: '+name)
                state = 'original_archive_present_and_rehashed'
            else:
                state = 'portable_manifest_only_original_archive_not_shipped'
            self.archive_checks[name] = {**spec,'validation':state}

    def _path(self, relative):
        path=(self.root/relative).resolve()
        _require(path.is_relative_to(self.root), 'Asset path escapes workspace/package')
        return path

    def read(self, relative, anchor):
        _require(relative in self.manifests[anchor], 'Asset absent from pinned archive manifest: '+relative)
        blob=self._path(relative).read_bytes();expected=self.manifests[anchor][relative]
        _require(_sha(blob) == expected['sha256'] and len(blob) == expected['bytes'], 'Archived asset bytes changed: '+relative)
        self.receipts[relative]=expected['sha256']
        return blob

    def json(self, relative, anchor):
        return json.loads(self.read(relative,anchor))

    def csv(self, relative, anchor):
        return list(csv.DictReader(io.StringIO(self.read(relative,anchor).decode('utf-8'),newline='')))

    def _old(self,dataset,seed):
        ranking=self.json(f'{RANKING}/ranking/ranking_summary.json','ranking')
        metrics=self.json(f'{RANKING}/metrics/summary.json','ranking')
        references=self.json(f'{REVISION}/initial_mechanisms/mechanism_diagnostics.json','ranking')['graph_records']
        meta=next(r for r in ranking['graphs'] if (r['dataset'],r['seed']) == (dataset,seed))
        metric_meta=next(r for r in metrics['graphs'] if (r['dataset'],r['seed']) == (dataset,seed))
        reference=next(r for r in references if (r['dataset'],r['seed']) == (dataset,seed))
        _require(meta['splits'] == metric_meta['splits'] == reference['splits'], 'Historical split provenance disagrees')
        # The ranking ZIP kept these hashes inside graph metadata, whereas the
        # calibration ZIP also ships the unchanged standalone holdout manifest.
        sealed=self.json('research/SEALED_HOLDOUT_MANIFEST.json','calibration')['datasets'][dataset]
        _require(meta['splits']['test'] == sealed['holdout'], 'Sealed membership hash changed')
        _require(meta['input_sha256'] == reference['input_sha256'] == sealed['normalized_sha256'], 'Historical input provenance disagrees')
        edge_file=f'{dataset}_{seed}_edges.csv';record_file=f'records_{dataset}_{seed}.csv'
        edge_path=f'{RANKING}/ranking/{edge_file}';record_path=f'{RANKING}/metrics/{record_file}'
        rows=self.csv(edge_path,'ranking');record_rows=self.csv(record_path,'ranking')
        _require(self.receipts[edge_path] == ranking['output_sha256'][edge_file], 'Edge table hash differs from ranking summary')
        _require(self.receipts[record_path] == metrics['output_sha256'][record_file], 'Record table hash differs from metrics summary')
        truth=_truth_from_rows(record_rows,dataset,seed);membership=_check_membership(truth,meta['splits']['development'])
        initial=[r for r in rows if r['method']=='cut_plan_fixed' and r['spent']=='0']
        _require(all(r['dataset']==dataset and int(r['seed'])==seed for r in initial), 'Initial edge table identity mismatch')
        edges=[]
        for row in initial:
            u,v=_pair(json.loads(row['edge']));negative=float(row['negative_probability'])
            _require(math.isfinite(negative) and 0<=negative<=1,'Invalid archived negative probability')
            edges.append((u,v,1-negative))
        graph=_make_graph(list(truth),edges)
        fingerprint=graph_fingerprint(graph);topology=graph_fingerprint(graph,probabilities=False)
        _require(topology == reference['topology_sha256'], 'Historical initial topology differs')
        _require(fingerprint == meta['graph_fingerprint_sha256'] == metric_meta['graph_fingerprint_sha256'], 'Historical edge probability fingerprint differs')
        main_summary=self.json(f'{REVISION}/main/summary.json','ranking')
        main_path=f'{REVISION}/main/runs.csv';run_rows=self.csv(main_path,'ranking')
        _require(self.receipts[main_path]==main_summary['output_sha256']['runs.csv'],'Historical run-table hash differs')
        matching=[r for r in run_rows if r['dataset']==dataset and int(r['seed'])==seed]
        _check_run_bindings(matching,fingerprint)
        return graph,truth,{'membership':membership,'normalized_data_sha256':meta['input_sha256'],
                            'original_topology_sha256':topology,'original_graph_fingerprint_sha256':fingerprint,
                            'source_mode':'archived_initial_edges_plus_complete_development_record_map',
                            'dense_scores_available':False,'edge_probabilities_match_archived_fingerprint':True,
                            'reconstruction_caveat':'No historical off-edge score reconstruction or selector-equivalence claim.',
                            'sealed_membership_hashes_only':sealed['holdout']}

    def load(self, *, family, dataset, seed=7, role=None):
        _require(dataset in DOMAINS,'Dataset outside prespecified scope')
        _require(family in ('historical','pilot'),'Unknown asset family')
        _require(isinstance(seed,int) and not isinstance(seed,bool) and seed in SEEDS,'Seed outside prespecified scope')
        if family=='historical':
            _require(role in (None,'development'),'Only exposed development graphs are allowed')
            role='development';graph,truth,provenance=self._old(dataset,seed)
        else:
            _require(seed==7 and role in PILOT_ROLES,'Only the four prespecified exposed pilot graphs are allowed')
            _,old_truth,_=self._old(dataset,7)
            members=self.json(f'{PILOT}/memberships.json','calibration')[dataset]
            saved_role=members['memberships'][role];frozen_role=members['roles'][role]
            nodes=saved_role['record_ids'];_require(set(nodes)<=set(old_truth),'Pilot role outside old permitted development')
            truth={n:old_truth[n] for n in nodes};membership=_check_membership(truth,frozen_role)
            _require(set(truth.values())==set(saved_role['entity_ids']),'Pilot entity mapping disagrees with frozen role')
            folder='completion' if role=='completion_fit' else 'evaluation'
            base=f'{PILOT}/pilot/{dataset}/{folder}_observable_graph'
            archive=self.json(base+'/observable_graph.json','calibration');hashes=self.json(base+'/hashes.json','calibration')
            _require(archive['contains_gold_or_text'] is False,'Observable graph contains disallowed feature data')
            _require(set(archive['nodes'])==set(nodes)==set(archive['record_ids']),'Pilot graph membership differs')
            _require(self.receipts[base+'/observable_graph.json']==hashes['observable_graph.json'],'Pilot graph hash manifest differs')
            # Dense arrays are archived and hash-checked, but not loaded or used
            # by structural diagnostics. This is distinct from edge-only history.
            dense=self.read(base+'/scores.npy','calibration')
            _require(_sha(dense)==hashes['scores.npy'],'Pilot dense array hash manifest differs')
            graph=_make_graph(archive['nodes'],archive['edges'])
            provenance={'membership':membership,'normalized_data_sha256':members['data_sha256'],
                        'original_topology_sha256':graph_fingerprint(graph,probabilities=False),
                        'original_graph_fingerprint_sha256':graph_fingerprint(graph),
                        'source_mode':'exact_archived_observable_graph_with_hash_verified_dense_array',
                        'dense_scores_available':True,'dense_array_loaded_or_used':False,
                        'edge_probabilities_match_archived_fingerprint':True,
                        'sealed_membership_hashes_only':members['sealed_role'],
                        'gold_mapping_source':'permitted old seed7 development record map restricted to frozen pilot membership'}
        provenance.update(family=family,dataset=dataset,seed=seed,role=role,
                          graph_id=f'{family}:{dataset}:{seed}:{role}',nodes=graph.number_of_nodes(),edges=graph.number_of_edges(),
                          refit_performed=False,new_oracle_queries=0,test_records_loaded=False,
                          source_receipts=dict(self.receipts),archive_anchors=dict(self.archive_checks),
                          scientific_scope='offline diagnostic on historically exposed entities; no independent confirmation')
        return graph,truth,provenance


def load_asset(root, *, family, dataset, seed=7, role=None):
    """Return (graph, permitted truth mapping, provenance); see AssetLoader."""
    return AssetLoader(root).load(family=family,dataset=dataset,seed=seed,role=role)


def asset_inventory(root):
    loader=AssetLoader(root);rows=[]
    for family in ('pilot','historical'):
        for dataset in DOMAINS:
            for seed in ((7,) if family=='pilot' else SEEDS):
                for role in (PILOT_ROLES if family=='pilot' else ('development',)):
                    identity={'family':family,'dataset':dataset,'seed':seed,'role':role}
                    try:
                        _,_,provenance=loader.load(**identity)
                        rows.append({**provenance,'status':'available'})
                    except (OSError,ValueError,KeyError,StopIteration) as error:
                        rows.append({**identity,'status':'missing_or_invalid','reason':str(error)})
    return {'schema':'structural-asset-inventory-v1','planned_graphs':10,'available_graphs':sum(r['status']=='available' for r in rows),
            'graphs':rows,'source_receipts':loader.receipts,'archive_anchors':loader.archive_checks,
            'structural_outcomes_computed':False,'refit_performed':False,'new_policy_runs':0,'new_queries':0,
            'missing_policy':'Retain all ten planned rows; missing or invalid assets are never substituted.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--inventory-out',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();out=(root/args.inventory_out).resolve()
    _require(out.is_relative_to(root),'Inventory output escapes workspace')
    result=asset_inventory(root);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'planned_graphs':10,'available_graphs':result['available_graphs'],'out':str(out)}))
    raise SystemExit(0 if result['available_graphs']==10 else 2)


if __name__=='__main__':
    main()
