"""One frozen intact-cohort study; no new selector or calibration recipe.

All source/data checks precede fitting. Stage workers and repair workers have
finite result deadlines; synchronous startup/IPC retain documented OS limits.
No timeout prefix is promoted to a completed outcome.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
from importlib.metadata import version
import json
import multiprocessing as mp
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import time
import traceback
import warnings

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.new_domain.cohort import split_cohort
from cut_audit_er.natural import bounded_audit

METHODS = ('error_weighted_edge_betweenness', 'cut_plan_fixed',
           'cut_plan_edge_calibrated', 'cut_plan_completion_calibrated')
BUDGETS = (12, 24, 48)
MODEL_KEYS = {'cut_plan_edge_calibrated': 'edge', 'cut_plan_completion_calibrated': 'plan'}
PROTOCOL = 'research/structural_20260922/PROSPECTIVE_PROTOCOL.md'
EXECUTABLE_PROTOCOL = 'research/new_domain_20260923/EXECUTABLE_PROTOCOL.md'
STAGE_LIMITS = {'ingestion': 120, 'matcher_fit': 900, 'graph': 600,
                'collection': 600, 'calibrator_fit': 120, 'diagnostics': 300}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def write(path, value, *, checkpoint=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint:
        temporary = path.with_suffix(path.suffix+'.tmp')
        temporary.write_bytes(json_bytes(value)); temporary.replace(path)
    else:
        with path.open('xb') as stream: stream.write(json_bytes(value))


def contained(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative or
        PurePosixPath(relative).is_absolute() or any(x in ('', '.', '..') for x in relative.split('/'))):
        raise ValueError('Unsafe frozen relative path')
    path = (root/relative).resolve()
    if not path.is_relative_to(root): raise ValueError('Frozen path escapes workspace')
    return path


def check_freeze(root, files):
    if not isinstance(files, dict) or not files: raise ValueError('Empty source/input freeze')
    for relative, expected in files.items():
        path = contained(root, relative)
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Freeze mismatch: '+relative)


def validate_config(cfg):
    expected = {'schema': 'cut-audit-new-domain-study-v1', 'phase': 'exploratory_development',
        'cohort': {'seed': 20260919, 'record_cap': 4000, 'graph_cap': 1500},
        'matcher': {'seed': 7, 'max_pairs': 50000, 'variant': 'char4'},
        'threshold': .6, 'top_k': 10, 'methods': list(METHODS), 'budgets': list(BUDGETS),
        'reference_budget': 24, 'worker_seconds': 30, 'outer_seconds': 1800,
        'stage_seconds': STAGE_LIMITS, 'lambda': 1, 'noise': 0,
        'max_plan_depth': 4, 'candidate_cap': 64, 'cpu_threads': 1, 'python_hash_seed': '0'}
    for field, value in expected.items():
        if json_bytes(cfg.get(field)) != json_bytes(value): raise ValueError('Fixed study configuration differs: '+field)
    return cfg


def validate_inputs(root, config, normalized, source_receipt, freeze_path):
    root = Path(root).resolve()
    paths = [Path(p).resolve() for p in (config, normalized, source_receipt, freeze_path)]
    if any(not p.is_relative_to(root) for p in paths): raise ValueError('Inputs must remain inside workspace')
    config, normalized, source_receipt, freeze_path = paths
    cfg = validate_config(json.loads(config.read_text(encoding='utf-8')))
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    files = freeze['files_sha256']; check_freeze(root, files)
    required = {config.relative_to(root).as_posix(), normalized.relative_to(root).as_posix(),
        source_receipt.relative_to(root).as_posix(), PROTOCOL, EXECUTABLE_PROTOCOL,
        'scripts/calibration_pilot/run.py', 'scripts/calibration_pilot/prepare.py',
        'scripts/structural_revision/events.py'}
    for directory in ('src', 'scripts/new_domain'):
        required.update(p.relative_to(root).as_posix() for p in (root/directory).rglob('*.py') if '__pycache__' not in p.parts)
    required.update(p.relative_to(root).as_posix() for pattern in ('test_new_domain*.py', 'test_wdc_adapter*.py')
                    for p in (root/'tests').glob(pattern))
    if not required <= set(files): raise ValueError('Source/config/methodology freeze omits dependencies: '+str(sorted(required-set(files))))
    if contained(root, cfg['normalized_csv']) != normalized or contained(root, cfg['source_receipt']) != source_receipt:
        raise ValueError('CLI input paths differ from frozen config')
    receipt = json.loads(source_receipt.read_text(encoding='utf-8'))
    archive = contained(root, cfg['source_archive'])
    if (digest(archive) != cfg['archive_sha256'] or receipt['archive_sha256'] != cfg['archive_sha256'] or
        digest(normalized) != cfg['normalized_sha256'] or receipt['normalized_sha256'] != cfg['normalized_sha256']):
        raise ValueError('Source archive or normalized hash mismatch')
    if (receipt.get('schema') != 'wdc-multiclass-source-normalization-v1' or
        receipt['selected_source_members'] != cfg['source_members'] or
        receipt.get('record_id_cluster_mapping_conflicts') != 0 or receipt.get('unseen_true_rows') != 0 or
        receipt.get('text_fields') != ['title', 'brand', 'description']):
        raise ValueError('Source schema/variant contract mismatch')
    return cfg, freeze, receipt


def _pilot_helpers():
    """Load only audited functions; the historical script's main is never run."""
    folder = ROOT/'scripts/calibration_pilot'
    spec = importlib.util.spec_from_file_location('_new_domain_old_prepare', folder/'prepare.py')
    prepare = importlib.util.module_from_spec(spec); spec.loader.exec_module(prepare)
    old = sys.modules.get('prepare')
    sys.modules['prepare'] = prepare
    try:
        spec = importlib.util.spec_from_file_location('_new_domain_old_helpers', folder/'run.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    finally:
        if old is None: sys.modules.pop('prepare', None)
        else: sys.modules['prepare'] = old
    return module


class StageFailure(Exception):
    def __init__(self, message, details):
        super().__init__(message); self.details = details


def stage_ingestion(path, expected_hash, settings):
    if digest(path) != expected_hash: raise ValueError('Normalized input changed before ingestion')
    with Path(path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['record_id', 'entity_id', 'text']: raise ValueError('Unexpected normalized CSV columns')
        records = list(reader)
    return split_cohort(records, expected_hash, **settings)


def stage_matcher(train, calibration, settings):
    import pandas as pd
    from cut_audit_er.matcher import PairMatcher
    matcher = PairMatcher(settings['seed'], settings['max_pairs'], settings['variant'])
    try:
        matcher.fit(pd.DataFrame(train), pd.DataFrame(calibration))
    except Exception as exc:
        raise StageFailure(str(exc), {'sample_diagnostics': matcher.sample_diagnostics}) from exc
    return matcher


def stage_graph(matcher, rows, threshold, top_k):
    import pandas as pd
    return matcher.graph_for(pd.DataFrame(rows), threshold, top_k)


def stage_collect(graph, scores, run, truth):
    return _pilot_helpers().collect_candidates(graph, scores, run, truth)


def stage_calibrator(kind, candidates):
    from cut_audit_er.completion_calibration import fit_edge_calibrator, fit_plan_calibrator
    if kind == 'edge':
        rows = candidates['edges']
        return fit_edge_calibrator([r['negative_probability'] for r in rows], [r['outcome'] for r in rows]).to_dict()
    if kind != 'plan': raise ValueError('No additional calibrator permitted')
    rows = [r for r in candidates['plans'] if r['paid_constraints']['logical_all_negative_probability'] is None]
    return fit_plan_calibrator([r['raw_q'] for r in rows], [r['depth'] for r in rows], [r['outcome'] for r in rows]).to_dict()


def stage_probability(candidates, models):
    from cut_audit_er.completion_calibration import LogisticCalibrationModel
    return _pilot_helpers().probability_summary(candidates['plans'], {k: LogisticCalibrationModel.from_dict(v) for k, v in models.items()})


def stage_structure(graph, truth):
    from cut_audit_er.offline_structure import structural_diagnostics
    return structural_diagnostics(graph, truth, perfect_oracle=True)


def stage_events(graph, truth, run):
    from scripts.structural_revision.events import replay_paid_trace
    return replay_paid_trace(graph, truth, run['decisions'], run['trace'], run['requested_budget'])


def _stage_worker(connection, name, args):
    try:
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter('always')
            value = globals()['stage_'+name](*args)
        connection.send({'status': 'completed', 'value': value, 'warnings': [str(w.message) for w in recorded]})
    except Exception as exc:
        connection.send({'status': 'failed', 'error': traceback.format_exc(), 'details': getattr(exc, 'details', {})})
    finally: connection.close()


def bounded_stage(name, args, seconds):
    """Finite requested result deadline; measured synchronous start/receive caveat."""
    context = mp.get_context('spawn'); receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_stage_worker, args=(send, name, args))
    start = time.perf_counter(); started = False
    result = {'status': 'failed', 'error': 'Stage worker not started'}
    phases = {}
    try:
        process.start(); started = True; send.close()
        phases['process_start_seconds'] = time.perf_counter()-start
        waiting = time.perf_counter()
        ready = receive.poll(max(0., seconds-(waiting-start)))
        phases['result_wait_seconds'] = time.perf_counter()-waiting
        if ready:
            t = time.perf_counter(); result = receive.recv()
            phases['payload_receive_seconds'] = time.perf_counter()-t
        else: result = {'status': 'timeout', 'error': 'Stage result deadline expired; no complete artifact'}
    except Exception: result = {'status': 'failed', 'error': traceback.format_exc()}
    finally:
        t = time.perf_counter(); send.close()
        if started:
            if result['status'] == 'completed': process.join(timeout=1)
            if process.is_alive(): process.terminate(); process.join(timeout=1)
            if process.is_alive(): process.kill(); process.join(timeout=1)
        alive = started and process.is_alive(); receive.close()
        phases['cleanup_seconds'] = time.perf_counter()-t
    if alive: result = {'status': 'cleanup_failed', 'error': 'Stage worker remains alive after bounded cleanup'}
    elapsed = time.perf_counter()-start
    return {**result, 'worker_wall_seconds': elapsed, 'worker_timing': phases,
        'worker_exit_code': process.exitcode if started else None, 'requested_result_deadline_seconds': seconds,
        'observed_wall_exceeded_requested_deadline': elapsed > seconds,
        'deadline_scope': 'Startup/IPC synchronous; result wait and cleanup joins bounded; no strict OS wall guarantee'}


def planned_cells():
    return [{'method': method, 'budget': budget, 'status': 'not_attempted', 'reason': 'prerequisites_pending'}
            for budget in BUDGETS for method in METHODS]


def archive_graph(folder, graph, scores):
    import numpy as np
    folder.mkdir(parents=True, exist_ok=False)
    np.save(folder/'scores.npy', scores.matrix, allow_pickle=False)
    write(folder/'observable_graph.json', {'record_ids': list(scores.ids), 'nodes': list(graph.nodes),
        'edges': [[u, v, float(a['p'])] for u, v, a in graph.edges(data=True)], 'contains_gold_or_text': False})
    result = {p.name: digest(p) for p in folder.iterdir() if p.is_file()}
    write(folder/'hashes.json', result)
    return result


def run_study(root, config, normalized, source_receipt, freeze_path, out, *, input_validator=None):
    """Reuse the fixed study engine with an explicit source-contract validator.

    The default preserves the original WDC validation. A later, separately
    frozen development source can supply its own strict provenance validator;
    this does not change any sealed-test or human-approval validation.
    """
    root = Path(root).resolve(); out = Path(out).resolve()
    if not out.is_relative_to(root): raise ValueError('Output must stay inside workspace')
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    ledger = {'schema': 'cut-audit-new-domain-results-v1', 'status': 'running',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'runs': planned_cells(), 'stages': {},
        'completion_reference': {'status': 'not_attempted', 'budget': 24, 'method': 'cut_plan_fixed'},
        'formal_test_scoring': False, 'evaluation_cohorts': 1,
        'baseline_alias': {'error_weighted_edge_betweenness': 'edge_betweenness'}}
    def checkpoint():
        ledger['elapsed_seconds'] = time.perf_counter()-started
        write(out/'suite.json', ledger, checkpoint=True)
    checkpoint()
    try:
        if os.environ.get('PYTHONHASHSEED') != '0' or any(os.environ.get(n) != '1' for n in
                ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')):
            raise ValueError('Launch with run_logged.py: require startup PYTHONHASHSEED=0 and CPU thread limits=1')
        validator = validate_inputs if input_validator is None else input_validator
        cfg, freeze, receipt = validator(root, config, normalized, source_receipt, freeze_path)
        files = freeze['files_sha256']
        ledger.update(config_sha256=digest(config), source_receipt_sha256=digest(source_receipt),
            scientific_freeze_sha256=digest(freeze_path), normalized_sha256=cfg['normalized_sha256'],
            source_archive_sha256=cfg['archive_sha256'], reference_caveat=receipt.get('reference_caveat'))
        source_files = {n: h for n, h in files.items() if n.endswith('.py')}
        for name, expected in source_files.items():
            target = out/'source_snapshot'/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(contained(root, name), target)
            if digest(target) != expected: raise ValueError('Execution source copy mismatch')
        write(out/'execution_source_freeze.json', {'files_sha256': source_files,
            'scientific_freeze_sha256': digest(freeze_path), 'python': platform.python_version(),
            'libraries': {name: version(name) for name in ('numpy', 'pandas', 'scikit-learn', 'scipy', 'networkx')},
            'python_hash_seed': os.environ['PYTHONHASHSEED'], 'cpu_threads': 1})

        repair_started = None
        def remaining():
            return cfg['outer_seconds'] if repair_started is None else cfg['outer_seconds']-(time.perf_counter()-repair_started)
        def stage(label, function, args, limit):
            check_freeze(root, files)
            result = bounded_stage(function, args, cfg['stage_seconds'][limit])
            metadata = {k: v for k, v in result.items() if k != 'value'}
            ledger['stages'][label] = metadata; write(out/'stages'/f'{label}.json', metadata)
            check_freeze(root, files); checkpoint()
            return result

        ingested = stage('ingestion', 'ingestion', (str(normalized), cfg['normalized_sha256'], cfg['cohort']), 'ingestion')
        if ingested['status'] != 'completed': raise RuntimeError('Ingestion failed; see stage receipt')
        roles, memberships = ingested['value']; write(out/'memberships.json', memberships)
        if memberships['input_records'] != receipt['distinct_records']:
            raise ValueError('Normalized record count differs from inspected source receipt')
        ledger['memberships_sha256'] = digest(out/'memberships.json'); checkpoint()
        if any(memberships['roles'][r]['status'] != 'eligible' for r in ('train', 'calibration')):
            raise RuntimeError('Empty matcher role; no redraw or sample rescue')
        fitted = stage('matcher_fit', 'matcher', (roles['train'], roles['calibration'], cfg['matcher']), 'matcher_fit')
        if fitted['status'] != 'completed': raise RuntimeError('Matcher fitting unavailable; no graph substitutes')
        matcher = fitted['value']; ledger['matcher_fit'] = matcher.fit_diagnostics
        write(out/'matcher.json', {'settings': cfg['matcher'], 'fit_diagnostics': matcher.fit_diagnostics,
            'classifier_coefficients': matcher.model.coef_.tolist(), 'classifier_intercept': matcher.model.intercept_.tolist(),
            'platt_coefficients': matcher.calibrator.coef_.tolist(), 'platt_intercept': matcher.calibrator.intercept_.tolist(),
            'vocabulary_sha256': hashlib.sha256(json_bytes({k: int(v) for k, v in matcher.vectorizer.vocabulary_.items()})).hexdigest(),
            'vocabulary_included': False})
        graphs = {}
        for role in ('completion_fit', 'evaluation'):
            eligibility = memberships['roles'][role]['status']
            if eligibility != 'eligible':
                ledger[role+'_graph'] = {'status': eligibility}; checkpoint(); continue
            result = stage(role+'_graph', 'graph', (matcher, roles[role], cfg['threshold'], cfg['top_k']), 'graph')
            ledger[role+'_graph'] = {k: v for k, v in result.items() if k != 'value'}
            if result['status'] == 'completed':
                graph, scores, diagnostics = result['value']
                hashes = archive_graph(out/(role+'_observable_graph'), graph, scores)
                truth = {r['record_id']: r['entity_id'] for r in roles[role]}
                graphs[role] = (graph, scores, truth, hashes)
                ledger[role+'_graph'].update(diagnostics=diagnostics, hashes=hashes)
            checkpoint()

        def repair(role, method, budget, model=None):
            nonlocal repair_started
            check_freeze(root, files)
            if repair_started is None: repair_started = time.perf_counter()
            if remaining() <= 0: return {'status': 'outer_limit', 'error': 'Fixed suite limit reached before policy launch'}
            graph, scores, truth, hashes = graphs[role]
            actual = 'edge_betweenness' if method == 'error_weighted_edge_betweenness' else method
            identity = {'role': role, 'method': actual, 'requested_budget': budget,
                'graph_sha256': hashes['observable_graph.json'], 'scores_sha256': hashes['scores.npy'],
                'model_sha256': hashlib.sha256(json_bytes(model)).hexdigest() if model else None,
                'normalized_sha256': cfg['normalized_sha256']}
            arguments = dict(g=graph, scores=scores, truth=truth, method=actual, budget=budget,
                             seed=7, noise=0., fn_weight=1.)
            if model is not None: arguments['completion_model'] = model
            result = bounded_audit(arguments, min(cfg['worker_seconds'], remaining()),
                journal_path=out/'journals'/f'{role}_{method}_B{budget}.jsonl', journal_identity=identity)
            result.update(label=method, role=role, requested_budget=budget, identity=identity)
            if result['status'] == 'completed' and not result.get('run', {}).get('complete'):
                result['status'] = 'incomplete'
            check_freeze(root, files)
            return result

        models = {}; candidates = None
        if 'completion_fit' in graphs:
            reference = repair('completion_fit', 'cut_plan_fixed', 24)
            write(out/'completion_reference.json', reference)
            ledger['completion_reference'] = {k: v for k, v in reference.items() if k != 'run'}
            if reference['status'] == 'completed':
                ledger['completion_reference']['spent'] = reference['run']['spent']
            ledger['completion_reference']['path'] = 'completion_reference.json'; checkpoint()
            if reference['status'] == 'completed':
                graph, scores, truth, _ = graphs['completion_fit']
                collected = stage('fitting_collection', 'collect', (graph, scores, reference['run'], truth), 'collection')
                if collected['status'] == 'completed':
                    candidates = collected['value']; write(out/'fit_candidates.json', candidates)
                    unresolved = [r for r in candidates['plans'] if r['paid_constraints']['logical_all_negative_probability'] is None]
                    ledger['completion_supervision'] = {**candidates['accounting'],
                        'fitting_plans': len(unresolved), 'fitting_positive_plans': sum(r['outcome'] for r in unresolved),
                        'forced_plans_excluded_from_fitting': len(candidates['plans'])-len(unresolved),
                        'additional_unique_offline_pair_labels': candidates['accounting']['unique_candidate_label_pairs']-
                            candidates['accounting']['candidate_reference_label_overlap']}
                    for kind in ('edge', 'plan'):
                        result = stage(kind+'_calibrator', 'calibrator', (kind, candidates), 'calibrator_fit')
                        if result['status'] == 'completed': models[kind] = result['value']
        else:
            ledger['completion_reference'].update(status='unavailable', reason='completion_fit_graph_unavailable')
        write(out/'models.json', {'frozen_before_evaluation_utc': datetime.now(timezone.utc).isoformat(),
            'models': models, 'supervision': ledger.get('completion_supervision'), 'c0_included': False})
        model_digest = digest(out/'models.json'); ledger['models_sha256'] = model_digest; checkpoint()

        for cell in ledger['runs']:
            method, budget = cell['method'], cell['budget']
            if 'evaluation' not in graphs:
                cell.update(status='unavailable', reason='evaluation_graph_unavailable'); checkpoint(); continue
            kind = MODEL_KEYS.get(method)
            if kind and kind not in models:
                cell.update(status='unavailable', reason='required_calibration_model_unavailable'); checkpoint(); continue
            if digest(out/'models.json') != model_digest: raise ValueError('Frozen calibration artifact changed')
            result = repair('evaluation', method, budget, models.get(kind))
            path = out/'runs'/f'{method}_B{budget}.json'; write(path, result)
            cell.update(status=result['status'], path=path.relative_to(out).as_posix(), sha256=digest(path),
                        reason=None if result['status']=='completed' else result.get('error', 'No complete outcome'))
            checkpoint()

        # All acquisition slots are attempted before offline diagnostic work.
        ledger['repair_reference_ledger_seconds'] = None if repair_started is None else time.perf_counter()-repair_started
        ledger['outer_limit_scope'] = 'First repair/reference launch through last repair slot, including intervening calibration; other stages have separate fixed limits'
        if 'evaluation' in graphs:
            graph, scores, truth, _ = graphs['evaluation']
            result = stage('evaluation_structure', 'structure', (graph, truth), 'diagnostics')
            if result['status'] == 'completed': write(out/'evaluation_structure.json', result['value'])
            for cell in ledger['runs']:
                if cell['status'] != 'completed': continue
                run = json.loads((out/cell['path']).read_text(encoding='utf-8'))['run']
                label = f"events_{cell['method']}_B{cell['budget']}"
                result = stage(label, 'events', (graph, truth, run), 'diagnostics')
                if result['status'] == 'completed': write(out/'events'/f'{label}.json', result['value'])
            reference = next(r for r in ledger['runs'] if r['method']=='cut_plan_fixed' and r['budget']==24)
            if reference['status'] == 'completed':
                run = json.loads((out/reference['path']).read_text(encoding='utf-8'))['run']
                result = stage('evaluation_collection', 'collect', (graph, scores, run, truth), 'collection')
                if result['status'] == 'completed':
                    evaluation_candidates = result['value']
                    write(out/'evaluation_candidates.json', evaluation_candidates)
                    ledger['evaluation_only_supervision'] = evaluation_candidates['accounting']
                    result = stage('probability_diagnostics', 'probability', (evaluation_candidates, models), 'diagnostics')
                    if result['status'] == 'completed':
                        summary, enriched = result['value']
                        write(out/'probability_metrics.json', summary); write(out/'evaluation_predictions.json', enriched)
            else: ledger['probability_diagnostics'] = {'status': 'unavailable', 'reason': 'Complete evaluation raw B24 required'}
        check_freeze(root, files)
        ledger['status'] = ('completed' if all(r['status']=='completed' for r in ledger['runs']) and
            ledger['completion_reference']['status']=='completed' and all(s['status']=='completed' for s in ledger['stages'].values())
            else 'finished_with_failures')
    except Exception:
        ledger['status'] = 'failed'; ledger['error'] = traceback.format_exc()
    for cell in ledger['runs']:
        if cell['status'] == 'not_attempted': cell['reason'] = 'prior_prerequisite_or_freeze_failure'
    ledger['finished_utc'] = datetime.now(timezone.utc).isoformat(); checkpoint()
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'normalized', 'source-receipt', 'freeze', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = run_study(ROOT, args.config, args.normalized, args.source_receipt, args.freeze, args.out)
    print(json.dumps({'status': result['status'], 'cases': len(result['runs']),
        'completed': sum(r['status']=='completed' for r in result['runs']), 'elapsed_seconds': result['elapsed_seconds']}))
    raise SystemExit(0 if result['status']=='completed' else 2)


if __name__ == '__main__': main()
