"""Offline revision queue tests, no API requests or state writes."""
import ast
from pathlib import Path
s=Path('release_files/update_watchdog.py').read_text(encoding='utf-8')
tree=ast.parse(s)
fns=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='revision_queue']
assert len(fns)==1
ns={}
exec(compile(ast.Module(body=fns,type_ignores=[]),'<revision_queue>','exec'),ns)
q={'id':'A','domain':'D1','topic':'IAM','question':'test'}
s1={'generated':{'A':{'candidate':q,'status':'REVISE_UNRESOLVED','audit':[{'review':{'issues':[{'detail':'wrong answer'}]}}]},
                 'B':{'candidate':{'id':'B','domain':'D3','topic':'S3','question':'ok'},'status':'AI_PASS'}}}
result=ns['revision_queue'](s1)
assert len(result)==1 and result[0]['id']=='A' and len(result[0]['issues'])==1
assert s1['generated']['A']['status']=='REVISE_UNRESOLVED'
assert "state.setdefault('revision_trials',{})[target['id']]=result" in s
assert "reserve_campaign_api_request(state)" in s
assert "if sys.argv[1:]==['revision-preview']" in s
assert "if sys.argv[1:]==['revision-one']" in s
print('PASS revision preview queue and isolated repair wiring')
