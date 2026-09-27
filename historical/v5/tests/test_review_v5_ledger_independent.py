"""Independent ledger/proof fault checks using toy objects and fake workers."""
import hashlib

import pytest

from scripts.review_v5 import study as s


class Copyable:
    def copy(self):
        return Copyable()


def grid():
    return [{'id': f'wdc_{i}', 'dataset': 'wdc', 'method': 'edge_betweenness',
             'budget': 1, 'status': 'not_started'} for i in (0,1)]


def assets():
    return {'wdc': (Copyable(), Copyable(), {'x':'one'})}


def interrupted(out):
    def worker(*_):
        raise KeyboardInterrupt('Independent test interruption')
    with pytest.raises(KeyboardInterrupt):
        s.execute_grid(out,'natural',grid(),assets(),'a'*64,audit_fn=worker,
                       clock=lambda:0.,epoch=lambda:100.)
    return s.ledger_state(out,grid())[2]


def proof_for(pending):
    return {'status':'confirmed_absent','scope':'V5_workers_and_supervisor',
            'active_python_workers':0,'checked_epoch_seconds':150.,
            'launch_identity_sha256':hashlib.sha256(s.blob(pending)).hexdigest()}


@pytest.mark.parametrize('field,value',[
    ('status','not_confirmed'), ('scope','unrelated_python_processes'),
    ('active_python_workers',1), ('launch_identity_sha256','0'*64),
    ('checked_epoch_seconds',99.), ('checked_epoch_seconds',201.),
    ('checked_epoch_seconds',True),
])
def test_wrong_absence_proof_never_consumes_or_launches_next_slot(tmp_path,field,value):
    out=tmp_path/'study'; pending=interrupted(out)
    before={p.name:s.digest(p) for p in (out/'ledger').glob('*.json')}
    proof=proof_for(pending);proof[field]=value
    path=tmp_path/'proof.json';s.write(path,proof)
    calls=[]
    with pytest.raises(ValueError):
        s.execute_grid(out,'natural',grid(),assets(),'a'*64,continue_run=True,
                       absence_receipt=path,audit_fn=lambda *a:calls.append(a),epoch=lambda:200.)
    assert calls==[]
    assert before=={p.name:s.digest(p) for p in (out/'ledger').glob('*.json')}
    assert s.ledger_state(out,grid())[2]['id']==pending['id']


def test_recovery_does_not_promote_uncommitted_completed_payload(tmp_path):
    out=tmp_path/'study';pending=interrupted(out)
    unaccepted=out/'runs'/f"{pending['id']}.json"
    s.write(unaccepted,{'status':'completed','run':{'complete':True},'identity':pending['identity']})
    original=unaccepted.read_bytes()
    proof=tmp_path/'proof.json';s.write(proof,proof_for(pending))
    s.recover_pending(out,grid(),proof,now=lambda:200.)
    rows,elapsed,active=s.ledger_state(out,grid())
    assert active is None and rows[0]['status']=='interrupted' and rows[1]['status']=='not_started'
    assert elapsed['wdc']==100. and unaccepted.read_bytes()==original
    recovery=s.read(out/rows[0]['path'])
    assert recovery['complete_result_promoted'] is False
    assert recovery['unaccepted_result_sha256']==hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize('charge',[-1.,float('inf'),float('nan'),True])
def test_invalid_duration_is_rejected_even_with_a_consistent_hash_chain(tmp_path,charge):
    out=tmp_path/'study';pending=interrupted(out)
    event={'kind':'finish','id':pending['id'],'charged_seconds':charge,
           'result':{'status':'failed'}}
    # Nonfinite values must be refused on append or on semantic ledger read.
    with pytest.raises(ValueError):
        s.append_event(out,event)
        s.ledger_state(out,grid())


@pytest.mark.parametrize('result',[
    {'status':'running'}, {'status':'not_started'},
    {'status':'completed','budget':9}, {'status':'failed','method':'other'},
])
def test_finish_cannot_rewrite_declared_identity_or_remain_nonterminal(tmp_path,result):
    out=tmp_path/'study';pending=interrupted(out)
    s.append_event(out,{'kind':'finish','id':pending['id'],'charged_seconds':1.,'result':result})
    with pytest.raises(ValueError):
        s.ledger_state(out,grid())


def test_durable_launch_exists_before_worker_and_repeated_consumption_is_refused(tmp_path):
    out=tmp_path/'study';seen=[]
    def worker(arguments,seconds,journal,identity):
        rows,elapsed,pending=s.ledger_state(out,grid())
        assert pending['identity']==identity
        assert s.read(out/'consumed.json')['freeze_sha256']=='a'*64
        assert rows[len(seen)]['status']=='running'
        seen.append(identity['run_id'])
        return {'status':'timeout'}
    s.execute_grid(out,'natural',grid(),assets(),'a'*64,audit_fn=worker)
    assert seen==[r['id'] for r in grid()]
    # Directly appending a second launch for the already consumed identity is
    # invalid even if all predecessor hashes were generated correctly.
    launch=next(e for e in s.ledger_events(out) if e['kind']=='launch')
    s.append_event(out,{k:v for k,v in launch.items() if k not in ('seq','previous_sha256')})
    with pytest.raises(ValueError,match='Repeated|order'):
        s.ledger_state(out,grid())


def test_finished_live_worker_cannot_be_bypassed_by_continue(tmp_path):
    out=tmp_path/'study';calls=[]
    def alive(*_):
        calls.append('initial')
        return {'status':'cleanup_failed','cleanup_worker_still_alive':True}
    with pytest.raises(ValueError,match='Worker still alive'):
        s.execute_grid(out,'natural',grid(),assets(),'a'*64,audit_fn=alive)
    assert s.ledger_state(out,grid())[2] is None  # Already terminal, no pending guard.
    before={p.name:s.digest(p) for p in (out/'ledger').glob('*.json')}
    with pytest.raises(ValueError):
        s.execute_grid(out,'natural',grid(),assets(),'a'*64,continue_run=True,
                       audit_fn=lambda *_:calls.append('unsafe continuation'))
    assert calls==['initial']
    assert before=={p.name:s.digest(p) for p in (out/'ledger').glob('*.json')}
