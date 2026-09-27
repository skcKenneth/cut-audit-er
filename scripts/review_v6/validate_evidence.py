"""Dependency-free checks of public V6 accounting, with no hidden data access."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


def require(value, message):
    if not value: raise ValueError(message)


def read(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def exact_ratio(row, prefix=''):
    return Fraction(int(row[prefix+'loss_gain']),int(row[prefix+'query_cost']))


def validate_rows(visible, evaluated, histogram):
    require(len(visible)==301 and len({r['state'] for r in visible})==301,'Physical state inventory differs')
    require(Counter(r['phase'] for r in visible)=={'natural':241,'synthetic':60},'Fixed phase counts differ')
    require(len(evaluated)==361 and len({(r['state'],r['reference']) for r in evaluated})==361,'Dependent reference inventory differs')
    states={r['state']:r for r in visible}
    grouped=defaultdict(list)
    for row in histogram:
        key=(row['state'],row['reference'])
        require(row['state'] in states and int(row['count'])>0,'Invalid histogram multiplicity/state')
        cost=int(row['query_cost']); fp=int(row['fp_removed']); fn=int(row['fn_added'])
        require(0<cost<=4 and fp>=0 and fn>=0 and int(row['loss_gain'])==fp-fn,'Candidate FP/FN conservation')
        require(int(row['positive_answers'])+int(row['negative_answers'])==cost,'Candidate payment accounting')
        require(float(row['gain_per_query'])==float(exact_ratio(row)),'Candidate gain normalization')
        grouped[key].append(row)
    completed=0; positive=0
    for row in evaluated:
        key=(row['state'],row['reference']); state=states[row['state']]
        require(row['reference'] in (('H0','H9') if state['phase']=='synthetic' else ('natural',)), 'Reference role differs')
        if row['single_batch_oracle_gap']=='':
            require(not grouped[key],'Missing state has candidate values')
            continue
        completed+=1
        cost=int(row['selected_query_cost']); fp=int(row['selected_fp_removed']); fn=int(row['selected_fn_added'])
        require(cost>0 and fp>=0 and fn>=0 and int(row['selected_loss_gain'])==fp-fn,'Selected FP/FN conservation')
        require(int(row['selected_negative_answers'])+int(row['selected_positive_answers'])==cost,'Selected payment accounting')
        selected=exact_ratio(row,'selected_')
        require(float(row['selected_gain_per_query'])==float(selected),'Selected value differs')
        candidates=grouped[key]
        require(sum(int(r['count']) for r in candidates)==int(row['candidate_occurrences']), 'Candidate denominator differs')
        best=max([Fraction(0),selected]+[exact_ratio(r) for r in candidates])
        gap=best-selected
        require(float(row['best_known_gain_per_query'])==float(best),'Best realized value differs')
        require(float(row['single_batch_oracle_gap'])==float(gap),'Realized gap differs')
        numerator,denominator=json.loads(row['gap_fraction'])
        require(Fraction(numerator,denominator)==gap,'Exact gap fraction differs')
        positive+=gap>0
        total=int(row['total_fp']); covered=int(row['covered_fp'])
        require(0<=covered<=total,'Invalid FP coverage')
        require((row['fp_coverage']=='' if total==0 else float(row['fp_coverage'])==covered/total),'FP coverage denominator differs')
        if state['searched_pool_complete_audit'] in ('True','true'):
            require(sum(int(r['count']) for r in candidates)==int(state['pool_count']),'Searched-pool occurrence count differs')
    return {'physical_states':301,'reference_slots':361,'evaluated_reference_states':completed,
            'positive_gap_reference_states':positive,'unknown_reference_states':361-completed,
            'candidate_occurrences':sum(int(r['count']) for r in histogram)}


def validate(evidence):
    evidence=Path(evidence)
    manifest=json.loads((evidence/'manifest.json').read_text(encoding='utf-8'))
    require(manifest['schema']=='cut-audit-v6-public-scalar-evidence','Wrong evidence manifest')
    for name,pin in manifest['files_sha256'].items():
        require(Path(name).name==name and name not in ('.','..'),'Unsafe manifest member')
        require(hashlib.sha256((evidence/name).read_bytes()).hexdigest()==pin,'Evidence hash mismatch: '+name)
    report=validate_rows(read(evidence/'visible_states.csv'),read(evidence/'evaluation_states.csv'),
                         read(evidence/'candidate_value_histogram.csv'))
    summary=json.loads((evidence/'summary.json').read_text(encoding='utf-8'))
    require(summary['physical_states']==301 and summary['reference_slots']==361,'Summary inventory mismatch')
    require(sum(g['evaluated_states'] for g in summary['groups'])==report['evaluated_reference_states'],'Summary completed mismatch')
    require(sum(g['positive_realized_gap_states'] for g in summary['groups'])==report['positive_gap_reference_states'],'Summary positive gap mismatch')
    external=read(evidence/'external_endpoints.csv')
    external_status=json.loads((evidence/'external_status.json').read_text(encoding='utf-8'))
    require(len(external)==21 and len({r['id'] for r in external})==21,'External slot inventory differs')
    require(Counter(int(r['budget']) for r in external)=={12:7,24:7,48:7},'External budgets differ')
    require(all(r['status']=='not_started_download_blocked' and all(r[k]=='' for k in ('fp','fn','loss','paid_queries')) for r in external),'Unavailable external outcomes were populated')
    require(external_status['status']=='blocked_download' and external_status['acquisitions_started']==0
            and external_status['new_model_fits']==0 and external_status['archive_downloads']==0,
            'External absence receipt differs')
    return {'status':'PASS',**report,'scope':'Public arithmetic and provenance; no pair identity or graph legality reconstruction.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args();print(json.dumps(validate(a.evidence),indent=2))
