"""Campaign 200 goal and daily request-cap regression, no network or API calls."""
import ast
from pathlib import Path
from types import SimpleNamespace

source=Path('release_files/update_watchdog.py').read_text(encoding='utf-8')
tree=ast.parse(source)
functions={x.name:x for x in tree.body if isinstance(x,ast.FunctionDef)}
wanted=['daily_call_cap','count_approved','existing_approved','goal_progress',
        'used_today','campaign_due']
for n in wanted:
    assert n in functions,n
scope={'CAMPAIGN_START':'2026-10-19','CUTOFF':'2026-10-28',
       'GOAL_TOTAL':200,'CAMPAIGN_DAILY_CAP':100,
       'CALL_CAP':25,'ONE_TIME_EXTRA_DATE':'2026-10-18','ONE_TIME_EXTRA_LIMIT':50}
day=['2026-10-19']
scope['a']=SimpleNamespace(today=lambda:day[0])
module=ast.fix_missing_locations(ast.Module(body=[functions[n] for n in wanted],type_ignores=[]))
exec(compile(module,'<campaign tests>','exec'),scope)

cap=scope['daily_call_cap']
assert cap('2026-10-17')==25
assert cap('2026-10-18')==50
assert cap('2026-10-19')==100
assert cap('2026-10-28')==100
assert cap('2026-10-29')==25

s={'last_attempt':'2026-10-19',
   'existing':{'A':{'status':'AI_PASS'},'B':{'status':'REVISE_UNRESOLVED'}},
   'generated':{'C':{'status':'AI_PASS'},'D':{'status':'BLOCKED'}},
   'history':[{'date':'2026-10-19','calls':23,'errors':['HTTP 400']}]}
assert scope['goal_progress'](s)==2, 'Never count unresolved or unreviewed'
assert scope['used_today'](s)==23
assert scope['campaign_due'](s),'A prior run may continue within daily budget'
s['history'].append({'date':'2026-10-19','calls':75,'errors':[]})
assert not scope['campaign_due'](s),'Only 2 requests remain'
s['history'][-1]['calls']=50
s['campaign_paused_date']='2026-10-19'
assert not scope['campaign_due'](s),'A stall blocks repeated spending'
s.pop('campaign_paused_date')
s['generated'].update({str(x):{'status':'AI_PASS'} for x in range(198)})
assert scope['goal_progress'](s)==200
assert not scope['campaign_due'](s),'200 PASS means stop'
s['generated'].pop('0')
assert scope['goal_progress'](s)==199
assert scope['campaign_due'](s),'Below goal must continue while budget remains'
day[0]='2026-10-29'
assert not scope['campaign_due'](s),'Never spend after exam preparation deadline'
day[0]='2026-10-18'
assert not scope['campaign_due'](s),'Campaign must not retroactively spend prior date'

assert 'GEN_DAILY=200' in source, 'Do not silently cap at twenty attempts'
assert "and goal_progress(state)<GOAL_TOTAL" in source, 'Stop at goal in-batch'
assert "'campaign_paused_date'" in source
assert 'campaign_due(_read_obj(ROOT/' in source
assert "batch-new-only' if (post_fix or campaign)" in source
assert 'GOAL_TOTAL-goal_progress(state)' in source
print('PASS: Gemini-only approved goal, date-scoped 100/day, reuse remaining budget, stop at 200, no-progress pause')
