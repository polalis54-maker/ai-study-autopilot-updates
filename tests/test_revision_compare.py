"""Read-only local review of original/revised content, never API/network/write."""
import ast
import copy
import io
import json
import re
from pathlib import Path
from contextlib import redirect_stdout

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
functions={'revision_comparison','revision_compare'}
picked=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in functions]
const=[n for n in tree.body if isinstance(n,ast.Assign) and
       any(isinstance(t,ast.Name) and t.id=='REVISION_REVIEW_FIELDS'
           for t in n.targets)]
assert len(picked)==2 and len(const)==1
id='SAA-AUTO-00020'
class A:
    STATEFILE='test-state.json'
    state={}
    calls=0
    @staticmethod
    def state_default():return {}
    @classmethod
    def jread(cls,*args):
        cls.calls+=1
        return cls.state
    @staticmethod
    def jwrite(*args):
        raise AssertionError('comparison must never write')
ns={'json':json,'re':re,'a':A}
exec(compile(ast.Module(body=const+picked,type_ignores=[]),
             '<compare>','exec'),ns)
A.state={
 'generated':{id:{'status':'REVISE_UNRESOLVED',
      'candidate':{'id':id,'exam':'SAA-C03','domain':'D2',
                   'question':'Old question','choices':['old A','old B'],
                   'correct':['A'],'explanation':'old rationale',
                   'source':{'token':'SENSITIVE_SOURCE_METADATA'}},
      'audit':[{'review':{'issues':['Review the old explanation'],
                          'notes':'old notes'}}]}},
 'revision_trials':{id:{'status':'REVIEWED_HOLD','human_approved':False,
      'candidate':{'id':id,'exam':'SAA-C03','domain':'D2',
                   'question':'New question','choices':['new A','new B'],
                   'correct':['B'],'explanation':'new rationale',
                   'secret_metadata':'SENSITIVE_TOKEN'},
      'review':{'verdict':'PASS','issues':[],'notes':'Recheck AWS docs',
                'exam_quality':{'reason':'scenario'}}}}
}
before=copy.deepcopy(A.state)
result=ns['revision_comparison'](A.state,id)
assert result['id']==id
assert result['revision_status']=='REVIEWED_HOLD'
assert result['original']['question']=='Old question'
assert result['original']['correct']==['A']
assert result['revision']['question']=='New question'
assert result['revision']['correct']==['B']
assert result['revision_review']['verdict']=='PASS'
assert result['original_review_issues']==['Review the old explanation']
assert result['human_approved'] is False
assert result['official_documentation_verified'] is False
assert 'source' not in result['original']
assert 'secret_metadata' not in result['revision']
assert A.state==before
buffer=io.StringIO()
with redirect_stdout(buffer):
    assert ns['revision_compare'](id)==0
printed=json.loads(buffer.getvalue())
assert printed==result
assert 'SENSITIVE_TOKEN' not in buffer.getvalue()
assert 'SENSITIVE_SOURCE_METADATA' not in buffer.getvalue()
assert A.calls==1 and A.state==before
for bad_id in ('SAA-AUTO-1','wrong','SAA-AUTO-00021','../../../secrets'):
    buf=io.StringIO()
    with redirect_stdout(buf):
        assert ns['revision_compare'](bad_id)==2
    assert not buf.getvalue().startswith('{')
# Failed revisions remain visible without inventing a revised question.
A.state['revision_trials'][id]={'status':'REVISION_ERROR','error':'timeout'}
out=ns['revision_comparison'](A.state,id)
assert out['revision'] is None
assert out['revision_review']['verdict'] is None
assert "if len(sys.argv)==3 and sys.argv[1]=='revision-compare'" in src
print('PASS local original/revision compare, rejected IDs, error trials, data unchanged')
