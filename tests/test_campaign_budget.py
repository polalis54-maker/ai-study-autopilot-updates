"""Offline budget test: cumulative and per-day reservations survive interrupted runs."""
import ast
from pathlib import Path

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'campaign_budget_remaining','reserve_campaign_api_request','history_calls_today','used_today'}
parts=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
assert len(parts)==len(wanted)

class A:
    STATEFILE='dummy'
    saved=[]
    day='2026-10-21'
    @classmethod
    def today(cls):return cls.day
    @classmethod
    def jwrite(cls,path,state):
        ledger=state['campaign_budget_1000jpy']
        cls.saved.append((ledger['reserved_calls'],ledger['estimated_reserved_jpy']))
ns={'CAMPAIGN_MAX_CALLS':150,'CAMPAIGN_RESERVE_JPY_PER_CALL':5,
    'daily_call_cap':lambda day=None:25,'a':A}
exec(compile(ast.Module(body=parts,type_ignores=[]),'<budget-test>','exec'),ns)
state={'campaign_budget_1000jpy_enabled':True,
       'history':[{'date':'2026-10-21','calls':22}]}
assert ns['used_today'](state)==22
for _ in range(3):ns['reserve_campaign_api_request'](state)
assert ns['used_today'](state)==25
assert state['campaign_budget_1000jpy']['daily_baseline']['2026-10-21']==22
assert state['campaign_budget_1000jpy']['daily_reserved']['2026-10-21']==3
# Restart after a crash, with history still at 22, must not permit a 26th request.
try:
    ns['reserve_campaign_api_request'](state)
    assert False,'day cap bypassed'
except RuntimeError:pass
assert len(A.saved)==3
# Adding successfully completed calls to the history must not double count.
state['history'].append({'date':'2026-10-21','calls':3})
assert ns['used_today'](state)==25
# Over six 25-call days, test the independent cumulative 150-request cap.
state={'campaign_budget_1000jpy_enabled':True}
A.saved=[]
for day in range(6):
    A.day=f'2026-10-{day+21:02}'
    for i in range(25):
        ns['reserve_campaign_api_request'](state)
        assert ns['used_today'](state)==i+1
        assert ns['campaign_budget_remaining'](state)==150-(day*25+i+1)
assert A.saved[-1]==(150,750)
A.day='2026-11-01'
try:
    ns['reserve_campaign_api_request'](state)
    assert False,'cumulative cap bypassed'
except RuntimeError:pass
assert len(A.saved)==150
# Missing opt-in and corrupt ledgers are fail-closed.
for state in ({}, {'campaign_budget_1000jpy_enabled':False}):
    try:ns['reserve_campaign_api_request'](state);assert False
    except RuntimeError:pass
for val in (-1,'unknown'):
    bad={'campaign_budget_1000jpy_enabled':True,
         'campaign_budget_1000jpy':{'reserved_calls':0,
                                     'daily_reserved':{A.day:val}}}
    try:ns['reserve_campaign_api_request'](bad);assert False
    except ValueError:pass
assert "not state.get('campaign_budget_1000jpy_enabled',False)" in src
assert 'api.call=budgeted_call' in src
print('PASS cumulative/day-level reservations, crash survival, restart, opt-in')
