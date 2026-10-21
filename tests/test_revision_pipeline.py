"""Offline end-to-end tests of the revision-one control flow (no network/API keys)."""
import ast
import copy
from pathlib import Path

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
names={'revision_queue','validated_revision_candidate','revision_one','judge'}
parts=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert len(parts)==len(names),names
compiled=compile(ast.Module(body=parts,type_ignores=[]),'<repair-test>','exec')

ORIGINAL={
    'id':'SAA-AUTO-00001','exam':'SAA-C03','domain':'D1',
    'topic':'Security group','type':'single','difficulty':'中級',
    'question':'Original problem about inbound traffic?',
    'choices':['a','b','c','d'],'correct':['A'],
    'explanation':'Not good','language':'ja',
    'source':{'kind':'original','label':'original'},
}
def state_fixture():
    return {'campaign_budget_1000jpy_enabled':True,
      'generated':{'SAA-AUTO-00001':{
          'status':'REVISE_UNRESOLVED','candidate':copy.deepcopy(ORIGINAL),
          'audit':[{'review':{'issues':['incorrect answer']}}]}},
      'history':[], 'revision_trials':{}}

class FakeAPI:
    requests=[]
    malformed_once=False
    def __init__(self,*keys,limit=3):
        self.keys={'openai':'fake','gemini':'fake'}
        self.calls=0
        self.limit=limit
    def call(self,provider,prompt,payload):
        if self.calls>=self.limit:raise RuntimeError('too many requests')
        self.calls+=1
        self.requests.append(provider)
        if self.malformed_once:
            self.malformed_once=False
            return {'reviews':[]}
        return {'reviews':[{'id':payload['questions'][0]['id'],
            'verdict':'PASS','issues':[], 'notes':'good'}]}

class FakeA:
    STATEFILE='work/state.json'
    state=None
    saved=[]
    @staticmethod
    def today():return '2026-10-21'
    @staticmethod
    def state_default():return {}
    @classmethod
    def jread(cls,path,default=None):return cls.state
    @classmethod
    def jwrite(cls,path,state):
        cls.saved.append(copy.deepcopy(state))
    @staticmethod
    def load_keys():return ('fake_openai','fake_gemini')
    @staticmethod
    def validate(q,strict=False):
        assert strict and len(q['choices'])==4 and q['correct']==['A']
    @staticmethod
    def validate_review(review):
        if review.get('verdict') not in ('PASS','BLOCK','REVISE'):
            raise ValueError('bad verdict')
    @staticmethod
    def meets_exam_quality(review):return True

class FakeLock:
    busy=False
    taken=0
    released=0
    @classmethod
    def windows_lock(cls,path):
        if cls.busy:return None
        cls.taken+=1
        return object()
    @classmethod
    def release_lock(cls,lock):cls.released+=1

class Stop:
    exists_value=True
    @classmethod
    def exists(cls):return cls.exists_value

def scenario(*, enabled=True,busy=False,available=150,daily=25,
             malformed=False,change_domain=False,duplicate=False,stopped=True):
    state=state_fixture()
    state['campaign_budget_1000jpy_enabled']=enabled
    FakeA.state=state
    FakeA.saved=[]
    FakeAPI.requests=[]
    FakeAPI.malformed_once=malformed
    FakeLock.busy=busy
    FakeLock.taken=FakeLock.released=0
    Stop.exists_value=stopped
    def reserve(st):
        budget=st.setdefault('campaign_budget_1000jpy',{'reserved_calls':0})
        if budget['reserved_calls']>=available:raise RuntimeError('budget exhausted')
        budget['reserved_calls']+=1
        FakeA.jwrite(FakeA.STATEFILE,st)
    def structured(api,prompt,payload):
        assert 'original' in payload and len(payload['specs'])==1
        api.calls+=1
        FakeAPI.requests.append('openai')
        changed=copy.deepcopy(ORIGINAL)
        changed['question']='Revised, distinct scenario with correct traffic policy?'
        changed['explanation']='A detailed explanation and why all distractors fail.'
        if change_domain:changed['domain']='D3'
        return {'questions':[changed]}
    ns={'a':FakeA,'ua':FakeLock,'STOP':Stop,'LOCK':'work/autopilot.lock',
        'CUTOFF':'2026-10-28','API':FakeAPI,'GENERATION_MODEL':'gpt-4.1-mini',
        'daily_call_cap':lambda:daily,'used_today':lambda state:0,
        'campaign_budget_remaining':lambda state:available-state.get('campaign_budget_1000jpy',{}).get('reserved_calls',0),
        'reserve_campaign_api_request':reserve,
        'structured_batch_call':structured,
        'question_is_near_duplicate':lambda *args:duplicate,
        'R_PROMPT':'review',
    }
    exec(compiled,ns)
    return ns, state

ns, state=scenario()
assert len(ns['revision_queue'](state))==1
notes_state=copy.deepcopy(state)
notes_state['generated']['SAA-AUTO-00001']['audit']=[{'review':{'issues':[], 'notes':'review notes only'}}]
assert ns['revision_queue'](notes_state)[0]['issues']==['review notes only']
original_snapshot=copy.deepcopy(state['generated'])
assert ns['revision_one']()==0
assert state['generated']==original_snapshot, 'the bank must never change'
assert state['revision_trials']['SAA-AUTO-00001']['status']=='REVIEWED_HOLD'
assert state['revision_trials']['SAA-AUTO-00001']['human_approved'] is False
assert state['campaign_budget_1000jpy']['reserved_calls']==2
assert state['history'][-1]['calls']==2
assert FakeAPI.requests==['openai','gemini']
assert FakeLock.taken==FakeLock.released==1

ns, state=scenario(malformed=True)
assert ns['revision_one']()==0, 'one Gemini invalid reply is retried'
assert state['campaign_budget_1000jpy']['reserved_calls']==3
assert state['history'][-1]['calls']==3
assert FakeLock.taken==FakeLock.released==1

ns, state=scenario(change_domain=True)
assert ns['revision_one']()==1
assert state['revision_trials']['SAA-AUTO-00001']['status']=='REVISION_ERROR'
assert state['history'][-1]['errors']==[], 'repair errors must not trigger batch retry'
assert state['history'][-1]['revision_error']
assert FakeAPI.requests==['openai']
assert state['generated']['SAA-AUTO-00001']['candidate']==ORIGINAL

ns, state=scenario(duplicate=True)
assert ns['revision_one']()==1
assert FakeAPI.requests==['openai']
assert state['revision_trials']['SAA-AUTO-00001']['status']=='REVISION_ERROR'

for kw in ({'enabled':False},{'busy':True},{'available':2},
           {'daily':2},{'stopped':False}):
    ns, state=scenario(**kw)
    assert ns['revision_one']()==2,kw
    assert FakeAPI.requests==[],kw
    assert not FakeA.saved,kw

ns,state=scenario()
state['revision_trials']['SAA-AUTO-00001']={'status':'REVISION_ERROR'}
assert ns['revision_one']()==0, 'an attempted item is not automatically retried'
assert FakeAPI.requests==[]
print('PASS revision schema, two-provider retries, locks, budget guards, no-overwrite')
