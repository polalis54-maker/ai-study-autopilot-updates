"""Offline daily growth test: new provisional questions at wakeup, no bank mutation."""
import copy
import importlib.util
import json
import re
import tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('lp','release_files/live_progress.py')
lp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)

def q(num):
    return {'id':f'SAA-AUTO-{num:05d}','exam':'SAA-C03','domain':'D2',
            'type':'single','difficulty':'中級','topic':'Storage',
            'question':'AWS上のWebシステムを運用しています。障害時の可用性とコストを考え、最適なストレージ設計を1つ選択してください。',
            'choices':{'A':'S3','B':'EBS','C':'EFS','D':'Storage Gateway'},
            'correct':['A'],
            'explanation':'【A】S3は耐久性のあるオブジェクトストレージです。【B】EBSはEC2向けブロックストレージです。【C】EFSは共有ファイルストレージです。【D】Storage Gatewayはハイブリッド連携に用います。'}
def record(n, status='QUALITY_HOLD', review='PASS'):
    return {'status':status,'candidate':q(n),
            'audit':[{'review':{'verdict':review,'issues':[]}}]}

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    (root/'work').mkdir()
    study=root/'AI_Study'
    study.mkdir()
    (study/'questions.json').write_text('{"questions":[{"id":"existing"}]}',encoding='utf8')
    (study/'index.html').write_text('<p>previous learning data preserved</p>',encoding='utf8')
    (study/'sw.js').write_text("const CACHE='ai-study-old';",encoding='utf8')
    originals={p.name:p.read_bytes() for p in study.iterdir()}
    state={'generated':{q(i)['id']:record(i) for i in range(10,29)},
           'revision_trials':{q(10)['id']:{'status':'REVISION_REQUESTED'}},
           'api_keys':{'openai':'PRIVATE_NEVER_EXPORT'},
           'existing':{'existing':{'status':'AI_PASS'}}}
    state['generated'][q(11)['id']]=record(11,'REVISE_UNRESOLVED','REVISE')
    state['generated'][q(12)['id']]=record(12,'QUALITY_HOLD','REVISE')
    with (root/'work'/'state.json').open('w',encoding='utf8') as fh:
        json.dump(state,fh,ensure_ascii=False)
    source_bytes=(root/'work'/'state.json').read_bytes()
    first=lp.prepare_daily_practice(root,today='2026-10-22',max_questions=12)
    assert first['status']=='READY' and first['new_questions']==12,first
    assert first['held_unseen_remaining']==4,first
    file=Path(first['path'])
    assert file.is_file()
    body=file.read_text(encoding='utf8')
    assert '公式未検証' in body
    assert 'PRIVATE_NEVER_EXPORT' not in body
    assert 'localStorage' not in body and 'fetch(' not in body
    assert '2026-10-22' in body
    matches=re.search(r'const questions=(.*?);\nlet index=',body,re.S)
    assert matches
    first_ids=[x['id'] for x in json.loads(matches.group(1))]
    assert len(first_ids)==12 and q(10)['id'] not in first_ids
    assert q(11)['id'] not in first_ids and q(12)['id'] not in first_ids
    saved=file.read_bytes()
    again=lp.prepare_daily_practice(root,today='2026-10-22',max_questions=12)
    assert again['status']=='ALREADY_READY' and again['new_questions']==12
    assert file.read_bytes()==saved
    next_day=lp.prepare_daily_practice(root,today='2026-10-23',max_questions=12)
    assert next_day['status']=='READY' and next_day['new_questions']==4,next_day
    matches=re.search(r'const questions=(.*?);\nlet index=',file.read_text(encoding='utf8'),re.S)
    second_ids=[x['id'] for x in json.loads(matches.group(1))]
    assert not set(first_ids)&set(second_ids)
    assert lp.prepare_daily_practice(root,today='2026-10-24')['status']=='NO_NEW'
    assert '新規問題は0問' in file.read_text(encoding='utf8')
    assert json.loads((root/'work'/'practice_delivery.json').read_text())['date']=='2026-10-24'
    assert (root/'work'/'state.json').read_bytes()==source_bytes
    assert {p.name:p.read_bytes() for p in study.iterdir()}==originals
    assert not (root/'work'/'content_approvals.json').exists()
    state['generated'][q(29)['id']]=record(29)
    (root/'work'/'state.json').write_text(json.dumps(state),encoding='utf8')
    new=lp.prepare_daily_practice(root,today='2026-10-25')
    assert new['new_questions']==1,new
    assert q(29)['id'] in file.read_text(encoding='utf8')
print('PASS: capped daily new sets, no repeats, no network, strict holds, state and study history preserved')
