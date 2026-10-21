"""Offline tests for bounded revision-batch scheduling; no API credentials."""
import ast
from pathlib import Path

s=Path('release_files/update_watchdog.py').read_text(encoding='utf-8')
tree=ast.parse(s)
func=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='revision_batch')
class A:
    STATEFILE='work/state.json'
    state={}
    @classmethod
    def jread(cls,*args):return cls.state
    @staticmethod
    def state_default():return {}

def run(*,count=81,cap=25,enabled=True,blocked=False,already=0,error_once=False):
    A.state={'campaign_budget_1000jpy_enabled':enabled,
             'generated':{f'Q{i}':{'status':'REVISE_UNRESOLVED','candidate':{'id':f'Q{i}'},
                         'audit':[{'review':{'issues':['weak answer']}}]}
                         for i in range(count)},
             'revision_trials':{f'Q{i}':{'status':'REVISION_ERROR'} for i in range(already)}}
    requests=[]
    def queue(state):
        return [{'id':k,'issues':['weak answer']}
                for k in sorted(state['generated'])]
    def repair():
        if blocked:return 2
        seen=set(A.state['revision_trials'])
        next_id=next((q['id'] for q in queue(A.state) if q['id'] not in seen),None)
        if next_id is None:return 0
        requests.append(next_id)
        A.state['revision_trials'][next_id]={'status':'REVISION_ERROR' if error_once else 'REVIEWED_HOLD'}
        return 1 if error_once else 0
    ns={'a':A,'REVISION_BATCH_SIZE':3,'revision_queue':queue,
        'revision_one':repair,'campaign_budget_remaining':lambda st:cap,
        'daily_call_cap':lambda:25,'used_today':lambda st:0}
    exec(compile(ast.Module(body=[func],type_ignores=[]),'<batch>', 'exec'),ns)
    return ns['revision_batch'](),requests,A.state

ret,ids,state=run()
assert ret==0 and ids==['Q0','Q1','Q10'],ids
assert len(state['revision_trials'])==3 and len(state['generated'])==81
ret,ids,state=run(count=2)
assert ret==0 and ids==['Q0','Q1']
ret,ids,state=run(count=8,already=3)
assert len(ids)==3 and not any(q in ('Q0','Q1','Q2') for q in ids)
for flags in ({'blocked':True},{'enabled':False},{'cap':2}):
    ret,ids,state=run(**flags)
    assert ret==2 and ids==[],flags
ret,ids,state=run(error_once=True)
assert ret==1 and len(ids)==1, 'provider failure must stop with nonzero exit'
assert state['revision_trials'][ids[0]]['status']=='REVISION_ERROR'
ret,ids,state=run(count=0)
assert ret==0 and ids==[]
assert "if sys.argv[1:]==['revision-batch']" in s
print('PASS limited repair batches, resume, no repeated IDs, fail-closed')
