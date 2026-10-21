"""Offline acceptance: real supply controller + delivery, fake provider boundary only."""
import copy
import datetime
import hashlib
import importlib.util
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path('release_files').resolve()))
import live_progress as lp

day=['2026-10-22']
class Clock:
    @staticmethod
    def now():return datetime.datetime.fromisoformat(day[0]+'T12:00:00+09:00')
lp.datetime=SimpleNamespace(date=datetime.date,datetime=Clock)
fake_a=SimpleNamespace(REVIEW_PROMPT='Review',Clients=object,today=lambda:day[0])
fake_ua=SimpleNamespace(UPDATES=Path('unused'),windows_lock=lambda p:object(),release_lock=lambda lock:None,check_and_apply=lambda:None)
sys.modules['autopilot']=fake_a
sys.modules['update_agent']=fake_ua
spec=importlib.util.spec_from_file_location('watchdog','release_files/update_watchdog.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

def read(path,default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else copy.deepcopy(default)

def question(spec):
    # Synthetic varied decision text; never real exam content or model claims.
    salt=' '.join(hashlib.sha256((spec['id']+str(i)).encode()).hexdigest() for i in range(3))
    return dict(spec,exam='SAA-C03',question='合成テスト用シナリオ。可用性とコストの要件を検討してください。'+salt+(' 2つ選択' if spec['type']=='multiple' else ''),
                choices={k:'選択肢 '+k+' '+salt[i*20:i*20+20] for i,k in enumerate('ABCDE' if spec['type']=='multiple' else 'ABCD')},
                correct=['A','B'] if spec['type']=='multiple' else ['A'],
                explanation=''.join('【'+k+'】この選択肢の正誤理由は合成テスト専用の説明です。' for k in ('ABCDE' if spec['type']=='multiple' else 'ABCD')))

class Provider:
    requests=[]
    fail=None
    def __init__(self,*keys,limit=25):self.calls=0;self.limit=limit
    def call(self,provider,prompt,payload):
        assert self.calls<self.limit
        self.calls+=1;self.requests.append(provider)
        if self.fail:
            failure=self.fail;Provider.fail=None;raise failure
        if provider=='openai':return {'questions':[question(s) for s in payload['specs']]}
        return {'reviews':[{'id':q['id'],'verdict':'PASS','issues':[],
                            'exam_quality':{'distractor_quality':3,'scenario_realism':3,'explanation_depth':3,'difficulty_alignment':3}}
                           for q in payload['questions']]}

fake_a.jread=read;fake_a.jwrite=lp.save_json;fake_a.state_default=lambda:{}
fake_a.load_keys=lambda:('MOCK_ONLY','MOCK_ONLY')
fake_a.validate=lambda q,strict=False:q
fake_a.validate_review=lambda r:None
fake_a.meets_exam_quality=lambda r:True
w.API=Provider;w.time.sleep=lambda seconds:None

def setup(root):
    work=root/'work';work.mkdir();(work/'outputs').mkdir()
    w.ROOT=root;w.STOP=work/'stop_requested';fake_a.STATEFILE=work/'state.json';fake_a.STUDY_FILE=root/'questions.json'
    lp.save_json(fake_a.STUDY_FILE,{'questions':[{'id':'original','question':'original bank'}]})
    state={'campaign_budget_1000jpy_enabled':True,'campaign_budget_1000jpy':{'reserved_calls':0},
           'generated_index':256,'generated':{f'SAA-AUTO-{i:05d}':{'status':'QUALITY_HOLD' if i<=22 else 'AI_PASS'} for i in range(1,257)},
           'existing':{'old':{'status':'AI_PASS'}},'pending':{},'history':[],
           'revision_trials':{'private':{'status':'REVISION_REQUESTED'}},'revision_trial_history':{'private':['preserve']},
           'trophies':{'keep':True},'attempts':[{'keep':True}]}
    lp.save_json(fake_a.STATEFILE,state)
    lp.save_json(work/'practice_delivery.json',{'delivered_ids':[f'SAA-AUTO-{i:05d}' for i in range(1,15)]})
    lp.save_json(work/'supply_campaign.json',{'enabled':True,'start':'2026-10-22','stop':'2026-11-30','billing_checked_until':'2026-11-30',
           'target':500,'daily_delivery_target':100,'batch_size':10,'daily_call_cap':25,'call_cap':150,'budget_jpy':1000,
           'billing_acknowledgement':'provider billing checked; reservations are not actual charges'})
    return state

class Crash(BaseException):pass

with patch('urllib.request.urlopen',side_effect=AssertionError('Real HTTP forbidden')):
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);initial=setup(root)
        original=fake_a.STUDY_FILE.read_bytes()
        assert lp.prepare_supply_practice(root)['delivered_total']==0
        old_ledger=(root/'work'/'practice_delivery.json').read_bytes()
        for n in range(5):
            day[0]=f'2026-10-{22+n}'
            assert w.run_supply()==0
            report=lp.prepare_supply_practice(root)
            assert report['new_questions']==100,report
            assert report['delivered_total']==(n+1)*100,report
            calls=len(Provider.requests)
            assert w.run_supply()==0 and len(Provider.requests)==calls
        ledger=read(root/'work'/'supply_delivery.json')
        assert len(ledger['receipts'])==500
        assert Counter(r['domain'] for r in ledger['receipts'].values())=={'D1':150,'D2':130,'D3':120,'D4':100}
        assert len(set().union(*({q['id'] for q in deck} for deck in ledger['days'].values())))==500
        after=read(fake_a.STATEFILE)
        for key in ('existing','revision_trials','revision_trial_history','trophies','attempts'):
            assert after[key]==initial[key]
        for uid,value in initial['generated'].items():assert after['generated'][uid]==value
        assert after['campaign_budget_1000jpy']['reserved_calls']==100
        assert all(value<=25 for value in after['campaign_budget_1000jpy']['daily_reserved'].values())
        assert fake_a.STUDY_FILE.read_bytes()==original
        assert (root/'work'/'practice_delivery.json').read_bytes()==old_ledger
        assert not (root/'work'/'content_approvals.json').exists()

    # Cached response and write-ahead deck survive process death at every boundary.
    for boundary in ('openai','gemini','deck','inflight'):
        with tempfile.TemporaryDirectory() as directory:
            day[0]='2026-10-22';root=Path(directory);setup(root)
            lp.prepare_supply_practice(root)
            fired=[False];save=lp.save_json
            def crash_save(path,data):
                save(path,data)
                jobs=data.get('supply_jobs',[]) if isinstance(data,dict) else []
                trigger=(boundary in ('openai','gemini') and jobs and boundary+'_response' in jobs[-1])
                trigger=trigger or (boundary=='deck' and Path(path).name=='supply_delivery.json' and data['receipts'])
                if trigger and not fired[0]:fired[0]=True;raise Crash()
            if boundary=='inflight':Provider.fail=Crash()
            try:
                with patch.object(lp,'save_json',crash_save):w.run_supply()
            except Crash:pass
            assert w.run_supply()==0,boundary
            report=lp.prepare_supply_practice(root)
            assert report['new_questions']==100 and report['delivered_total']==100,(boundary,report)
            state=read(fake_a.STATEFILE)
            expected=21 if boundary=='inflight' else 20
            assert state['campaign_budget_1000jpy']['reserved_calls']==expected,(boundary,state['campaign_budget_1000jpy'])

    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);setup(root);lp.prepare_supply_practice(root)
        state=read(fake_a.STATEFILE);state['campaign_budget_1000jpy']['reserved_calls']=150
        lp.save_json(fake_a.STATEFILE,state);before=len(Provider.requests)
        assert w.run_supply()==0 and len(Provider.requests)==before
        assert '予算' in read(root/'work'/'outputs'/'supply_run.json')['reason']
        state.pop('campaign_budget_1000jpy');lp.save_json(fake_a.STATEFILE,state)
        assert w.run_supply()==0 and len(Provider.requests)==before

    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);setup(root);lp.prepare_supply_practice(root)
        Provider.fail=TimeoutError('mock');assert w.run_supply()==0
        assert read(fake_a.STATEFILE)['campaign_budget_1000jpy']['reserved_calls']==21

    # Malformed data and transport rejection never spend without a finite bound.
    original_call=Provider.call
    for mode in ('malformed','review','429','duplicate'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);setup(root);lp.prepare_supply_practice(root)
            def bad_call(self,provider,prompt,payload):
                self.calls+=1;self.requests.append(provider)
                if mode=='429':raise RuntimeError('HTTP 429')
                if mode=='malformed':return ['not an object']
                if provider=='gemini' and mode=='review':return {'reviews':[]}
                self.calls-=1;self.requests.pop()
                reply=original_call(self,provider,prompt,payload)
                if mode=='duplicate' and provider=='openai':
                    for item in reply['questions']:
                        item['question']='同一シナリオを繰り返す合成テスト。可用性とコストの要件を検討してください。'
                        item['choices']={k:'同一選択肢'+k for k in item['choices']}
                return reply
            with patch.object(Provider,'call',bad_call):
                result=w.run_supply()
                reserved=read(fake_a.STATEFILE)['campaign_budget_1000jpy']['reserved_calls']
                assert 1<=reserved<=4,(mode,reserved)
                before=len(Provider.requests)
                w.run_supply();assert len(Provider.requests)==before,mode
                report=lp.prepare_supply_practice(root)
                assert report['delivered_total']<=2,(mode,report)

    # Calendar/billing expiry, stop switch and single instance all prohibit calls.
    for block in ('expired','stop','busy','daily'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);setup(root);lp.prepare_supply_practice(root)
            if block=='expired':
                config=read(root/'work'/'supply_campaign.json');config['billing_checked_until']='2026-10-21'
                lp.save_json(root/'work'/'supply_campaign.json',config)
            if block=='stop':w.STOP.touch()
            if block=='daily':
                state=read(fake_a.STATEFILE)
                state['campaign_budget_1000jpy']['daily_reserved']={day[0]:25}
                lp.save_json(fake_a.STATEFILE,state)
            before=len(Provider.requests)
            with patch.object(fake_ua,'windows_lock',lambda p:None if block=='busy' else object()):w.run_supply()
            assert len(Provider.requests)==before,block

q=question({'id':'SAA-AUTO-00020','domain':'D2','topic':'SQS','type':'single','difficulty':'中級'})
q['explanation']+='SQS クロスリージョンのクローン機能で複製する。FIFOはスケールできない。'
assert lp.supply_quality_error(q)
q['explanation']='【A】だけ説明しています。他の選択肢の説明はありません。'
assert lp.supply_quality_error(q)
assert "run_daily(campaign=True)" in Path('release_files/update_watchdog.py').read_text(encoding='utf-8')
print('PASS: 500 unique delivered across five days; baseline/quality/budget/privacy; crash replay; timeout retry; false PASS guard')
