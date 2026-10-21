"""No API calls: test campaign budget reservation and stop after 150 requests."""
import ast
from pathlib import Path

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'campaign_budget_remaining','reserve_campaign_api_request'}
parts=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
assert len(parts)==2
class A:
    STATEFILE='dummy'
    saved=[]
    @classmethod
    def jwrite(cls,path,state):
        cls.saved.append((state['campaign_budget_1000jpy']['reserved_calls'],state['campaign_budget_1000jpy']['estimated_reserved_jpy']))
ns={'CAMPAIGN_MAX_CALLS':150,'CAMPAIGN_RESERVE_JPY_PER_CALL':5,'a':A}
exec(compile(ast.Module(body=parts,type_ignores=[]),'<budget-test>','exec'),ns)
state={'campaign_budget_1000jpy_enabled':True}
assert ns['campaign_budget_remaining'](state)==150
for i in range(150):
    ns['reserve_campaign_api_request'](state)
    assert ns['campaign_budget_remaining'](state)==149-i
assert len(A.saved)==150 and A.saved[-1]==(150,750)
try:
    ns['reserve_campaign_api_request'](state)
    assert False,'must stop at 150'
except RuntimeError:
    pass
assert len(A.saved)==150
assert ns['campaign_budget_remaining']({'campaign_budget_1000jpy':{'reserved_calls':150}})==0
assert "not state.get('campaign_budget_1000jpy_enabled',False)" in src
assert 'api.call=budgeted_call' in src
print('PASS cumulative budget reservations, restart persistence, stop and opt-in')
