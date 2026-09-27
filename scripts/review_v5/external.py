"""One qualified ALASKA Camera branch, with independent pre-fit/repair freezes.

No network operation is implemented here. Root must first inspect the official
provider, pass the completed development gate, and acquire the single archive.
Only annotated titles are normalized. No category switch, role redraw, rescue
fit or repeated repair slot is permitted. Raw data are not public deliverables.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from scripts.review_v5 import study as s
from scripts.new_domain.cohort import split_cohort

PROVIDER = 'https://github.com/merialdo/research.alaska'
PAPER = 'https://arxiv.org/html/2101.11259v2'
DATASET = 'alaska_camera'
EXTERNAL = s.SESSION + '/external'
EXPECTED = {'labeled_records': 3865, 'entities': 103, 'records': 29787, 'sources': 24}


def fixed_config():
    return {'schema': 'cut-audit-v5-alaska-config-v1', 'dataset': DATASET,
        'provider': PROVIDER, 'paper': PAPER, 'provider_expected': EXPECTED,
        'text_field': '<page title>', 'title_normalization': 'Preserve exact nonempty Unicode title; no coercion or trimming',
        'normalized_csv': 'UTF-8 without BOM, LF, csv minimal quoting; record_id/entity_id/text; exact ID UTF-8 sort',
        'cohort': {'seed': 20260919, 'record_cap': 4000, 'graph_cap': 1500},
        'matcher': {'seed': 7, 'max_pairs': 50000, 'variant': 'char4'},
        'threshold': .6, 'top_k': 10, 'completion_role_used': False,
        'stage_seconds': {'matcher': 900, 'graph': 600},
        'methods': list(s.NATURAL_METHODS), 'budgets': [12,24,48],
        'worker_seconds': 120, 'suite_seconds': 2700, 'cpu_threads': 1,
        'formal_test_access': False, 'raw_redistribution_permitted': False}


def planned_slots():
    return [{'id': f'{DATASET}_{m}_B{b}', 'dataset': DATASET, 'method': m,
             'budget': b, 'status': 'not_started'} for b in (12,24,48) for m in s.NATURAL_METHODS]


def checked_gate(root=ROOT):
    """Bind a passed gate to the complete fixed development matrix and analysis."""
    from scripts.review_v5.analysis import external_gate
    root = Path(root).resolve(); s.checked_freeze(root)
    folder = root / s.SESSION / 'natural'; study = folder / 'study'; analysis = folder / 'analysis'
    suite = s.read(study/'suite.json'); declared = s.slots('natural')
    s.require(suite.get('status') in ('completed','completed_with_missing') and suite['slots']==declared,
              'Complete fixed development matrix required before ALASKA branch')
    rows, elapsed, pending = s.ledger_state(study, declared)
    s.require(pending is None and rows==suite['runs'] and elapsed==suite['active_elapsed_seconds'], 'Development ledger differs')
    s.check_hashes(study/'ledger', suite['ledger_files_sha256'])
    manifest = s.read(analysis/'manifest.json')
    s.require(manifest.get('status')=='passed' and manifest.get('phase')=='natural', 'Development analysis incomplete')
    s.check_hashes(analysis, manifest['files_sha256'])
    sources = s.read(analysis/'sources.json'); s.check_hashes(study, sources['study_files_sha256'])
    s.require(sources['freeze_sha256']==s.digest(root/s.SESSION/'freeze.json'), 'Development analysis freeze differs')
    with (analysis/'endpoints.csv').open(encoding='utf-8', newline='') as stream:
        endpoints = list(csv.DictReader(stream))
    s.require(len(endpoints)==63, 'Development endpoint grid truncated')
    for row in endpoints:
        row['budget']=int(row['budget'])
        if row['status']=='completed': row['loss']=float(row['loss'])
    gate = external_gate(endpoints)
    s.require(gate==s.read(analysis/'external_gate.json') and gate['eligible'], 'External development gate did not pass')
    return {'gate': gate, 'natural_suite_sha256': s.digest(study/'suite.json'),
            'analysis_manifest_sha256': s.digest(analysis/'manifest.json'),
            'gate_sha256': s.digest(analysis/'external_gate.json')}


def member_name(name):
    s.require(isinstance(name,str) and name and not name.startswith('/') and '\\' not in name and ':' not in name,
              'Unsafe archive member')
    name = name.rstrip('/')
    s.require(name and all(p not in ('','.','..') for p in name.split('/')), 'Unsafe archive member')
    return name


class Archive:
    """Read archive members only; never extract or execute supplied content."""
    def __init__(self, path):
        self.path=Path(path); self.files={}; self.total=0
        if zipfile.is_zipfile(path):
            self.archive=zipfile.ZipFile(path); self.kind='zip'
            for entry in self.archive.infolist():
                name=member_name(entry.filename)
                s.require(not stat.S_ISLNK(entry.external_attr>>16), 'Archive symlink rejected')
                if entry.is_dir(): continue
                self._add(name,entry,entry.file_size)
        else:
            self.archive=tarfile.open(path,'r:*'); self.kind='tar'
            for entry in self.archive.getmembers():
                name=member_name(entry.name)
                if entry.isdir(): continue
                s.require(entry.isfile(), 'Archive link/special file rejected')
                self._add(name,entry,entry.size)
        s.require(bool(self.files), 'Empty archive')
    def _add(self,name,entry,size):
        s.require(name not in self.files, 'Duplicate archive member')
        self.total+=size
        s.require(size<=16*1024**2 and self.total<=1024**3 and len(self.files)<100000, 'Archive inspection capacity exceeded')
        self.files[name]=entry
    def read(self,name):
        entry=self.files[name]
        return self.archive.read(entry) if self.kind=='zip' else self.archive.extractfile(entry).read()
    def close(self): self.archive.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()


def json_unique(data):
    def pairs(items):
        result={}
        for key,value in items:
            s.require(key not in result, 'Duplicate JSON attribute')
            result[key]=value
        return result
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs)


def normalize_archive(path, *, expected=EXPECTED):
    """Deterministic format/integrity check; reference labels only group records."""
    with Archive(path) as archive:
        candidates=[]; licenses=[]
        for name in sorted(archive.files):
            if Path(name).name.lower().startswith(('license','licence','copying','terms')):
                value=archive.read(name)
                licenses.append({'member':name,'sha256':hashlib.sha256(value).hexdigest(),
                                 'text':value.decode('utf-8',errors='replace')})
            if name.lower().endswith('.csv'):
                text=archive.read(name).decode('utf-8-sig')
                reader=csv.DictReader(io.StringIO(text,newline=''))
                if reader.fieldnames==['entity_id','spec_id']: candidates.append((name,list(reader)))
        s.require(len(candidates)==1, 'Exactly one official entity_id/spec_id mapping required')
        mapping_name,mapping=candidates[0]; labels={}; duplicates=0
        for row in mapping:
            s.require(set(row)=={'entity_id','spec_id'}, 'Malformed annotation row')
            entity,record=row['entity_id'],row['spec_id']
            s.require(all(isinstance(v,str) and v.strip() and v==v.strip() for v in (entity,record)), 'Invalid annotation ID')
            if record in labels:
                s.require(labels[record]==entity, 'Conflicting entity annotation')
                duplicates+=1
            labels[record]=entity
        specs={}
        for name in archive.files:
            if name.lower().endswith('.json'):
                parts=name.split('/')
                if len(parts)>=2:
                    key=parts[-2]+'//'+parts[-1][:-5]
                    s.require(key not in specs, 'Ambiguous specification path')
                    specs[key]=name
        rows=[]
        for record in sorted(labels,key=lambda value:value.encode('utf-8')):
            parts=record.split('//')
            s.require(len(parts)==2 and all(v and '/' not in v and '\\' not in v and ':' not in v and v not in ('.','..') for v in parts),
                      'Unexpected official specification ID')
            s.require(record in specs, 'Labeled specification absent from archive: '+record)
            obj=json_unique(archive.read(specs[record])); title=obj.get('<page title>') if isinstance(obj,dict) else None
            s.require(isinstance(title,str) and title.strip(), 'Missing/invalid annotated title: '+record)
            title.encode('utf-8')
            rows.append({'record_id':record,'entity_id':labels[record],'text':title})
        actual={'labeled_records':len(rows),'entities':len(set(labels.values())),
                'records':len(specs),'sources':len({v.split('//')[0] for v in specs})}
        s.require(actual==expected, 'Official Camera version/count mismatch: '+repr(actual))
        stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=['record_id','entity_id','text'],lineterminator='\n')
        writer.writeheader(); writer.writerows(rows); normalized=stream.getvalue().encode('utf-8')
        return normalized, rows, {'archive_kind':archive.kind,'archive_members':len(archive.files),
            'archive_uncompressed_bytes':archive.total,'mapping_member':mapping_name,
            'mapping_sha256':hashlib.sha256(archive.read(mapping_name)).hexdigest(),
            'mapping_rows':len(mapping),'identical_mapping_rows_coalesced':duplicates,
            'conflicting_mapping_rows':0,'missing_labeled_records':0,'invalid_annotated_titles':0,
            'actual':actual,'unlabeled_records_excluded':len(specs)-len(rows),'embedded_license_notices':licenses,
            'normalization_uses_outcomes':False,'titles_only':True}


def qualify(archive, provenance, *, root=ROOT):
    root=Path(root).resolve(); gate=checked_gate(root); out=root/EXTERNAL
    out.mkdir(parents=True,exist_ok=True)
    s.write(out/'qualification_consumed.json',{'created_utc':s.utc(),'archive_sha256':s.digest(archive),
            'one_fixed_archive_only':True,'alternative_category_or_resplit':False})
    report={'schema':'cut-audit-v5-alaska-qualification-v1','status':'blocked','gate':gate,
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
    report=s.read(out/'qualification.json'); s.require(report['status']=='qualified','Qualification failed')
    s.require(s.read(out/'config.json')==fixed_config(),'External configuration differs')
    names={p.relative_to(root).as_posix() for p in (root/'src/cut_audit_er').glob('*.py')}
    names.update(('scripts/review_v5/external.py','scripts/review_v5/study.py','scripts/review_v5/analysis.py',
                  'scripts/new_domain/run.py','scripts/new_domain/cohort.py','scripts/review_v4/replay.py',
                  'research/review_v5/PROTOCOL.md','research/review_v5/NUMERIC_BOUND.md','research/review_v5/THEORY.md',
                  'tests/test_review_v5_external.py'))
    names.update(name for name in ('scripts/__init__.py','scripts/review_v5/__init__.py',
        'scripts/new_domain/__init__.py','scripts/review_v4/__init__.py') if (root/name).is_file())
    names.update((out/name).relative_to(root).as_posix() for name in ('qualification.json','source_provenance.json','config.json','memberships.json','normalized/records.csv'))
    names.update(p.relative_to(root).as_posix() for p in (out/'roles').glob('*.json'))
    pins={name:s.digest(root/name) for name in sorted(names)}
    snapshot=out/'source_snapshot'; snapshot.mkdir(exist_ok=False)
    for name in names:
        target=snapshot/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(root/name,target)
    s.check_hashes(snapshot,pins)
    frozen={'schema':'cut-audit-v5-alaska-prefit-freeze-v1','created_utc':s.utc(),
        'files_sha256':pins,'snapshot':snapshot.relative_to(root).as_posix(),'gate':gate,
        'development_freeze_sha256':s.digest(root/s.SESSION/'freeze.json'),'config':fixed_config(),
        'slots':planned_slots(),'formal_test_access':False,'human_approval_record_created':False,
        'authorization_scope':'User-authorized gated local development; no submission, redistribution or held-out test approval'}
    s.write(out/'prefit_freeze.json',frozen); return frozen


def check_prefit(root=ROOT):
    root=Path(root).resolve(); out=root/EXTERNAL; frozen=s.read(out/'prefit_freeze.json')
    s.require(frozen['schema']=='cut-audit-v5-alaska-prefit-freeze-v1' and frozen['config']==fixed_config()
              and frozen['slots']==planned_slots(),'Wrong external pre-fit freeze')
    s.require(s.digest(root/s.SESSION/'freeze.json')==frozen['development_freeze_sha256'],'Development freeze changed')
    s.check_hashes(root,frozen['files_sha256']); s.check_hashes(s.relative(root,frozen['snapshot']),frozen['files_sha256'])
    checked_gate(root)
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
    frozen={'schema':'cut-audit-v5-alaska-repair-freeze-v1','created_utc':s.utc(),
        'prefit_sha256':s.digest(out/'prefit_freeze.json'),'preparation_sha256':s.digest(out/'preparation.json'),
        'graph_files_sha256':report['graph_files_sha256'],'slots':planned_slots(),
        'note':'Frozen before repair outcomes; one fixed evaluation graph including isolates', 'formal_test_access':False}
    s.write(out/'repair_freeze.json',frozen); return report


def check_repair(root=ROOT):
    root=Path(root).resolve(); out=root/EXTERNAL; check_prefit(root)
    frozen=s.read(out/'repair_freeze.json')
    s.require(frozen['schema']=='cut-audit-v5-alaska-repair-freeze-v1' and frozen['slots']==planned_slots(), 'Wrong repair freeze')
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('inspect','qualify','freeze','prepare','run','continue'))
    parser.add_argument('--archive',type=Path); parser.add_argument('--provenance',type=Path)
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
    else: report=run(continue_run=args.action=='continue',absence_receipt=args.absence_receipt)
    if args.receipt: s.write(args.receipt,report)
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__': main()
