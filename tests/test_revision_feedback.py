"""Zero-network human rejection -> retry contract, including no-approval and history safety."""
import ast
import copy
import json
import re
from pathlib import Path

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'revision_is_staged_or_approved','revision_request_changes','revision_queue',
        'revision_one','validated_revision_candidate','judge'}
funcs=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in wanted]
assert len(funcs)==len(wanted)
uid='SAA-AUTO-00020'
feedback='高スループットFIFOを過小評価している。SNSイベント配信と既存SQSメッセージの複製を混同している。'
original={'id':uid,'exam':'SAA-C03','domain':'D2','topic':'SQS','type':'single',
          'difficulty':'中級','question':'Original question','choices':['a','b','c','d'],
          'correct':['A'],'explanation':'Original explanation',
          'source':{'kind':'original','label':'AI generation'},'language':'ja'}
revision={**original,'question':'First revision scenario',
          'explanation':'First revision explanation'}
def fixture():
    return {'campaign_budget_1000jpy_enabled':True,
      'generated':{uid:{'status':'REVISE_UNRESOLVED','candidate':copy.deepcopy(original),
                        'audit':[{'review':{'issues':['Invented AWS capability']}}]}},
      'revision_trials':{uid:{'status':'REVIEWED_HOLD','candidate':copy.deepcopy(revision),
                              'original_status':'REVISE_UNRESOLVED',
                              'review':{'verdict':'PASS','issues':[]}}},
      'history':[]}
class A:
    STATEFILE='statefile'
    data={}
    files={}
    writes=[]
    @classmethod
    def jread(cls,path,default=None):
        if str(path)==cls.STATEFILE:return cls.data
        return cls.files.get(str(path),default)
    @classmethod
    def jwrite(cls,path,data):
        cls.writes.append((str(path),copy.deepcopy(data)))
        if str(path)!=cls.STATEFILE:cls.files[str(path)]=copy.deepcopy(data)
    @staticmethod
    def state_default():return {}
    @staticmethod
    def load_keys():return ('fake1','fake2')
    @staticmethod
    def today():return '2026-10-21'
    @staticmethod
    def validate(question,strict=False):
        assert strict and question['id']==uid
    @staticmethod
    def validate_review(v):
        assert v['verdict']=='PASS'
    @staticmethod
    def meets_exam_quality(v):return True
class UA:
    busy=False
    taken=0
    released=0
    @classmethod
    def windows_lock(cls,*args):
        if cls.busy:return None
        cls.taken+=1
        return object()
    @classmethod
    def release_lock(cls,*args):cls.released+=1
class Stop:
    stopped=True
    @classmethod
    def exists(cls):return cls.stopped
class API:
    requests=[]
    def __init__(self,*keys,limit=3):
        self.calls=0
        self.limit=limit
    def call(self,provider,prompt,payload):
        assert provider=='gemini'
        assert self.calls<self.limit
        self.calls+=1
        API.requests.append(('gemini',payload))
        return {'reviews':[{'id':uid,'verdict':'PASS','issues':[]}]}
def scenario(*, staged=False,approved=False, broken=False, daily=25,enabled=True):
    A.data=fixture()
    A.data['campaign_budget_1000jpy_enabled']=enabled
    A.files={}
    A.writes=[]
    API.requests=[]
    UA.busy=False
    UA.taken=UA.released=0
    Stop.stopped=True
    p=Path('fake')/'work'
    if staged:A.files[str(p/'outputs'/'revision_staged.json')]={'questions':[revision]}
    if approved:A.files[str(p/'content_approvals.json')]={'approvals':{uid:{'human_approved':True}}}
    def reserve(st):
        ledger=st.setdefault('campaign_budget_1000jpy',{'reserved_calls':0})
        ledger['reserved_calls']+=1
        A.jwrite(A.STATEFILE,st)
    def structured(api,prompt,payload):
        assert payload['issues']==[feedback]
        assert payload['original']['question']=='First revision scenario'
        assert len(payload['specs'])==1 and payload['specs'][0]['id']==uid
        api.calls+=1
        API.requests.append(('openai',payload))
        if broken:raise ValueError('Malformed JSON received')
        changed=copy.deepcopy(revision)
        changed['question']='Second correction with valid AWS features and DR event fanout.'
        changed['explanation']='All answer choices carefully examined'
        return {'questions':[changed]}
    ns={'a':A,'ua':UA,'STOP':Stop,'LOCK':'local.lock','ROOT':p.parent,
        're':re,'json':json,'CUTOFF':'2026-10-28','API':API,'R_PROMPT':'review',
        'GENERATION_MODEL':'gpt-4.1-mini','daily_call_cap':lambda:daily,
        'used_today':lambda st:0,'campaign_budget_remaining':
            lambda st:150-st.get('campaign_budget_1000jpy',{}).get('reserved_calls',0),
        'reserve_campaign_api_request':reserve,'structured_batch_call':structured,
        'question_is_near_duplicate':lambda *args:False}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'<feedback-test>','exec'),ns)
    return ns,A.data

ns,state=scenario()
before=copy.deepcopy(state['generated'])
first=copy.deepcopy(state['revision_trials'][uid])
assert ns['revision_request_changes'](uid,feedback)==0
assert ns['revision_request_changes'](uid,feedback)==0
assert ns['revision_request_changes'](uid,feedback+' differing')==2
assert state['generated']==before
assert state['revision_trials'][uid]['status']=='REVISION_REQUESTED'
assert state['revision_trials'][uid]['candidate']==first['candidate']
assert state['revision_trials'][uid]['review']==first['review']
assert state['revision_trials'][uid]['human_review']['issues']==[feedback]
assert state.get('campaign_budget_1000jpy') is None
assert all(x[0]==A.STATEFILE for x in A.writes)
assert ns['revision_one']()==0, 'normal auto selection must skip rejected trial'
assert API.requests==[]
assert ns['revision_one'](retry_id=uid)==0
assert [x[0] for x in API.requests]==['openai','gemini']
assert state['revision_trials'][uid]['status']=='REVIEWED_HOLD'
assert state['revision_trials'][uid]['candidate']['question'].startswith('Second correction')
assert state['revision_trials'][uid]['original_status']=='REVISE_UNRESOLVED'
assert state['revision_trials'][uid]['revision_round']==2
assert state['revision_trials'][uid]['human_approved'] is False
assert state['revision_trial_history'][uid][0]['status']=='REVISION_REQUESTED'
assert state['revision_trial_history'][uid][0]['human_review']['issues']==[feedback]
assert state['generated']==before
assert state['campaign_budget_1000jpy']['reserved_calls']==2
assert state['history'][-1]['calls']==2
assert UA.taken==UA.released
assert "if len(sys.argv)==4 and sys.argv[1]=='revision-request-changes'" in src
assert "if len(sys.argv)==3 and sys.argv[1]=='revision-retry'" in src
ns,state=scenario(broken=True)
assert ns['revision_request_changes'](uid,feedback)==0
assert ns['revision_one'](retry_id=uid)==1
assert state['revision_trials'][uid]['status']=='REVISION_ERROR'
assert state['revision_trial_history'][uid][0]['candidate']==revision
assert state['generated'][uid]['candidate']==original
for flag in ('staged','approved'):
    ns,state=scenario(**{flag:True})
    assert ns['revision_request_changes'](uid,feedback)==2
    assert ns['revision_one'](retry_id=uid)==2
    assert API.requests==[]
for kw in ({'daily':2},{'enabled':False}):
    ns,state=scenario(**kw)
    assert ns['revision_request_changes'](uid,feedback)==0
    assert ns['revision_one'](retry_id=uid)==2
    assert API.requests==[]
ns,state=scenario()
Stop.stopped=False
assert ns['revision_request_changes'](uid,feedback)==2
Stop.stopped=True
UA.busy=True
assert ns['revision_request_changes'](uid,feedback)==2
assert not A.writes
print('PASS human rejection -> explicit budgeted retry; originals, approval and old attempts protected')
