"""V6 prospective Camera mechanism branch, separate from the failed V5 gate.

No network or work runs on import. The official source must first be inspected.
No legacy gate is called, changed, or patched. Method, pre-fit, and repair freezes
bind the new study. One fixed Camera archive/fit/grid, with no rescue attempts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from scripts.review_v5 import study as s
from scripts.review_v5.external import normalize_archive, PROVIDER, PAPER, EXPECTED
from scripts.review_v5.external import fixed_config as legacy_recipe
from scripts.new_domain.cohort import split_cohort

SESSION = 'outputs/session_20260927_v6'
EXTERNAL = SESSION + '/external'
DATASET = 'alaska_camera'


def fixed_config():
    config = legacy_recipe()
    config.update(schema='cut-audit-v6-alaska-config-v1',
                  purpose='Prospective mechanism validation, not V5 method progression',
                  v5_gate_rewritten=False)
    return config


def planned_slots():
    return [{'id': f'{DATASET}_{m}_B{b}', 'dataset': DATASET, 'method': m,
             'budget': b, 'status': 'not_started'}
            for b in (12, 24, 48) for m in s.NATURAL_METHODS]


def check_method(root=ROOT):
    from scripts.review_v6.freeze import check
    return check(root=Path(root).resolve())


def checked_gate(root=ROOT):
    """Recheck source/tests and audit receipts; no favorable-result requirement."""
    root=Path(root).resolve(); check_method(root)
    gate_path=root/SESSION/'audit_gate.json'; gate=s.read(gate_path)
    s.require(gate.get('schema')=='cut-audit-v6-audit-gate-v1', 'Wrong V6 audit gate')
    s.require(gate.get('method_freeze_sha256')==s.digest(root/SESSION/'freeze.json'),
              'Audit gate method freeze differs')
    pins=gate.get('audit_manifests_sha256', {})
    s.check_hashes(root, pins)
    manifests={}
    for name in pins:
        path=s.relative(root,name); manifest=s.read(path)
        schema=manifest.get('schema')
        s.require(schema not in manifests, 'Duplicate audit scope')
        manifests[schema]=(path,manifest)
        s.require(manifest.get('status') in ('passed','completed_with_unknown'),
                  'Audit manifest is not finalized successfully')
        s.require(type(manifest.get('technical_mismatch_count')) is int
                  and manifest['technical_mismatch_count']==0,
                  'Audit manifest records technical mismatch')
        s.require(not manifest.get('technical_mismatches'),
                  'Audit manifest has mismatch details')
        s.require(manifest.get('planned_states')==301
                  and manifest.get('phase_counts')=={'natural':241,'synthetic':60},
                  'Audit manifest omits declared physical states')
        s.require(manifest.get('completed_states',-1)+manifest.get('unknown_states',-1)==301,
                  'Audit completion accounting differs')
        s.check_hashes(path.parent,manifest.get('files_sha256',{}))
        s.check_hashes(root,manifest.get('code_sha256',{}))
    s.require(set(manifests)=={'cut-audit-v6-visible-suite-v1','cut-audit-v6-evaluator-suite-v1'},
              'Both visible and evaluator audit manifests required')
    visible,_=manifests['cut-audit-v6-visible-suite-v1']
    _,evaluated=manifests['cut-audit-v6-evaluator-suite-v1']
    s.require(evaluated.get('source_manifest_sha256')==s.digest(visible),
              'Evaluator does not bind the visible audit')
    s.require(gate.get('scopes_finalized') is True, 'Declared audit scopes not finalized')
    s.require(type(gate.get('mismatches')) is int and gate['mismatches']==0,
              'Visible audit mismatch blocks external acquisition')
    s.require(type(gate.get('technical_errors')) is int and gate['technical_errors']==0,
              'Visible audit technical error blocks external acquisition')
    s.require(gate.get('eligible') is True, 'V6 correctness gate incomplete')
    return {'method_freeze_sha256':s.digest(root/SESSION/'freeze.json'),
            'audit_gate_sha256':s.digest(gate_path), 'audit_manifests_sha256':pins,
            'timeout_unknown_states':gate.get('timeout_unknown_states',0),
            'v5_progression_gate_not_used':True}


def validate_memberships(root=ROOT):
    """Recompute the outcome-blind allocator; reject overlap or edited roles."""
    root=Path(root).resolve(); out=root/EXTERNAL
    with (out/'normalized/records.csv').open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream)
        s.require(reader.fieldnames==['record_id','entity_id','text'], 'Normalized schema changed')
        rows=list(reader)
    roles,memberships=split_cohort(rows,s.digest(out/'normalized/records.csv'),**fixed_config()['cohort'])
    s.require(memberships==s.read(out/'memberships.json'), 'Whole-entity membership differs')
    for name,values in roles.items():
        s.require(values==s.read(out/'roles'/f'{name}.json'), 'Role records differ: '+name)
    return memberships


def qualify(archive, provenance, *, root=ROOT):
    root=Path(root).resolve(); gate=checked_gate(root); out=root/EXTERNAL
    out.mkdir(parents=True,exist_ok=True)
    s.require(not (out/'final_manifest.json').exists(), 'External branch already closed')
    s.write(out/'qualification_consumed.json',{'created_utc':s.utc(),'archive_sha256':s.digest(archive),
            'one_fixed_archive_only':True,'alternative_category_or_resplit':False})
    report={'schema':'cut-audit-v6-alaska-qualification-v1','status':'blocked','gate':gate,
        'provider':PROVIDER,'paper':PAPER,'archive_sha256':s.digest(archive),
        'raw_redistribution_permitted':False,'formal_test_access':False}
    try:
        supplied=s.read(provenance)
        s.require(supplied.get('provider_url')==PROVIDER and supplied.get('archive_sha256')==s.digest(archive), 'Archive provenance differs')
        s.require(isinstance(supplied.get('download_url'),str) and supplied['download_url'].startswith('https://'), 'Missing inspected provider download URL')
        legal=supplied.get('license_review',{})
        s.require(legal.get('local_research_use_supported') is True and isinstance(legal.get('basis'),str) and legal['basis'].strip(),
                  'Local research-use basis not established')
        exposure=supplied.get('historical_exposure_review',{})
        s.require(exposure.get('previously_used') is False and isinstance(exposure.get('basis'),str) and exposure['basis'].strip(),
                  'Camera historical exposure not resolved')
        normalized,rows,inspection=normalize_archive(archive)
        # Archive notices are substantive; their actual bytes must be inspected,
        # not silently overridden by a repository-level MIT badge.
        notice_pins={x['member']:x['sha256'] for x in inspection['embedded_license_notices']}
        s.require(legal.get('embedded_notices_reviewed_sha256',{})==notice_pins, 'Actual archive license notices need review')
        (out/'normalized').mkdir(); (out/'normalized/records.csv').write_bytes(normalized)
        roles,memberships=split_cohort(rows,hashlib.sha256(normalized).hexdigest(),**fixed_config()['cohort'])
        s.write(out/'memberships.json',memberships); s.write(out/'config.json',fixed_config())
        s.write(out/'source_provenance.json',supplied)
        for role,values in roles.items(): s.write(out/'roles'/f'{role}.json',values)
        validate_memberships(root)
        report.update(inspection=inspection,normalized_sha256=hashlib.sha256(normalized).hexdigest(),
            memberships_sha256=s.digest(out/'memberships.json'),
            reference_semantics='Official paper section3.3 defines complete pair-reference subgraph on annotated records; section4 gives complete target-entity matches; section5 states transitive closure. Unannotated records are excluded, never singleton-labeled.',
            license_scope='Repository MIT covers software/documentation; downloaded raw product-data redistribution is not inferred. Local research basis and archive notices are recorded separately.',
            semantic_domain='Product/camera; not an independent semantic domain relative to WDC')
        for role in ('train','calibration','evaluation'):
            s.require(memberships['roles'][role]['status']=='eligible', 'Fixed role is ineligible: '+role)
        report['status']='qualified'
    except Exception as exc:
        report['reason']=f'{type(exc).__name__}: {exc}'
        s.write(out/'qualification.json',report)
        raise
    s.write(out/'qualification.json',report)
    return report


def make_prefit_freeze(*,root=ROOT):
    root=Path(root).resolve(); gate=checked_gate(root); out=root/EXTERNAL
    s.require(not (out/'final_manifest.json').exists(), 'External branch already closed'); report=s.read(out/'qualification.json'); s.require(report['status']=='qualified','Qualification failed')
    s.require(s.read(out/'config.json')==fixed_config(),'External configuration differs')
    s.require(report['gate']==gate, 'Qualification mechanism gate changed')
    validate_memberships(root)
    names={p.relative_to(root).as_posix() for p in (root/'src/cut_audit_er').glob('*.py')}
    names.update(('scripts/review_v6/external.py','scripts/review_v6/freeze.py','scripts/review_v6/audit.py',
                  'scripts/review_v6/audit_runner.py',
                  'scripts/review_v5/external.py','scripts/review_v5/study.py','scripts/review_v5/analysis.py',
                  'scripts/new_domain/run.py','scripts/new_domain/cohort.py','scripts/review_v4/replay.py',
                  'research/review_v6/PROTOCOL.md','research/review_v6/ALASKA_SOURCE_REVIEW.md',
                  'research/review_v5/PROTOCOL.md','research/review_v5/NUMERIC_BOUND.md','research/review_v5/THEORY.md',
                  'tests/test_review_v6_external.py','tests/test_review_v5_external.py'))
    names.update(name for name in ('scripts/__init__.py','scripts/review_v6/__init__.py','scripts/review_v5/__init__.py',
        'scripts/new_domain/__init__.py','scripts/review_v4/__init__.py') if (root/name).is_file())
    names.update((out/name).relative_to(root).as_posix() for name in ('qualification.json','source_provenance.json','config.json','memberships.json','normalized/records.csv'))
    names.update(p.relative_to(root).as_posix() for p in (out/'roles').glob('*.json'))
    pins={name:s.digest(root/name) for name in sorted(names)}
    snapshot=out/'source_snapshot'; snapshot.mkdir(exist_ok=False)
    for name in names:
        target=snapshot/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(root/name,target)
    s.check_hashes(snapshot,pins)
    frozen={'schema':'cut-audit-v6-alaska-prefit-freeze-v1','created_utc':s.utc(),
        'files_sha256':pins,'snapshot':snapshot.relative_to(root).as_posix(),'gate':gate,
        'method_freeze_sha256':s.digest(root/SESSION/'freeze.json'),'config':fixed_config(),
        'slots':planned_slots(),'formal_test_access':False,'human_approval_record_created':False,
        'authorization_scope':'User-authorized V6 mechanism study; V5 progression gate remains failed; no submission, raw redistribution or held-out test approval'}
    s.write(out/'prefit_freeze.json',frozen); return frozen


def check_prefit(root=ROOT):
    root=Path(root).resolve(); out=root/EXTERNAL; frozen=s.read(out/'prefit_freeze.json')
    s.require(not (out/'final_manifest.json').exists(), 'External branch already closed')
    s.require(frozen['schema']=='cut-audit-v6-alaska-prefit-freeze-v1' and frozen['config']==fixed_config()
              and frozen['slots']==planned_slots(),'Wrong external pre-fit freeze')
    s.require(s.digest(root/SESSION/'freeze.json')==frozen['method_freeze_sha256'],'V6 method freeze changed')
    s.check_hashes(root,frozen['files_sha256']); s.check_hashes(s.relative(root,frozen['snapshot']),frozen['files_sha256'])
    s.require(checked_gate(root)==frozen['gate'], 'Frozen mechanism gate changed')
    return frozen


def prepare(*,root=ROOT):
    """Consume one fit attempt; save the complete evaluation graph, then freeze."""
    from scripts.new_domain.run import bounded_stage
    from scripts.review_v4.replay import observable
    import numpy as np
    root=Path(root).resolve(); out=root/EXTERNAL; check_prefit(root)
    s.require(all(os.environ.get(k)==v for k,v in s.ENV.items()),'Pin CPU/hash environment before startup')
    s.write(out/'preparation_consumed.json',{'created_utc':s.utc(),'prefit_sha256':s.digest(out/'prefit_freeze.json'),
            'fit_attempts_allowed':1,'graph_attempts_allowed':1,'retries_allowed':False})
    cfg=fixed_config(); start=time.perf_counter(); stages={}
    report={'status':'failed','stages':stages,'formal_test_access':False,'completion_role_used':False}
    try:
        def stage(name,args):
            check_prefit(root); result=bounded_stage(name,args,cfg['stage_seconds'][name])
            stages[name]={k:v for k,v in result.items() if k!='value'}
            s.write(out/'preparation_stages'/f'{name}.json',stages[name]); check_prefit(root)
            s.require(result['status']=='completed','Preparation stage did not complete: '+name)
            return result['value']
        train=s.read(out/'roles/train.json'); calibration=s.read(out/'roles/calibration.json')
        matcher=stage('matcher',(train,calibration,cfg['matcher']))
        s.write(out/'matcher'/'diagnostics.json',{'settings':cfg['matcher'],'fit_diagnostics':matcher.fit_diagnostics,
            'classifier_coefficients':matcher.model.coef_.tolist(),'classifier_intercept':matcher.model.intercept_.tolist(),
            'platt_coefficients':matcher.calibrator.coef_.tolist(),'platt_intercept':matcher.calibrator.intercept_.tolist(),
            'vocabulary_sha256':hashlib.sha256(s.blob({k:int(v) for k,v in matcher.vectorizer.vocabulary_.items()})).hexdigest(),
            'vocabulary_included':False,'python':platform.python_version()})
        records=s.read(out/'roles/evaluation.json')
        graph,scores,diagnostics=stage('graph',(matcher,records,cfg['threshold'],cfg['top_k']))
        folder=out/'graph'; folder.mkdir(exist_ok=False)
        s.require(list(scores.ids)==[r['record_id'] for r in records] and set(graph)==set(scores.ids),'Evaluation membership changed')
        s.write(folder/'observable.json',observable(graph,scores)); np.save(folder/'scores.npy',scores.matrix,allow_pickle=False)
        s.write(folder/'evaluator_reference.json',{'reference':{r['record_id']:r['entity_id'] for r in records}})
        s.write(folder/'diagnostics.json',diagnostics)
        report.update(status='completed',evaluation_nodes=len(graph),evaluation_edges=graph.number_of_edges(),
                      graph_files_sha256={p.name:s.digest(p) for p in sorted(folder.iterdir())})
    except Exception as exc:
        report['reason']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report['wall_seconds']=time.perf_counter()-start; s.write(out/'preparation.json',report)
    frozen={'schema':'cut-audit-v6-alaska-repair-freeze-v1','created_utc':s.utc(),
        'prefit_sha256':s.digest(out/'prefit_freeze.json'),'preparation_sha256':s.digest(out/'preparation.json'),
        'graph_files_sha256':report['graph_files_sha256'],'slots':planned_slots(),
        'note':'Frozen before repair outcomes; one fixed evaluation graph including isolates', 'formal_test_access':False}
    s.write(out/'repair_freeze.json',frozen); return report


def check_repair(root=ROOT):
    root=Path(root).resolve(); out=root/EXTERNAL; check_prefit(root)
    frozen=s.read(out/'repair_freeze.json')
    s.require(frozen['schema']=='cut-audit-v6-alaska-repair-freeze-v1' and frozen['slots']==planned_slots(), 'Wrong repair freeze')
    s.require(frozen['prefit_sha256']==s.digest(out/'prefit_freeze.json') and frozen['preparation_sha256']==s.digest(out/'preparation.json'),
              'External preparation changed')
    s.check_hashes(out/'graph',frozen['graph_files_sha256']); return frozen


def run(*,root=ROOT,continue_run=False,absence_receipt=None):
    from scripts.review_v4.replay import graph_from_observable
    import numpy as np
    root=Path(root).resolve(); out=root/EXTERNAL; check_repair(root)
    s.require(all(os.environ.get(k)==v for k,v in s.ENV.items()),'Pin CPU/hash environment before startup')
    graph,scores=graph_from_observable(s.read(out/'graph/observable.json'),np.load(out/'graph/scores.npy',allow_pickle=False))
    truth=s.read(out/'graph/evaluator_reference.json')['reference']
    s.require(set(truth)==set(graph), 'External evaluator membership differs')
    return s.execute_grid(out/'study','natural',planned_slots(),{DATASET:(graph,scores,truth)},
        s.digest(out/'repair_freeze.json'),continue_run=continue_run,absence_receipt=absence_receipt,
        before_cell=lambda:check_repair(root))


def record_blocked(provider_receipt, *, root=ROOT):
    """Close a never-acquired branch without inventing a passed audit gate."""
    root=Path(root).resolve(); check_method(root); out=root/EXTERNAL
    receipt=Path(provider_receipt).resolve()
    s.require(receipt.is_relative_to(root), 'Provider receipt outside workspace')
    source=s.read(receipt)
    s.require(source.get('schema')=='cut-audit-v6-provider-transport-review-v1'
              and source.get('status')=='blocked_expired_official_share'
              and source.get('provider_url')==PROVIDER
              and source.get('expired_share_message_found') is True
              and source.get('archive_downloaded') is False,
              'Provider receipt does not demonstrate the fixed acquisition block')
    s.require(not any((out/name).exists() for name in
              ('qualification_consumed.json','preparation_consumed.json','study','graph')),
              'Cannot mark acquired or attempted study never started')
    rows=[{**slot,'status':'not_started_download_blocked',
           'reason':'Official Camera sharing link expired; no alternate source/category/cohort',
           'loss':None,'fp':None,'fn':None,'paid_queries':None} for slot in planned_slots()]
    result={'schema':'cut-audit-v6-external-final-v1','created_utc':s.utc(),
            'status':'blocked_download','scope':'Prospective V6 mechanism branch',
            'method_freeze_sha256':s.digest(root/SESSION/'freeze.json'),
            'provider_receipt':receipt.relative_to(root).as_posix(),
            'provider_receipt_sha256':s.digest(receipt),
            'planned_slots':21,'acquisitions_started':0,'acquisitions_completed':0,
            'archive_downloads':0,'new_model_fits':0,'paid_queries':0,
            'audit_gate_claimed_passed':False,'v5_progression_gate_changed':False,
            'sealed_test_access':False,'alternative_benchmark_used':False,'runs':rows}
    s.write(out/'final_manifest.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('inspect','qualify','freeze','prepare','run','continue','blocked'))
    parser.add_argument('--archive',type=Path); parser.add_argument('--provenance',type=Path)
    parser.add_argument('--provider-receipt',type=Path)
    parser.add_argument('--absence-receipt',type=Path); parser.add_argument('--receipt',type=Path)
    args=parser.parse_args()
    if args.action=='inspect':
        s.require(args.archive is not None,'Archive path required'); checked_gate()
        _,_,report=normalize_archive(args.archive)
    elif args.action=='qualify':
        s.require(args.archive is not None and args.provenance is not None,'Archive/provenance required')
        report=qualify(args.archive,args.provenance)
    elif args.action=='freeze': report=make_prefit_freeze()
    elif args.action=='prepare': report=prepare()
    elif args.action=='blocked':
        s.require(args.provider_receipt is not None,'Provider transport receipt required')
        report=record_blocked(args.provider_receipt)
    else: report=run(continue_run=args.action=='continue',absence_receipt=args.absence_receipt)
    if args.receipt: s.write(args.receipt,report)
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__': main()
