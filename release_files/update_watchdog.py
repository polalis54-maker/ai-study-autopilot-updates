#!/usr/bin/env python3
"""Safe unattended updater/watchdog and bounded SAA batch question creator.
The watched machine must be awake. No deployment to Netlify; no secret uploads.
"""
from __future__ import annotations
import datetime, difflib, html, json, os, re, subprocess, sys, time
from pathlib import Path
import urllib.error
import urllib.request
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
# Draft-only model: no reasoning-token overhead. Gemini remains independent reviewer.
GENERATION_MODEL='gpt-4.1-mini'
# Count goal as 55 existing questions plus Gemini-approved new candidates.
# Existing questions are NOT automatically AWS-official-verified.
GOAL_TOTAL=200
GEN_DAILY=200
CAMPAIGN_START='2026-10-19'
CAMPAIGN_DAILY_CAP=300
# Optional repairs stay disabled until HTTP 400 is diagnosed.
# Pause optional OpenAI rewriter until its HTTP 400 path is diagnosed.
# Never block the already Gemini-reviewed valid questions.
ENABLE_OPTIONAL_REPAIR=False
REV_DAILY=5
CALL_CAP=25
ONE_TIME_EXTRA_DATE='2026-10-18'
ONE_TIME_EXTRA_LIMIT=50

def daily_call_cap(day=None):
    # Temporary consent: 2026-10-18 only. All other dates stay at 25.
    day=a.today() if day is None else day
    if day==ONE_TIME_EXTRA_DATE:
        return ONE_TIME_EXTRA_LIMIT
    if CAMPAIGN_START<=day<=CUTOFF:
        return CAMPAIGN_DAILY_CAP
    return CALL_CAP


G_PROMPT='''JSONオブジェクトのみを出力。指定した各specのid, exam=SAA-C03, domain, topic, type, difficultyを文字単位で厳守。複数選択なら選択肢5個・正解2個・問題文に「2つ選択」を明記。AWS SAA-C03のオリジナル日本語模擬試験を生成。specsのdomainとtopicを必ず守り、topic固有の設計判断を主題にする。同一テーマでも要件・正答理由・誤答理由の言い換えだけにしない。マイナーサービスは要件との適合性がある場合のみ採用し、サービス名の暗記問題にはしない。specsと同じ件数を返す。中〜上級の実務シナリオ。可用性・コスト・運用負荷・DRなどの制約を2つ以上含め、誤答ももっともらしく。全選択肢の正誤理由を解説。公式問題を転載しない。JSONのみ: {"questions":[{"id":"指定ID","exam":"SAA-C03","domain":"D1","topic":"...","type":"single","question":"...","choices":{"A":"...","B":"...","C":"...","D":"..."},"correct":["A"],"explanation":"...","difficulty":"中級","language":"ja","review_status":"ai_review_pending","source":{"kind":"original","label":"AI Study Auto-generated / AI review pending"}}]} singleは4択1正解、multipleは5択2正解で問題文に「2つ選択」を明記。すべてのIDと属性を守り、省略しない。'''
R_PROMPT=a.REVIEW_PROMPT.split('JSONオブジェクトだけ返答:')[0]+'''\n各questionsを独立かつ厳格にレビュー。全問題IDについて回答し、資料を調べたと偽らない。JSONのみ: {"reviews":[{"id":"指定ID","verdict":"PASS|REVISE|BLOCK","issues":[],"notes":"...","needs_official_verification":true,"exam_quality":{"distractor_quality":3,"scenario_realism":3,"explanation_depth":3,"difficulty_alignment":3,"reason":"..."}}]}'''

FIELDS={
    'id':{'type':'string'}, 'exam':{'type':'string'},
    'domain':{'type':'string'}, 'topic':{'type':'string'},
    'type':{'type':'string'}, 'question':{'type':'string'},
    'choices':{'type':'array','items':{'type':'string'}},
    'correct':{'type':'array','items':{'type':'string'}},
    'explanation':{'type':'string'}, 'difficulty':{'type':'string'}
}
SCHEMA={
    'type':'object','additionalProperties':False,'required':['questions'],
    'properties':{'questions':{
        'type':'array','items':{
            'type':'object','additionalProperties':False,
            'required':list(FIELDS),'properties':FIELDS
        }
    }}
}


def structured_batch_call(client, prompt, payload):
    """Use API-enforced schema instead of fragile JSON-only prompting."""
    if client.calls>=client.limit:
        raise RuntimeError('API request cap reached')
    client.calls+=1
    request={
        'model':GENERATION_MODEL,
        'instructions':prompt + (
            '\nChoices must be a JSON ARRAY of 4 strings for single or 5 strings'
            ' for multiple, in A/B/C/D(/E) order. Follow every spec exactly.'
        ),
        'input':json.dumps(payload,ensure_ascii=False),
        'store':False, 'max_output_tokens':9500,
        'text':{'format':{
            'type':'json_schema','name':'saa_batch',
            'strict':True,'schema':SCHEMA
        }}
    }
    req=urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=json.dumps(request,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json',
                 'Authorization':'Bearer '+client.keys['openai']},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req,timeout=180) as response:
            output=json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'OpenAI structured response HTTP {exc.code}') from None
    except (TimeoutError,urllib.error.URLError):
        raise RuntimeError('OpenAI network error / timeout') from None
    if output.get('status')=='incomplete':
        reason=(output.get('incomplete_details') or {}).get('reason','unknown')
        raise ValueError('OpenAI response truncated: '+str(reason)+' (model='+GENERATION_MODEL+')')
    if output.get('status')!='completed':
        raise ValueError('OpenAI response not completed')
    texts=[item.get('text','') for block in output.get('output',[])
           for item in block.get('content',[])
           if item.get('type')=='output_text']
    if not texts:raise ValueError('No OpenAI structured output')
    return a.parse_reply(''.join(texts))


def salvage_batch(api,specs,prompt):
    """Only accept exact spec-matching questions. Never silently coerce a changed ID/type."""
    by_id={item['id']:item for item in specs}
    response=api.call('openai',prompt,{'specs':specs})
    questions=response.get('questions',[])
    if not isinstance(questions,list):raise ValueError('questions must be array')
    found={}
    errors=[]
    for q in questions:
        if not isinstance(q,dict):
            errors.append('question is not a JSON object');continue
        qid=q.get('id')
        if qid not in by_id:
            errors.append('unexpected id: '+str(qid)[:60]);continue
        if qid in found:
            errors.append('duplicate response id: '+str(qid));continue
        spec=by_id[qid]
        mismatch=[field for field,want in (('exam','SAA-C03'),('type',spec['type']),
                  ('domain',spec['domain']),('difficulty',spec['difficulty']))
                  if q.get(field)!=want]
        if mismatch:
            errors.append(str(qid)+' mismatched fields: '+','.join(mismatch));continue
        if 'topic' in spec and q.get('topic')!=spec['topic']:
            errors.append(str(qid)+' mismatched fields: topic');continue
        try:
            a.validate(q,strict=True)
            if q['type']=='multiple' and not any(t in q['question']
                 for t in ('2つ','２つ','二つ','2 つ')):
                raise ValueError('multiple selection count missing')
            q['source']={'kind':'original',
                         'label':'AI Study Auto-generated / AI review pending'}
            q['review_status']='ai_review_pending'
            q['language']='ja'
            found[qid]=q
        except (ValueError,KeyError,TypeError) as exc:
            errors.append(str(qid)+' invalid schema: '+str(exc)[:90])
    # Avoid logging the generated question content, which could contain sensitive text.
    if errors:print('[FAST][FORMAT]', '; '.join(errors[:5]),flush=True)
    return [found[item['id']] for item in specs if item['id'] in found]

class API(a.Clients):
    def call(self, provider, prompt, payload):
        if provider=='openai' and prompt==G_PROMPT and not self.demo:
            return structured_batch_call(self,prompt,payload)
        return super().call(provider,prompt,payload)

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

# SAA-C03 exam-domain targets: D1 30%, D2 26%, D3 24%, D4 20%.
# Each slot selects a knowledge-specific blueprint instead of repeating generic topics.
# This is a *generation allocation*, not a claim about actual AWS exam question frequencies.
SAA_WEIGHTS={'D1':30,'D2':26,'D3':24,'D4':20}
SAA_BLUEPRINT={
 'D1':[
  'IAM Identity Center / SCP / permissions boundary の使い分け',
  'IAM Access Analyzer を使う外部共有リスク',
  'KMS キーポリシー / 暗号化の権限分離',
  'VPC Interface Endpoint と PrivateLink の通信制御',
  'Security Groups / NACL / Network Firewall の選択',
  'WAF / Shield / CloudFront のレイヤ別保護',
  'Secrets Manager と Systems Manager Parameter Store の使い分け',
  'AWS Organizations と複数アカウントのガバナンス',
  'Amazon Cognito とアプリ利用者認証',
  'CloudTrail / Config / GuardDuty の監査・検知'
 ],
 'D2':[
  'Multi-AZ と Multi-Region の障害範囲の判断',
  'RTO / RPO に応じた DR 戦略と Elastic Disaster Recovery',
  'AWS Backup によるクロスアカウント・クロスリージョン保護',
  'Route 53 フェイルオーバーとヘルスチェック',
  'SQS / SNS / EventBridge による疎結合',
  'Aurora Global Database とデータ復旧設計',
  'S3 バージョニングとクロスリージョンレプリケーション',
  'ELB / Auto Scaling の障害時の回復',
  'Step Functions による失敗時の再試行',
  'EFS / FSx / EBS の冗長化と共有要件'
 ],
 'D3':[
  'EC2 ファミリー選択とコンピューティング性能',
  'Auto Scaling と負荷指標の選択',
  'CloudFront / Global Accelerator のネットワーク性能差',
  'DynamoDB オンデマンド・プロビジョンド容量',
  'Aurora Replica と RDS Read Replica の性能',
  'ElastiCache / DAX のキャッシュ選択',
  'EBS gp3 / io2 / instance store の IOPS とレイテンシ',
  'S3 Transfer Acceleration / Multipart Upload',
  'Direct Connect / VPN / DataSync の転送要件',
  'Amazon FSx for Lustre / Windows File Server の性能要件'
 ],
 'D4':[
  'Compute Savings Plans / Reserved Instances / Spot の選択',
  'S3 Intelligent-Tiering / Lifecycle / Glacier の比較',
  'AWS Compute Optimizer による適正サイズ',
  'NAT Gateway / VPC Endpoint のコストトレードオフ',
  'データ転送料金と CloudFront キャッシュによる最適化',
  'DynamoDB オンデマンドとプロビジョンドの料金比較',
  'RDS / Aurora / Serverless の課金モデル',
  'Cost Explorer / Budgets / Cost Anomaly Detection の役割',
  'EBS / EFS / FSx のストレージ料金とアクセス',
  'Lambda / Fargate / EC2 の利用特性別コスト'
 ]
}
def _saa_domain_slots():
    # Smooth weighted scheduling, exactly 100 slots; stable across restarts.
    counts={d:0 for d in SAA_WEIGHTS}
    slots=[]
    for i in range(100):
        domain=max(SAA_WEIGHTS, key=lambda d:(i+1)*SAA_WEIGHTS[d]/100-counts[d])
        slots.append(domain)
        counts[domain]+=1
    assert counts==SAA_WEIGHTS
    return tuple(slots)

SAA_DOMAIN_SLOTS=_saa_domain_slots()

def _topic_usage(state, existing):
    """Count covered topic *labels* only. Conservative heuristic, not semantic clustering."""
    usage={}
    pool=list(existing)
    for part in ('existing','generated','pending'):
        for item in (state.get(part) or {}).values():
            q=item.get('candidate',item) if isinstance(item,dict) else None
            if isinstance(q,dict):pool.append(q)
    seen=set()
    for q in pool:
        if not isinstance(q,dict):continue
        uid=q.get('id')
        if uid and uid in seen:continue
        if uid:seen.add(uid)
        topic=str(q.get('topic') or '').strip()
        domain=str(q.get('domain') or '')
        if topic:usage[(domain,topic)]=usage.get((domain,topic),0)+1
    return usage


def specs_for(state,n,existing=()):
    """Weighted domain allocation, select the least-covered topic within each domain."""
    usage=_topic_usage(state,existing)
    specs=[]
    for ix in range(state['generated_index'],state['generated_index']+n):
        domain=SAA_DOMAIN_SLOTS[ix%100]
        topics=SAA_BLUEPRINT[domain]
        # Stable tie breaker rotates topics to avoid always using the first.
        offset=(ix//100+ix%100)%len(topics)
        topic=min((topics[(offset+j)%len(topics)] for j in range(len(topics))),
                  key=lambda t:usage.get((domain,t),0))
        usage[(domain,topic)]=usage.get((domain,topic),0)+1
        specs.append({'id':f'SAA-AUTO-{ix+1:05d}','domain':domain,'topic':topic,
                      'type':'multiple' if ix%4==3 else 'single',
                      'difficulty':'上級' if ix%3==2 else '中級'})
    return specs

# Validate each generated question separately; preserve valid neighbors.
def make(api,specs):
    return salvage_batch(api,specs,G_PROMPT)

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

def question_is_near_duplicate(candidate, existing, state, threshold=0.88):
    """Conservative text overlap gate, not a semantic equivalence classifier."""
    def normalized(q):
        return re.sub(r'[\\W_]+', '', str(q.get('question', '')).lower())
    new=normalized(candidate)
    if len(new)<25:
        return False
    others=list(existing)
    for part in ('existing','generated','pending'):
        for item in (state.get(part) or {}).values():
            q=item.get('candidate',item) if isinstance(item,dict) else None
            if isinstance(q,dict) and q.get('id')!=candidate.get('id'):
                others.append(q)
    for old in others:
        if not isinstance(old,dict) or old.get('id')==candidate.get('id'):
            continue
        text=normalized(old)
        if len(text)<25:continue
        if new==text or difflib.SequenceMatcher(None,new,text,autojunk=False).ratio()>=threshold:
            return True
    return False


def count_approved(state):
    generated=state.get('generated') or {}
    return sum(isinstance(v,dict) and v.get('status')=='AI_PASS'
               for v in generated.values())


def existing_approved(state):
    existing=state.get('existing') or {}
    # These are independently Gemini-reviewed existing questions.
    return sum(isinstance(v,dict) and v.get('status')=='AI_PASS'
               for v in existing.values())


def goal_progress(state):
    # Count only Gemini PASS, not unreviewed original 55 or REVISE/BLOCK.
    return count_approved(state)+existing_approved(state)


def campaign_due(state):
    day=a.today()
    if not (CAMPAIGN_START<=day<=CUTOFF):
        return False
    if goal_progress(state)>=GOAL_TOTAL:
        return False
    if state.get('campaign_paused_date')==day:
        return False
    if daily_call_cap()-used_today(state)<4:
        return False
    # Do not launch another batch until this day's prior run is fully committed.
    return bool(state.get('last_attempt')==day and
                any(isinstance(h,dict) and h.get('date')==day
                    for h in state.get('history',[])))


def used_today(state):
    """Total API requests across all completed runs on this date."""
    return sum(max(0, h['calls']) for h in state.get('history', [])
               if isinstance(h, dict) and h.get('date') == a.today()
               and type(h.get('calls')) is int)


def retry_due(state):
    """Automatic same-day retry: once only, under the existing daily request cap."""
    if state.get('last_attempt') != a.today():
        return False
    if state.get('auto_retry_date') == a.today():
        return False
    entries=[h for h in state.get('history',[]) if isinstance(h,dict) and h.get('date')==a.today()]
    return bool(entries and entries[-1].get('errors') and daily_call_cap()-used_today(state)>=4)


def fix_retry_due(state):
    """One extra recovery in the explicitly authorized Oct 18 budget, never daily."""
    if a.today() != ONE_TIME_EXTRA_DATE or state.get('last_attempt') != a.today():
        return False
    if state.get('post_fix_retry_date') == a.today():
        return False
    entries=[h for h in state.get('history', []) if isinstance(h,dict) and h.get('date')==a.today()]
    if not entries or not entries[-1].get('errors'):
        return False
    errors=' | '.join(str(x) for x in entries[-1]['errors'])
    return "name 'urllib' is not defined" in errors and daily_call_cap()-used_today(state)>=4


def run_fast(*,demo=False,force=False,generate_only=False):
    if a.today()>CUTOFF and not demo:
        print('10/28を過ぎたため生成停止');return 0
    existing=a.jread(a.STUDY_FILE)['questions']
    for q in existing:a.validate(q)
    state=a.jread(a.STATEFILE,a.state_default())
    state.setdefault('pending',{})
    state.setdefault('failed_generations',{})
    if goal_progress(state)>=GOAL_TOTAL:
        print('目標到達: Gemini PASSを含む全200問に到達。追加API利用なし。',flush=True)
        return 0
    if not demo and state['last_attempt']==a.today() and not force:
        print('今日は既に実行済み。API呼び出しなし');return 0
    remaining=daily_call_cap() if demo else max(0,daily_call_cap()-used_today(state))
    if not demo and remaining<4:
        print(f'本日のAPI残枠不足: {remaining}回。追加呼び出しなし。');return 0
    keys=('', '') if demo else a.load_keys()
    if not demo:
        state['last_attempt']=a.today()
        a.jwrite(a.STATEFILE,state)
    api=API(*keys,limit=remaining,demo=demo)
    log=[];errors=[];reviewed=0;generated=0
    before_pass=count_approved(state)
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
        if part=='generated' and status=='AI_PASS' and question_is_near_duplicate(q, existing, state):
            status='DUPLICATE_HOLD'  # Never approve a near-duplicate automatically.
        if part=='generated' and status=='AI_PASS':
            # A model's self-reported PASS is not documentation verification.
            # Require an explicit human/content approval for generated material.
            status='QUALITY_HOLD'
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
        # A malformed response must not discard valid neighbors.
        try:
            valid=make(api,group)
        except (ValueError,TypeError,KeyError) as exc:
            valid=[]
            print('[FAST][WARN] バッチ生成不完全。個別再試行: '+str(exc)[:160],flush=True)
        found={q['id'] for q in valid}
        missing=[spec for spec in group if spec['id'] not in found]
        # Retry missing IDs INDIVIDUALLY, not as the same oversized batch.
        # Reserve one API call for Gemini to review any salvaged proposals.
        if missing and len(group)>1:
            for spec in missing:
                if api.calls+2>api.limit:
                    break
                try:
                    extra=make(api,[spec])
                    for q in extra:
                        if q['id'] not in found:
                            valid.append(q)
                            found.add(q['id'])
                except (ValueError,TypeError,KeyError) as exc:
                    print('[FAST][WARN] 単独生成も不完全: '+str(exc)[:160],flush=True)
        for spec in group:
            if spec['id'] not in found:
                state['failed_generations'][spec['id']]={
                    'date':a.today(),'reason':'問題の形式不備・応答途中終了またはAPI残枠不足'}
                errors.append(spec['id']+': 形式不備または未完了で未採用')
        if missing:checkpoint()
        return valid
    progress('RUNNING','目標200問までバッチ作成を開始')
    try:
        missing=[] if generate_only else [q for q in existing if q['id'] not in state['existing'] and q['id'] not in state['generated']][:REV_DAILY]
        for start in range(0,len(missing),GROUP):
            if api.calls+2>api.limit:break
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
            if api.calls+2>api.limit:break
            group=[state['pending'][i] for i in pending_ids[start:start+GROUP] if i in state['pending']]
            if not group:continue
            results=review_safe(group)
            for q in group:
                if q['id'] in results:
                    keep(q,results[q['id']],'generated');state['pending'].pop(q['id'],None);generated+=1
            checkpoint()
        attempted=0
        while (attempted<GEN_DAILY and api.calls+4<=api.limit
               and goal_progress(state)<GOAL_TOTAL):
            group=specs_for(state,min(GROUP,GEN_DAILY-attempted,
                                      GOAL_TOTAL-goal_progress(state)),existing)
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
        for qid, entry in (list(state['generated'].items())[-GEN_DAILY:] if ENABLE_OPTIONAL_REPAIR else []):
            if api.calls+3>api.limit:break
            if entry['status'] not in ('REVISE_UNRESOLVED','NEEDS_QUALITY_UPGRADE'):continue
            if entry.get('repair_deferred'):
                continue  # Do not waste tomorrow's API budget on a known rejected repair request.
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
            except RuntimeError as exc:
                # The original question remains staged as unapproved. Never let a
                # nonessential repair HTTP failure abort the whole batch.
                entry['repair_deferred']=True
                entry['audit'].append({'role':'openai','action':'repair_deferred_http_error',
                                       'reason':str(exc)[:170]})
                print('[FAST][WARN] 任意の修正API失敗。問題を保留して続行: '+qid,flush=True)
                checkpoint()
            except (ValueError,KeyError,TypeError) as exc:
                entry['audit'].append({'role':'openai','action':'fix_rejected','reason':str(exc)[:170]})
                checkpoint()
    except Exception as exc:
        errors.append(type(exc).__name__+': '+str(exc)[:220])
    if not demo:
        state['total_calls']+=api.calls
        new_pass=count_approved(state)-before_pass
        state['history'].append({'date':a.today(),'mode':'continuous_200',
                                 'calls':api.calls,'items':log,'errors':errors,
                                 'new_pass':new_pass,'new_reviewed':generated,
                                 'goal_progress':goal_progress(state)})
        # Stop repeated loops with zero useful approvals. Keep the current
        # proposals and retry on the following day with a fresh budget.
        if generate_only and new_pass<=0 and api.calls>=4:
            state['campaign_paused_date']=a.today()
            print('Gemini PASSが増えなかったため本日の連続実行を停止',flush=True)

        state['history']=state['history'][-1200:]
        checkpoint();a.build_pack(state);a.produce_report(state)
        a.jwrite(a.OUT/'last_result.json',state['history'][-1])
    progress('ERROR' if errors else 'COMPLETE','高速処理終了',errors[0] if errors else f'既存{reviewed}件・新規{generated}件')
    print(f'処理結果: 既存レビュー{reviewed}問・新規審査{generated}問・未審査{len(state["pending"])}問 / 目標 {goal_progress(state)}/{GOAL_TOTAL}問（Gemini PASS+既存）',flush=True)
    print(f'API {api.calls}/{remaining}回（本日累計{used_today(state)}/{daily_call_cap()}回）',flush=True)
    if errors:print('最初のエラー:',errors[0])
    return 1 if errors else 0


def today():return datetime.datetime.now().astimezone().date().isoformat()


RUNTIME=ROOT/'work'/'outputs'/'runtime_status.json'
DASHBOARD=ROOT/'work'/'outputs'/'runtime_status.html'

def _read_obj(path):
    try:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}

def write_runtime_status(status, detail='', child_pid=None):
    """Publish local heartbeat while waiting AND while generating. Never uses API."""
    state=_read_obj(ROOT/'work'/'state.json')
    last=_read_obj(ROOT/'work'/'outputs'/'last_result.json')
    live=_read_obj(ROOT/'work'/'outputs'/'live_progress.json')
    generated=state.get('generated') or {}
    reviewed=state.get('existing') or {}
    errors=last.get('errors') or []
    if status=='WAITING' and errors and last.get('date')==today():
        status='ERROR_WAITING'
    now=datetime.datetime.now().astimezone()
    data={'status':status,'detail':detail,'timestamp':now.isoformat(timespec='seconds'),
      'unix_time':time.time(),'watchdog_pid':os.getpid(),'child_pid':child_pid,
      'version':ua.local_version(),'last_attempt':state.get('last_attempt',''),
      'reviewed_count':len(reviewed),'reviewed_pass':sum(
          isinstance(x,dict) and x.get('status')=='AI_PASS' for x in reviewed.values()),
      'generated_count':len(generated),'generated_pass':sum(
          isinstance(x,dict) and x.get('status')=='AI_PASS' for x in generated.values()),
      'pending_count':len(state.get('pending') or {}),
      'goal_total':GOAL_TOTAL,'goal_progress':goal_progress(state),
      'goal_remaining':max(0,GOAL_TOTAL-goal_progress(state)),
      'total_calls':state.get('total_calls',0),
      'today_calls':used_today(state),'today_cap':daily_call_cap(),
      'today_remaining':max(0,daily_call_cap()-used_today(state)),
      'last_errors':errors[:3],
      'last_phase':live.get('phase','') if status=='RUNNING' else '',
      'next_run':('目標200問到達・生成完了' if goal_progress(state)>=GOAL_TOTAL else
                  ('本日の残り枠で追加生成予定' if campaign_due(state) else
                   ('本日の生成停止・次回は翌日' if a.today()>=CAMPAIGN_START and a.today()<=CUTOFF and already_attempted() else
                    ('今夜の残り枠で新規生成を再開予定' if fix_retry_due(state) else ('本日中にエラー再試行予定' if retry_due(state) else ('本日中の再試行済み・翌日実行' if state.get('auto_retry_date')==today() else ('PC起動中に翌日実行' if already_attempted() else 'まもなく開始'))))))),
      'sync_status':_read_obj(ROOT/'work'/'outputs'/'study_sync_status.json').get('status','未記録'),
      'mobile_status':_read_obj(ROOT/'work'/'outputs'/'mobile_publish_status.json').get('status','未設定'),
      'mobile_questions':_read_obj(ROOT/'work'/'outputs'/'mobile_publish_status.json').get('questions','未記録')}
    RUNTIME.parent.mkdir(parents=True,exist_ok=True)
    tmp=RUNTIME.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(RUNTIME)
    esc=lambda v:html.escape(str(v),quote=True)
    labels={'STARTING':'起動準備中','WAITING':'待機中（正常）','RUNNING':'生成・レビュー中',
            'ERROR_WAITING':'前回エラーあり・待機中','STOPPED':'停止中'}
    label=labels.get(status,status)
    color='#57d6a5' if status=='WAITING' else ('#ffd078' if status in ('RUNNING','STARTING') else '#f09eab')
    latest=esc(data['last_phase'] or detail)
    err=esc(' / '.join(map(str,errors[:2])) if errors else 'なし')
    page=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="8"><title>AI Study 稼働状況</title><style>body{{background:#101827;color:#f5f7fc;font:16px/1.7 system-ui,sans-serif;max-width:820px;margin:32px auto;padding:0 16px}}main{{background:#1c2840;border:1px solid #3e5375;border-radius:18px;padding:24px}}h2{{color:{color}}}small{{color:#aab8d0}}.cards{{display:flex;gap:12px;flex-wrap:wrap}}.cards>div{{background:#111c31;padding:15px;border-radius:12px;flex:1;min-width:130px}}strong{{display:block;font-size:1.4rem}}#signal{{font-weight:bold}}</style></head><body><h1>🎓 AI Study Autopilot</h1><main><small>v{esc(data['version'])}</small><h2>{esc(label)}</h2><p>{latest}</p><div class="cards"><div>既存レビュー<strong>{data['reviewed_count']} / 55</strong></div><div>新規保存<strong>{data['generated_count']}問</strong></div><div>新規 Gemini PASS<strong>{data['generated_pass']}問</strong></div></div><p><strong>Gemini PASS 合計: {data['goal_progress']} / {data['goal_total']} 問</strong></p><p>目標まで残り {data['goal_remaining']} 問。新規 Gemini PASS {data['generated_pass']} 問</p><p>本日のAPI利用: {data['today_calls']} / {data['today_cap']} 回 (残り {data['today_remaining']} 回)</p><p>次回: {esc(data['next_run'])}</p><p>PC内の問題同期: {esc(data['sync_status'])}</p><p><strong>スマホ版(Netlify): {esc(data['mobile_status'])}</strong> / 公開問題数: {esc(data['mobile_questions'])}</p><p>直近のエラー: {err}</p><small>生存信号: {esc(data['timestamp'])} / PID {data['watchdog_pid']}</small><p id="signal">生存信号を確認中…</p></main><p><small>8秒ごとに更新。2分間更新がなければ停止・フリーズの疑い。AI PASSはAWS公式確認済みではありません。</small></p><script>const t={int(data['unix_time']*1000)};function check(){{const elapsed=Math.max(0,Date.now()-t),el=document.getElementById('signal');el.textContent=elapsed>120000?'⚠ 生存信号が2分以上更新されていません':('● 生存信号あり '+Math.floor(elapsed/1000)+'秒前');el.style.color=elapsed>120000?'#ffab83':'#57d6a5';}}check();setInterval(check,4000)</script></body></html>'''
    tmp=DASHBOARD.with_suffix('.html.tmp')
    tmp.write_text(page,encoding='utf-8')
    tmp.replace(DASHBOARD)
    return data

def already_attempted():
    try:return json.loads((ROOT/'work'/'state.json').read_text(encoding='utf-8')).get('last_attempt')==today()
    except (OSError,ValueError,TypeError):return False

def run_daily(*, retry=False, post_fix=False, campaign=False):
    if retry:
        # Reserve the one allowed automatic retry before launching a child.
        state=_read_obj(ROOT/'work'/'state.json')
        state['auto_retry_date']=today()
        if post_fix:
            state['post_fix_retry_date']=today()
        a.jwrite(ROOT/'work'/'state.json',state)
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as log:
        log.write('\n=== '+datetime.datetime.now().isoformat(timespec='seconds')+(' / エラー再試行 ===\n' if retry else ' / 高速バッチ ===\n'));log.flush()
        proc=subprocess.Popen([sys.executable,str(ROOT/'update_watchdog.py'),'batch-new-only' if (post_fix or campaign) else ('batch-retry' if retry else 'batch-once')],
                              cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        while True:
            write_runtime_status('RUNNING','OpenAI生成・Geminiレビューを実行中',child_pid=proc.pid)
            try:code=proc.wait(timeout=6)
            except subprocess.TimeoutExpired:continue
            break
        log.write(f'[WATCHDOG] 高速日次実行終了 exit={code}\n')
        log.flush()
    write_runtime_status('WAITING','本日の処理終了。次の実行を待機中' if code==0 else '処理がエラーで終了。ログを確認')
    ua.log('高速版の日次実行が終了。scheduler.logに結果を保存')

def scheduler(checker=ua.check_and_apply, *, iterations=None, sleep=time.sleep):
    if os.name!='nt':raise RuntimeError('Windows専用')
    lock=ua.windows_lock(LOCK)
    if lock is None:
        ua.log('別のAutopilotが起動中のため二重起動しません');return
    checks=0;next_update=0.0;previous_result=''
    write_runtime_status('STARTING','常駐プログラムを起動しました')
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
            if goal_progress(_read_obj(ROOT/'work'/'state.json'))>=GOAL_TOTAL:
                write_runtime_status('WAITING','目標200問に到達。生成を停止')
            elif not already_attempted():run_daily()
            elif campaign_due(_read_obj(ROOT/'work'/'state.json')):run_daily(campaign=True)
            elif fix_retry_due(_read_obj(ROOT/'work'/'state.json')):run_daily(retry=True,post_fix=True)
            elif retry_due(_read_obj(ROOT/'work'/'state.json')):run_daily(retry=True)
            write_runtime_status('WAITING','本日の処理は完了。次回実行を待機中')
            checks+=1
            if iterations is not None and checks>=iterations:break
            for _ in range(60):
                if STOP.exists():break
                sleep(1)
    finally:
        write_runtime_status('STOPPED','停止要求または期限到達')
        ua.release_lock(lock)
    ua.log('自動実行が終了')

if __name__=='__main__':
    if sys.argv[1:]==['batch-demo']:
        sys.exit(run_fast(demo=True))
    if sys.argv[1:]==['batch-once']:
        sys.exit(run_fast())
    if sys.argv[1:]==['batch-force']:
        sys.exit(run_fast(force=True))
    if sys.argv[1:]==['batch-retry']:
        sys.exit(run_fast(force=True))
    if sys.argv[1:]==['batch-new-only']:
        sys.exit(run_fast(force=True,generate_only=True))
    if len(sys.argv)>1:
        print('Unknown argument');sys.exit(2)
    try:scheduler()
    except Exception as exc:
        ua.log('バックグラウンドエラー: '+str(exc));sys.exit(1)
