"""Offline read-only revision visibility and privacy checks."""
import ast
import io
import json
from pathlib import Path
from contextlib import redirect_stdout

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
targets={'revision_queue','revision_summary','revision_status'}
funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in targets]
assert len(funcs)==3
class FakeA:
    state={}
    STATEFILE='fake-state.json'
    reads=0
    writes=0
    @classmethod
    def jread(cls,*args):
        cls.reads+=1
        return cls.state
    @classmethod
    def jwrite(cls,*args):
        cls.writes+=1
        raise RuntimeError('Read-only command must not write')
    @staticmethod
    def state_default():return {}
ns={'a':FakeA,'json':json,'campaign_budget_remaining':lambda st:147,
    'daily_call_cap':lambda:25,'used_today':lambda st:22}
exec(compile(ast.Module(body=funcs,type_ignores=[]),'<audit>', 'exec'),ns)
FakeA.state={
 'generated':{
  'Q1':{'status':'REVISE_UNRESOLVED','candidate':
            {'id':'Q1','domain':'D1','topic':'KMS',
             'question':'PRIVATE_QUESTION_TEXT','correct':['B']},
        'audit':[{'review':{'issues':['PRIVATE_REVIEW_NOTE']}}]},
  'Q2':{'status':'REVISE_UNRESOLVED','candidate':
            {'id':'Q2','domain':'D2','topic':'DR'},
        'audit':[{'review':{'issues':['critical']}}]},
  'Q3':{'status':'REVISION_REQUIRED','candidate':
            {'id':'Q3','domain':'D1','topic':'SG'},
        'audit':[{'review':{'issues':[]}}]},
  'Q4':{'status':'QUALITY_HOLD','candidate':{'id':'Q4','domain':'D3'}},
  'Q5':{'status':'AI_PASS','candidate':{'id':'Q5','domain':'D4'}}
 },
 'revision_trials':{
  'Q1':{'status':'REVIEWED_HOLD','candidate':
             {'question':'PRIVATE_REVISED_QUESTION'}}
 },
 'campaign_budget_1000jpy':{'reserved_calls':3},
 'history':[{'date':'2026-10-21','calls':22}]
}
before=json.dumps(FakeA.state,sort_keys=True)
result=ns['revision_summary'](FakeA.state)
assert result['unresolved_total']==3
assert result['already_attempted']==1
assert result['ready_for_first_revision']==1
assert result['missing_review_issues']==1
assert result['attempt_outcomes']['REVIEWED_HOLD']==1
assert result['by_domain']['D1']['attempted']==1
assert result['by_domain']['D1']['no_review_issues']==1
assert result['by_domain']['D2']['waiting']==1
assert result['next_ids']==['Q2']
assert result['quality_hold_originals']==1
assert result['campaign_remaining_calls']==147
assert result['today_used_calls']==22 and result['today_remaining_calls']==3
assert result['original_questions_modified'] is False
assert result['auto_approval_enabled'] is False
out=io.StringIO()
with redirect_stdout(out):
    assert ns['revision_status']()==0
view=json.loads(out.getvalue())
assert view==result
assert FakeA.reads==1 and FakeA.writes==0
for private in ('PRIVATE_QUESTION_TEXT','PRIVATE_REVISED_QUESTION',
                'PRIVATE_REVIEW_NOTE'):
    assert private not in out.getvalue(),private
assert before==json.dumps(FakeA.state,sort_keys=True)
assert "if sys.argv[1:]==['revision-status']" in src
print('PASS read-only backlog, attempted and held counts, budget, no private content')
