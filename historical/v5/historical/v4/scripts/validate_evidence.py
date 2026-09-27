"""Check V4 public aggregate evidence without private graphs or benchmark text."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
from decimal import Decimal
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.legacy_v3.validate_evidence import validate as legacy_validate

INTS={'budget','fp','fn','loss','paid','initial_fp','initial_fn','initial_loss','batch','spent','spent_before',
      'fp_removed','fn_added','fp_after','fn_after','loss_after','action_size','logical_score_accesses',
      'generated','generated_multi','capped','capped_multi','scored','scored_multi','selected_depth',
      'nodes','edges','components','exact_components','covered_fp','headroom','k','actual_spent',
      'loss_difference','fp_difference','fn_difference','exact_loss'}

def table(folder,name):
    with (Path(folder)/(name+'.csv')).open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f))
    def integer(value):
        number=Decimal(value)
        if not number.is_finite() or number!=number.to_integral_value():
            raise ValueError('Non-integral count in evidence')
        return int(number)
    def seconds(value):
        number=float(value)
        if not math.isfinite(number) or number<0:raise ValueError('Invalid measured duration')
        return number
    return [{k:(None if v=='' else integer(v) if k in INTS else seconds(v) if k.endswith('_seconds') else v)
             for k,v in r.items()} for r in rows]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def validate(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest['schema']!='cut-audit-public-evidence-v4':raise ValueError('Evidence schema mismatch')
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    if actual!=set(manifest['files_sha256'])|{'manifest.json'}:raise ValueError('Unlisted or missing evidence file')
    for name,pin in manifest['files_sha256'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or sha(path)!=pin:raise ValueError('Evidence hash mismatch')
    legacy=legacy_validate(folder/'legacy_v3')
    endpoints=table(folder,'natural_endpoints');events=table(folder,'natural_events');batches=table(folder,'natural_batches')
    if len(endpoints)!=27:raise ValueError('Expected all18legacy+9prospective slots')
    keys=[(r['dataset'],r['method'],r['budget']) for r in endpoints]
    methods=('edge_betweenness','cut_plan_fixed','cut_plan_fixed_singleton')
    expected={(d,m,b) for d in ('wdc','dblp_acm','dblp_unused') for m in methods for b in (12,24,48)}
    if set(keys)!=expected or len(set(keys))!=27:raise ValueError('Natural grid differs')
    ids={r['run_id'] for r in endpoints}
    if len(ids)!=27 or any(e['run_id'] not in ids for e in events+batches):raise ValueError('Orphan/duplicate run identity')
    for r in endpoints:
        if r['status']!='completed':
            if any(r[k] is not None for k in ('fp','fn','loss')):raise ValueError('Missing endpoint imputed')
            continue
        ee=sorted([e for e in events if e['run_id']==r['run_id']],key=lambda e:e['spent'])
        bb=[b for b in batches if b['run_id']==r['run_id']]
        if not 0<=r['paid']<=r['budget']:raise ValueError('Paid count violates requested budget')
        if r['loss']!=r['fp']+r['fn'] or r['initial_loss']!=r['initial_fp']+r['initial_fn']:raise ValueError('FP/FN sum differs')
        if len(ee)!=r['paid'] or sum(b['action_size'] for b in bb)!=r['paid']:raise ValueError('Paid/batch cost differs')
        fp,fn=r['initial_fp'],r['initial_fn']
        for i,e in enumerate(ee,1):
            if e['spent']!=i:raise ValueError('Event positions have a gap')
            if e['fp_removed']<0 or e['fn_added']<0:raise ValueError('Invalid deletion-only error change')
            if e['category'] in ('paid_positive','paid_negative_no_split','positive','negative_no_split') and (e['fp_removed'] or e['fn_added']):
                raise ValueError('Non-splitting query changed partition metrics')
            fp-=e['fp_removed'];fn+=e['fn_added']
            if (fp,fn,fp+fn)!=(e['fp_after'],e['fn_after'],e['loss_after']):raise ValueError('Per-event conservation differs')
        if (fp,fn)!=(r['fp'],r['fn']):raise ValueError('Endpoint/event conservation differs')
    synthetic=table(folder,'synthetic_endpoints')
    if len(synthetic)!=180:raise ValueError('All180offline synthetic slots required')
    expected_s={(k,p,h,m,b) for k in (1,2,3) for p in ('uniform','ranked') for h in ('H0','H9') for m in methods for b in (1,2,3,4,6)}
    actual_s={(r['k'],r['profile'],r['reference'],r['method'],r['budget']) for r in synthetic}
    if actual_s!=expected_s:raise ValueError('Synthetic fixed grid differs')
    completed=[r for r in synthetic if r['status']=='completed']
    for r in synthetic:
        if r['status']=='completed':
            if r['loss']!=r['fp']+r['fn']:raise ValueError('Synthetic FP/FN differs')
        elif any(r[k] is not None for k in ('fp','fn','loss')):raise ValueError('Missing synthetic endpoint imputed')
    return {'status':'PASS','natural_slots':len(endpoints),'natural_completed':sum(r['status']=='completed' for r in endpoints),
            'synthetic_reference_slots':len(synthetic),'synthetic_reference_completed':len(completed),
            'synthetic_independent_observations_claimed':False,'legacy_status':legacy.get('status','PASS')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,default=ROOT/'evidence');a=p.parse_args()
    print(json.dumps(validate(a.evidence)))
