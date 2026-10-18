#!/usr/bin/env python3
"""Safe unattended updater/watchdog and bounded SAA batch question creator.
The watched machine must be awake. No deployment to Netlify; no secret uploads.
"""
from __future__ import annotations
import datetime, json, os, subprocess, sys, time
from pathlib import Path
import autopilot as a
import update_agent as ua

ROOT=Path(__file__).resolve().parent
LOG=ROOT/'work'/'outputs'/'scheduler.log'
STOP=ROOT/'work'/'stop_requested'
LOCK=ROOT/'work'/'autopilot.lock'
REQUEST=ua.UPDATES/'check_requested'
UPDATE_INTERVAL_SEC=3600
CUTOFF='2026-10-28'
GROUP=2
GEN_DAILY=20
REV_DAILY=5
CALL_CAP=25

G_PROMPT='''AWS SAA-C03のオリジナル日本語模擬試験を生成。specsと同じ件数を返す。中〜上級の実務シナリオ。可用性・コスト・運用負荷・DRなどの制約を2つ以上含め、誤答ももっともらしく。全選択肢の正誤理由を解説。公式問題を転載しない。JSONのみ: {"questions":[{"id":"指定ID","exam":"SAA-C03","domain":"D1","topic":"...","type":"single","question":"...","choices":{"A":"...","B":"...","C":"...","D":"..."},"correct":["A"],"explanation":"...","difficulty":"中級","language":"ja","review_status":"ai_review_pending","source":{"kind":"original","label":"AI Study Auto-generated / AI review pending"}}]} singleは4択1正解、multipleは5択2正解で問題文に「2つ選択」を明記。すべてのIDと属性を守り、省略しない。'''
R_PROMPT=a.REVIEW_PROMPT.split('JSONオブジェクトだけ返答:')[0]+'''\n各questionsを独立かつ厳格にレビュー。全問題IDについて回答し、資料を調べたと偽らない。JSONのみ: {"reviews":[{"id":"指定ID","verdict":"PASS|REVISE|BLOCK","issues":[],"notes":"...","needs_official_verification":true,"exam_quality":{"distractor_quality":3,"scenario_realism":3,"explanation_depth":3,"difficulty_alignment":3,"reason":"..."}}]}'''

class API(a.Clients):
    def fake(self, provider, prompt, payload):
        if prompt==G_PROMPT:
            qs=[]
            for spec in payload['specs']:
                q=super().fake('openai',a.GEN_PROMPT,spec)
                q['difficulty']=spec['difficulty']
                if spec['type']=='multiple':q['question']+=' 【2つ選択】'
                qs.append(q)
            return {'questions':qs}
        if prompt==R_PROMPT:
            return {'reviews':[{'id':q['id'],**super().fake('gemini',a.REVIEW_PROMPT,q)} for q in payload['questions']]}
        return super().fake(provider,prompt,payload)

def specs_for(state,n):
    specs=[]
    for ix in range(state['generated_index'],state['generated_index']+n):
        d,t=a.TOPICS[ix%len(a.TOPICS)]
        specs.append({'id':f'SAA-AUTO-{ix+1:05d}','domain':d,'topic':t,
                      'type':'multiple' if ix%4==3 else 'single',
                      'difficulty':'上級' if ix%3==2 else '中級'})
    return specs

def make(api,specs):
    wanted={s['id']:s for s in specs}
    for attempt in range(2):
        try:
            response=api.call('openai',G_PROMPT,{'specs':specs,'retry_format':attempt>0})
            qs=response.get('questions')
            if not isinstance(qs,list) or len(qs)!=len(specs):raise ValueError('生成数不一致')
            ids=[q.get('id') for q in qs if isinstance(q,dict)]
            if len(ids)!=len(specs) or set(ids)!=set(wanted) or len(set(ids))!=len(ids):
                raise ValueError('問題IDが欠落・重複')
            for q in qs:
                a.validate(q,strict=True)
                s=wanted[q['id']]
                if (q['exam']!='SAA-C03' or q['type']!=s['type'] or q['domain']!=s['domain'] or q['difficulty']!=s['difficulty']):
                    raise ValueError('分野・難易度・形式が不一致')
                if q['type']=='multiple' and not any(x in q['question'] for x in ('2つ','２つ','二つ','2 つ')):
                    raise ValueError('複数選択の正解数が問題文に未記載')
                q['source']={'kind':'original','label':'AI Study Auto-generated / AI review pending'}
                q['review_status']='ai_review_pending'
            return qs
        except (ValueError,KeyError,TypeError):
            if attempt:raise
    return []

def judge(api,qs):
    for attempt in range(2):
        try:
            d=api.call('gemini',R_PROMPT,{'questions':qs,'retry_format':attempt>0})
            r=d.get('reviews')
            if not isinstance(r,list) or len(r)!=len(qs):raise ValueError('レビュー件数不一致')
            ids=[x.get('id') for x in r if isinstance(x,dict)]
            if len(ids)!=len(qs) or set(ids)!={q['id'] for q in qs} or len(set(ids))!=len(ids):
                raise ValueError('レビューIDが不一致')
            for x in r:a.validate_review(x)
            return {x['id']:x for x in r}
        except (ValueError,KeyError,TypeError):
            if attempt:raise
    return {}

def run_fast(*,demo=False,force=False):
    if a.today()>CUTOFF and not demo:
        print('10/28を過ぎたため生成停止');return 0
    existing=a.jread(a.STUDY_FILE)['questions']
    for q in existing:a.validate(q)
    state=a.jread(a.STATEFILE,a.state_default())
    state.setdefault('pending',{})
    state.setdefault('failed_generations',{})
    if not demo and state['last_attempt']==a.today() and not force:
        print('今日は既に実行済み。API呼び出しなし');return 0
    keys=('', '') if demo else a.load_keys()
    if not demo:
        state['last_attempt']=a.today()
        a.jwrite(a.STATEFILE,state)
    api=API(*keys,limit=CALL_CAP,demo=demo)
    log=[];errors=[];reviewed=0;generated=0
    def checkpoint():
        if not demo:a.jwrite(a.STATEFILE,state)
    def progress(status,phase,details=''):
        print('[FAST]',status,phase,details,flush=True)
        if not demo:a.update_live_progress(a.OUT,status=status,phase=phase,detail=details,calls=api.calls,
            existing=len(state['existing']),generated=len(state['generated']),
            passed_existing=sum(v['status']=='AI_PASS' for v in state['existing'].values()),
            passed_generated=sum(v['status']=='AI_PASS' for v in state['generated'].values()),
            mode='高速バッチ',goal_existing=REV_DAILY,goal_generated=GEN_DAILY,
            error=details if status=='ERROR' else '')
    def keep(q,review,part):
        status={'BLOCK':'BLOCKED','REVISE':'REVISE_UNRESOLVED'}.get(review['verdict'])
        if status is None:status='AI_PASS' if part=='existing' or a.meets_exam_quality(review) else 'NEEDS_QUALITY_UPGRADE'
        state[part][q['id']]={'status':status,'candidate':q,'audit':[{'role':'gemini','review':review}],
                              'official_documentation_verified':False,'human_approved':False}
        log.append(q['id']+': '+status)
    def review_safe(group):
        try:return judge(api,group)
        except (ValueError,TypeError,KeyError) as exc:
            if len(group)==1:
                errors.append(group[0]['id']+': Geminiのレビュー形式不備: '+str(exc)[:150]);return {}
            cut=len(group)//2
            return {**review_safe(group[:cut]),**review_safe(group[cut:])}
    def make_safe(group):
        try:return make(api,group)
        except (ValueError,TypeError,KeyError) as exc:
            if len(group)==1:
                state['failed_generations'][group[0]['id']]={'date':a.today(),'reason':str(exc)[:200]}
                errors.append(group[0]['id']+': 生成形式不備: '+str(exc)[:150]);return []
            cut=len(group)//2
            return make_safe(group[:cut])+make_safe(group[cut:])
    progress('RUNNING','既存レビューと新規問題生成を開始')
    try:
        missing=[q for q in existing if q['id'] not in state['existing'] and q['id'] not in state['generated']][:REV_DAILY]
        for start in range(0,len(missing),GROUP):
            if api.calls+2>CALL_CAP:break
            group=missing[start:start+GROUP]
            progress('RUNNING','Gemini既存レビュー',str([q['id'] for q in group]))
            results=review_safe(group)
            for q in group:
                if q['id'] in results:
                    keep(q,results[q['id']],'existing');reviewed+=1
            while state['review_index']<len(existing) and existing[state['review_index']]['id'] in state['existing']:
                state['review_index']+=1
            checkpoint()
        # Resume previously generated but never-reviewed proposals first.
        pending_ids=list(state['pending'])
        for start in range(0,len(pending_ids),GROUP):
            if api.calls+2>CALL_CAP:break
            group=[state['pending'][i] for i in pending_ids[start:start+GROUP] if i in state['pending']]
            if not group:continue
            results=review_safe(group)
            for q in group:
                if q['id'] in results:
                    keep(q,results[q['id']],'generated');state['pending'].pop(q['id'],None);generated+=1
            checkpoint()
        attempted=0
        while attempted<GEN_DAILY and api.calls+4<=CALL_CAP:
            group=specs_for(state,min(GROUP,GEN_DAILY-attempted))
            progress('RUNNING','OpenAI一括生成',str([s['id'] for s in group]))
            proposals=make_safe(group)
            state['generated_index']+=len(group);attempted+=len(group)
            for q in proposals:state['pending'][q['id']]=q
            checkpoint()  # Never lose proposals that already incurred an API call
            if not proposals:continue
            results=review_safe(proposals)
            for q in proposals:
                if q['id'] not in results:continue
                keep(q,results[q['id']],'generated');state['pending'].pop(q['id'],None);generated+=1
                state['failed_generations'].pop(q['id'],None)
            checkpoint()
            progress('RUNNING','Gemini新規レビュー',f'今回{generated}問')
        # Fix weak or REVISE-flagged *new* questions once, then ask Gemini again.
        for qid, entry in list(state['generated'].items())[-GEN_DAILY:]:
            if api.calls+3>CALL_CAP:break
            if entry['status'] not in ('REVISE_UNRESOLVED','NEEDS_QUALITY_UPGRADE'):continue
            r=entry['audit'][0]['review']
            if r['verdict']=='PASS':
                r=dict(r,verdict='REVISE',issues=[{
                    'severity':'major','dimension':'scenario','detail':'試験品質スコアが不足',
                    'suggestion':'シナリオ制約、選択肢と全誤答解説を改善'}])
            source=entry['candidate']
            try:
                candidate=a.validate(api.call('openai',a.FIX_PROMPT,{'question':source,'review':r}),strict=True)
                if any(candidate[k]!=source[k] for k in ('id','exam','type','source')):
                    raise ValueError('修正時にID・形式・出典が変更')
                again=judge(api,[candidate])[qid]
                entry['audit'].extend([{'role':'openai','action':'fix_once'},
                                       {'role':'gemini','review':again,'iteration':1}])
                if again['verdict']=='PASS' and a.meets_exam_quality(again):
                    entry['candidate']=candidate;entry['status']='AI_PASS'
                elif again['verdict']=='BLOCK':entry['status']='BLOCKED'
                checkpoint()
            except (ValueError,KeyError,TypeError) as exc:
                entry['audit'].append({'role':'openai','action':'fix_rejected','reason':str(exc)[:170]})
                checkpoint()
    except Exception as exc:
        errors.append(type(exc).__name__+': '+str(exc)[:220])
    if not demo:
        state['total_calls']+=api.calls
        state['history'].append({'date':a.today(),'mode':'fast_daily','calls':api.calls,'items':log,'errors':errors})
        state['history']=state['history'][-60:]
        checkpoint();a.build_pack(state);a.produce_report(state)
        a.jwrite(a.OUT/'last_result.json',state['history'][-1])
    progress('ERROR' if errors else 'COMPLETE','高速処理終了',errors[0] if errors else f'既存{reviewed}件・新規{generated}件')
    print(f'処理結果: 既存レビュー{reviewed}問・新規審査{generated}問・未審査{len(state["pending"])}問・API {api.calls}/{CALL_CAP}回')
    if errors:print('最初のエラー:',errors[0])
    return 1 if errors else 0


def today():return datetime.datetime.now().astimezone().date().isoformat()

def already_attempted():
    try:return json.loads((ROOT/'work'/'state.json').read_text(encoding='utf-8')).get('last_attempt')==today()
    except (OSError,ValueError,TypeError):return False

def run_daily():
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as log:
        log.write('\n=== '+datetime.datetime.now().isoformat(timespec='seconds')+' / 高速バッチ ===\n');log.flush()
        res=subprocess.run([sys.executable,str(ROOT/'update_watchdog.py'),'batch-once'],
                           cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=False)
        log.write(f'[WATCHDOG] 高速日次実行終了 exit={res.returncode}\n')
    ua.log('高速版の日次実行が終了。scheduler.logに結果を保存')

def scheduler(checker=ua.check_and_apply, *, iterations=None, sleep=time.sleep):
    if os.name!='nt':raise RuntimeError('Windows専用')
    lock=ua.windows_lock(LOCK)
    if lock is None:
        ua.log('別のAutopilotが起動中のため二重起動しません');return
    checks=0;next_update=0.0;previous_result=''
    try:
        while not STOP.exists() and today()<=CUTOFF:
            now=time.monotonic()
            if now>=next_update or REQUEST.exists():
                REQUEST.unlink(missing_ok=True)
                try:
                    result=checker()
                    if result not in ('UP_TO_DATE','NOT_CONFIGURED') or result!=previous_result:
                        ua.log('更新状態: '+result)
                    previous_result=result
                except Exception as exc:ua.log('更新確認失敗（生成は継続）: '+str(exc))
                next_update=now+UPDATE_INTERVAL_SEC
            if not already_attempted():run_daily()
            checks+=1
            if iterations is not None and checks>=iterations:break
            for _ in range(60):
                if STOP.exists():break
                sleep(1)
    finally:ua.release_lock(lock)
    ua.log('自動実行が終了')

if __name__=='__main__':
    if sys.argv[1:]==['batch-demo']:
        sys.exit(run_fast(demo=True))
    if sys.argv[1:]==['batch-once']:
        sys.exit(run_fast())
    if sys.argv[1:]==['batch-force']:
        sys.exit(run_fast(force=True))
    if len(sys.argv)>1:
        print('Unknown argument');sys.exit(2)
    try:scheduler()
    except Exception as exc:
        ua.log('バックグラウンドエラー: '+str(exc));sys.exit(1)
