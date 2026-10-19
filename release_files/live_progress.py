"""Progress and fail-closed LOCAL AI Study sync. No network or model API calls."""
import datetime, hashlib, html, io, json, re, zipfile
from pathlib import Path


def save_json(path, data):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def update(output_dir, *, status, phase, detail='', calls=0, existing=0, generated=0,
           passed_existing=0, passed_generated=0, mode='通常実行', goal_existing=5,
           goal_generated=4, error=''):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    now=datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    data={'status':status,'phase':phase,'detail':detail,'updated_at':now,
          'api_calls_this_run':calls,'mode':mode,'existing_reviewed_total':existing,
          'new_questions_total':generated,'existing_pass_total':passed_existing,
          'new_pass_total':passed_generated,'goal_reviews_this_run':goal_existing,
          'goal_generation_this_run':goal_generated,'error':error}
    save_json(out/'live_progress.json',data)
    esc=lambda x:html.escape(str(x),quote=True)
    label={'RUNNING':'🔄 処理中','COMPLETE':'✅ 完了','ERROR':'❌ エラー'}.get(status,status)
    rows=''.join('<p>%s：<b>%s</b></p>'%(esc(name),esc(value)) for name,value in [
        ('既存レビュー済み',existing),('新規問題保存済み',generated),
        ('既存AI PASS',passed_existing),('新規AI PASS',passed_generated),
        ('今回のAPI呼び出し',calls)])
    page='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta http-equiv="refresh" content="5"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Study 進捗</title><style>body{font:16px/1.7 system-ui,sans-serif;background:#111728;color:#f1f4fc;max-width:760px;margin:35px auto;padding:16px}.panel{background:#1c2740;padding:24px;border:1px solid #404e71;border-radius:18px}b{color:#ffb3cf}.small{color:#a8b5ca;font-size:13px}</style><h1>🎓 AI Study 自動制作</h1><div class="panel"><div class="small">%s · 5秒ごとに更新</div><h2>%s</h2><b>%s</b><p>%s</p>%s<p class="small">更新時刻: %s</p></div><p class="small">AI PASSはAWS公式確認済みを意味しません。</p></html>'''%(esc(mode),esc(label),esc(phase),esc(detail),rows,esc(now))
    tmp=out/'live_progress.html.tmp';tmp.write_text(page,encoding='utf-8');tmp.replace(out/'live_progress.html')
    if status in ('COMPLETE','ERROR'):
        result=sync_study_pack(out)
        if result.get('status') in ('SYNCED','UNCHANGED'):
            try:
                publish_mobile(out, quiet=True)
            except Exception as exc:
                record_mobile_result(out, 'ERROR', str(exc)[:180])


def sync_study_pack(output_dir):
    """Merge only AI-PASS proposals into bundled PWA, not Netlify or device history."""
    out=Path(output_dir);study=out.parent.parent/'AI_Study'
    path=study/'questions.json';index=study/'index.html';sw=study/'sw.js'
    proposals=out/'AI_Study_追加候補.json'
    def report(state,**details):
        result={'status':state,'updated_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),**details}
        save_json(out/'study_sync_status.json',result)
        return result
    if not proposals.is_file() or not all(p.is_file() for p in (path,index,sw)):
        return report('WAITING',message='問題パックまたはアプリのファイル待ち')
    try:
        incoming=json.loads(proposals.read_text(encoding='utf-8-sig'))['questions']
        base=json.loads(path.read_text(encoding='utf-8-sig'))
        current=base['questions']
        original_html=index.read_text(encoding='utf-8')
        m=re.search(r'(<script id="default-pack" type="application/json">)(.*?)(</script>)',original_html,re.S)
        if not m:raise ValueError('初期問題データの埋め込みタグがありません')
        inline=json.loads(m.group(2))['questions']
        if not isinstance(incoming,list) or not isinstance(current,list) or not isinstance(inline,list):
            raise ValueError('問題データは配列である必要があります')
        ids=[q['id'] for q in current]
        if ids != [q['id'] for q in inline] or len(ids)!=len(set(ids)):
            raise ValueError('questions.jsonとindex.htmlが不一致。元データを保護して中止')
        existing=set(ids); seen=set(); add=[]
        for q in incoming:
            qid=q.get('id') if isinstance(q,dict) else None
            if not isinstance(qid,str) or not qid.startswith('SAA-AUTO-') or qid in seen:
                raise ValueError('不正な問題IDまたはパック内で重複したID')
            seen.add(qid)
            if qid in existing:continue
            letters=set('ABCDE' if q.get('type')=='multiple' else 'ABCD')
            correct=q.get('correct'); choices=q.get('choices')
            if (q.get('exam')!='SAA-C03' or q.get('review_status')!='ai_reviewed_unverified'
                or q.get('type') not in ('single','multiple')
                or not isinstance(q.get('question'),str) or len(q['question'])<40
                or not isinstance(q.get('explanation'),str) or len(q['explanation'])<75
                or not isinstance(choices,dict) or set(choices)!=letters
                or any(not isinstance(v,str) or not v.strip() for v in choices.values())
                or not isinstance(correct,list) or len(correct)!=(2 if q['type']=='multiple' else 1)
                or len(set(correct))!=len(correct) or not set(correct)<=letters
                or not isinstance(q.get('source'),dict) or q['source'].get('kind')!='original'):
                raise ValueError('候補形式不備: '+qid)
            item=dict(q);item['source']={**q['source'],'label':'AI生成・Geminiレビュー通過（公式資料未照合）'}
            add.append(item);existing.add(qid)
        if not add:return report('UNCHANGED',total=len(current),newly_added=0)
        merged={**base,'questions':current+add}
        raw=json.dumps(merged,ensure_ascii=False,separators=(',',':'))
        safe=raw.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        new_html=original_html[:m.start(2)]+safe+original_html[m.end(2):]
        new_sw,n=re.subn(r"const CACHE='ai-study-[^']+';",
                         "const CACHE='ai-study-autopilot-"+hashlib.sha256(raw.encode()).hexdigest()[:12]+"';",
                         sw.read_text(encoding='utf-8'),count=1)
        if n!=1:raise ValueError('サービスワーカーキャッシュ名が不明')
        changed={path:(json.dumps(merged,ensure_ascii=False,indent=2)+'\n').encode(),
                 index:new_html.encode(),sw:new_sw.encode()}
        permitted={'index.html','questions.json','sw.js','manifest.webmanifest','icon.svg',
                   'icon-192.png','icon-512.png','ai-teacher-avatar.webp','ai-hero-art.webp','_headers'}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(study.iterdir()):
                if p.is_file() and p.name in permitted:
                    z.writestr(p.name,changed[p] if p in changed else p.read_bytes())
        backups={p:p.read_bytes() for p in changed};written=[]
        try:
            for p,data in changed.items():
                temp=p.with_suffix(p.suffix+'.sync.tmp');temp.write_bytes(data);temp.replace(p);written.append(p)
            zip_path=out/'AI_Study_公開用.zip';temp=zip_path.with_suffix('.zip.tmp')
            temp.write_bytes(buf.getvalue());temp.replace(zip_path)
        except Exception:
            for p in reversed(written):
                temp=p.with_suffix(p.suffix+'.restore.tmp');temp.write_bytes(backups[p]);temp.replace(p)
            raise
        return report('SYNCED',total=len(merged['questions']),newly_added=len(add),
                      ready_zip='AI_Study_公開用.zip',message='ローカルアプリのみ更新、Netlifyは未更新')
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile) as exc:
        return report('FAILED',message=str(exc)[:250])


# Mobile publisher for the EXISTING Netlify PWA.
# Optional feature: does not require Netlify credentials until configured locally.
# The PAT is encrypted using Windows DPAPI for the current Windows account.
# Never upload work/, API keys, progress data, or user backups.
import base64
import ctypes
import getpass
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MOBILE_FILES=frozenset({
    'index.html','questions.json','sw.js','manifest.webmanifest',
    'icon.svg','icon-192.png','icon-512.png','ai-teacher-avatar.webp',
    'ai-hero-art.webp','_headers','LICENSE-MIT.txt'
})
MOBILE_REQUIRED=frozenset({'index.html','questions.json','sw.js','manifest.webmanifest'})
NETLIFY_API='https://api.netlify.com/api/v1'

def mobile_paths():
    root=Path(__file__).resolve().parent
    return root/'work'/'mobile_sync',root/'AI_Study',root/'work'/'outputs'

def record_mobile_result(out, status, message='', **extra):
    out.mkdir(parents=True,exist_ok=True)
    obj={'status':status,'time':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
         'message':str(message)[:240],**extra}
    save_json(out/'mobile_publish_status.json',obj)
    return obj

def _win_blob(data):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]
    buffer=ctypes.create_string_buffer(data)
    return Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte))),buffer,Blob

def dpapi_encrypt_token(token):
    if os.name!='nt':raise RuntimeError('Windows DPAPI is required')
    inp,buffer,Blob=_win_blob(token.encode('utf-8'))
    out=Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp),'AI Study Netlify',None,None,None,1,ctypes.byref(out)):
        raise RuntimeError('Windows DPAPI could not protect Netlify access token')
    try:return base64.b64encode(ctypes.string_at(out.pbData,out.cbData)).decode('ascii')
    finally:ctypes.windll.kernel32.LocalFree(ctypes.cast(out.pbData,ctypes.c_void_p))

def dpapi_decrypt_token(cipher):
    if os.name!='nt':raise RuntimeError('Windows DPAPI is required')
    inp,buffer,Blob=_win_blob(base64.b64decode(cipher))
    out=Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp),None,None,None,None,1,ctypes.byref(out)):
        raise RuntimeError('Netlify token cannot be decrypted with this Windows user')
    try:return ctypes.string_at(out.pbData,out.cbData).decode('utf-8')
    finally:ctypes.windll.kernel32.LocalFree(ctypes.cast(out.pbData,ctypes.c_void_p))

def mobile_site_host(s):
    s=str(s).strip().lower()
    if '://' not in s:s='https://'+s
    parsed=urllib.parse.urlsplit(s)
    host=parsed.hostname or ''
    if parsed.scheme!='https' or parsed.port or not host.endswith('.netlify.app') or host.count('.')!=2 or parsed.path not in ('','/') or parsed.query or parsed.fragment:
        raise ValueError('Enter only your original https://NAME.netlify.app website address')
    return host

def mobile_request(path,token,method='GET',data=None):
    if not path.startswith('/') or '://' in path:
        raise ValueError('Invalid Netlify API path')
    url=NETLIFY_API+path
    req=urllib.request.Request(url,data=data,
        headers={'Authorization':'Bearer '+token,'User-Agent':'AI-Study-Mobile-Publisher/0.1',
                 'Content-Type':'application/zip' if data is not None else 'application/json'},
        method=method)
    try:
        with urllib.request.urlopen(req,timeout=90) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        # Never include token or untrusted response body in logs.
        raise RuntimeError('Netlify API HTTP '+str(e.code)+' ('+method+' '+path.split('?')[0]+')') from None
    except (TimeoutError,urllib.error.URLError) as e:
        raise RuntimeError('Unable to contact Netlify securely') from None

def validate_mobile_site(site):
    info=str(site.get('ssl_url') or site.get('url') or '')
    if not info:
        return False
    try:return mobile_site_host(info)==site.get('expected_host')
    except ValueError:return False

def build_mobile_zip(study):
    path=study/'questions.json';index=study/'index.html'
    if not all((study/name).is_file() for name in MOBILE_REQUIRED):
        raise ValueError('AI Study files missing: ' + ','.join(sorted(MOBILE_REQUIRED)))
    pack=json.loads(path.read_text(encoding='utf-8-sig'))
    from re import search, S
    htmltext=index.read_text(encoding='utf-8')
    matched=search(r'<script id="default-pack" type="application/json">(.*?)</script>',htmltext,S)
    if not matched:raise ValueError('AI Study embedded questions not found')
    inner=json.loads(matched.group(1))
    originals=pack.get('questions',[])
    embedded=inner.get('questions',[])
    ids=[q['id'] for q in originals]
    if len(ids)!=len(set(ids)) or ids!=[q['id'] for q in embedded]:
        raise ValueError('AI Study JSON and HTML question IDs disagree; blocked')
    # Ensure local ZIP contains a complete website, not a partial deployment.
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(MOBILE_FILES):
            p=study/name
            if p.is_file() and p.is_file():z.write(p,name)
    data=buf.getvalue()
    if len(data)>25*1024*1024:raise ValueError('Site ZIP exceeds 25MB safety cap')
    return data,len(ids)

def publish_mobile(out=None,quiet=False,force=False):
    configdir,study,outputs=mobile_paths()
    if out is None:out=outputs
    cfg_path=configdir/'config.json'
    if not cfg_path.is_file():
        if not quiet:print('[MOBILE] Not configured. Run: py -3 live_progress.py setup-mobile')
        return record_mobile_result(out,'NOT_CONFIGURED')
    cfg=json.loads(cfg_path.read_text(encoding='utf-8'))
    host=mobile_site_host(cfg['host'])
    site_id=cfg['site_id']
    if not isinstance(site_id,str) or not site_id or '/' in site_id:
        raise ValueError('Invalid configured Netlify site ID')
    install_trophy_ui(study)  # idempotent; questions and history untouched
    bundle,total=build_mobile_zip(study)
    digest=hashlib.sha256(bundle).hexdigest()
    logpath=configdir/'last_deploy.json'
    last=json.loads(logpath.read_text(encoding='utf-8')) if logpath.is_file() else {}
    if not force and digest==last.get('sha256'):
        return record_mobile_result(out,'UP_TO_DATE','Already published',url='https://'+host,questions=total)
    token=dpapi_decrypt_token(cfg['token_dpapi'])
    # Recheck site identity to avoid overwriting the wrong user-owned website.
    site=mobile_request('/sites/'+urllib.parse.quote(site_id,safe=''),token)
    candidate=str(site.get('ssl_url') or site.get('url') or '')
    if not candidate or mobile_site_host(candidate)!=host:
        raise ValueError('Netlify site identity mismatch; publication refused')
    record_mobile_result(out,'UPLOADING','Uploading verified AI Study package',questions=total)
    result=mobile_request('/sites/'+urllib.parse.quote(site_id,safe='')+'/deploys',token,'POST',bundle)
    depid=result.get('id')
    if not isinstance(depid,str) or not depid:
        raise RuntimeError('Netlify returned no deployment ID')
    state=str(result.get('state',''))
    for attempt in range(25):
        if state=='ready':break
        if state in ('error','failed'):raise RuntimeError('Netlify deployment failed')
        time.sleep(3)
        check=mobile_request('/deploys/'+urllib.parse.quote(depid,safe=''),token)
        state=str(check.get('state',''))
    if state!='ready':raise RuntimeError('Netlify deploy still processing; confirm in dashboard before retry')
    configdir.mkdir(parents=True,exist_ok=True)
    save_json(logpath,{'sha256':digest,'deployed_at':datetime.datetime.now().isoformat(),
                      'deploy_id':depid,'questions':total,'url':'https://'+host})
    outcome=record_mobile_result(out,'PUBLISHED','Live on original Netlify URL',
                                 url='https://'+host,questions=total)
    if not quiet:print('[MOBILE] PUBLISHED:',outcome['url'],'/',total,'questions')
    return outcome

def setup_mobile_sync():
    configdir,study,outputs=mobile_paths()
    print('AI Study -> existing Netlify PWA (one-time setup)')
    print('Before updating, export a backup from the smartphone AI Study.')
    original='https://spectacular-medovik-6118c6.netlify.app'
    url=input('Original Netlify site URL ['+original+']: ').strip() or original
    host=mobile_site_host(url)
    print('Create a personal access token in Netlify User settings > Applications.')
    token=getpass.getpass('Netlify personal access token (hidden input): ').strip()
    if not token:raise ValueError('No Netlify personal access token')
    site=mobile_request('/sites/'+urllib.parse.quote(host,safe=''),token)
    verified=str(site.get('ssl_url') or site.get('url') or '')
    if not verified or mobile_site_host(verified)!=host:
        raise ValueError('Token does not match the requested Netlify site')
    site_id=site.get('id')
    if not isinstance(site_id,str) or not site_id:raise ValueError('Netlify did not return site ID')
    print('Netlify site confirmed:',host)
    confirm=input('Deploy AI Study and replace live site files? Type YES: ').strip()
    if confirm!='YES':
        print('Canceled. No changes made.')
        return
    bundle,questions=build_mobile_zip(study)
    # Do not save credentials until app files have been validated.
    configdir.mkdir(parents=True,exist_ok=True)
    save_json(configdir/'config.json',{'host':host,'site_id':site_id,
                                      'token_dpapi':dpapi_encrypt_token(token)})
    try:
        result=publish_mobile(outputs,force=True)
        print('Smartphone URL:',result.get('url','(not ready)'))
        print('The phone may need an online restart to refresh the PWA cache.')
    except Exception:
        # Keep secured configuration so that user can retry without typing PAT.
        raise

# Inlined into an existing allowlisted updater file for compatibility with v0.4.2.
"""Idempotent achievement UI patch for AI Study PWA.

Derives achievements from existing attempt/perfect-award history. Does not touch
questions, exam answers, API credentials, or user progress.
"""
import hashlib
import re
from pathlib import Path

MARKER="<!-- AI_STUDY_TROPHIES_V1 -->"
SAVE_ORIGINAL="function save(){return commitState()}"
SAVE_PATCHED="function save(){const ok=commitState();if(ok&&typeof trophyRefresh==='function')trophyRefresh();return ok}"
RENDER_ORIGINAL="function render(){({home:renderHome,study:renderStudy,review:renderReview,analysis:renderAnalysis,manage:renderManage}[tab])();if(!session || tab!=='study'){let [line,mood]=defaultAiLine(tab);sayAi(line,mood)}syncTeacherActions()}"
RENDER_PATCHED=RENDER_ORIGINAL[:-1]+";if(typeof trophyRender==='function')trophyRender()}"

TROPHY_UI=r"""
<style id="ai-study-trophy-style">
.trophy-home{background:linear-gradient(140deg,#3c2946,#1c2948);border-color:#6e517c}
.trophy-header{display:flex;justify-content:space-between;align-items:center;gap:10px}
.trophy-home .trophy-count{font-size:30px;font-weight:850;color:#ffe2a0;margin:5px 0}
.trophy-home .trophy-sub{color:#ccdaf3;font-size:12px}
.trophy-progress{height:9px;background:#151d32;border-radius:12px;overflow:hidden;margin:9px 0}
.trophy-progress>span{display:block;height:100%;background:linear-gradient(90deg,#f7b76a,#ff83c6);border-radius:12px}
.trophy-home button{width:100%;margin-top:10px}
.trophy-shade{position:fixed;inset:0;background:#070b19de;z-index:150;display:flex;align-items:center;justify-content:center;padding:12px}
.trophy-shade[hidden]{display:none!important}
.trophy-dialog{width:min(720px,100%);max-height:min(86dvh,850px);overflow:auto;background:#17213a;border:1px solid #8c6797;border-radius:19px;padding:18px;box-shadow:0 24px 65px #000b}
.trophy-dialog header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.trophy-dialog h2{font-size:19px;margin:0}
.trophy-dialog .trophy-filters{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}
.trophy-filters button{padding:8px 11px;border:1px solid #53617c;background:#243454;color:#d9e8ff;border-radius:10px;font-size:12px}
.trophy-filters button[aria-pressed=true]{background:#714774;color:#fff;border-color:#ff9bcc}
.trophy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.trophy-item{background:#242d48;border:1px solid #556782;padding:13px;border-radius:13px;min-width:0}
.trophy-item.locked{opacity:.62;filter:grayscale(.7)}
.trophy-item .glyph{font-size:28px;float:right}
.trophy-item strong{display:block;color:#ffe6ad;font-size:13px}
.trophy-item small{color:#b8c6e0;display:block;margin-top:5px;font-size:12px;line-height:1.5}
.trophy-item .tier{color:#ffc7eb;font-size:10px;font-weight:700}
.trophy-item .trophy-condition{color:#b0d7ec;font-size:11px;margin-top:4px}
.trophy-toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:155;width:min(420px,calc(100% - 30px));background:linear-gradient(110deg,#493359,#24375f);border:2px solid #ffc47b;border-radius:16px;padding:14px 17px;color:#fff;box-shadow:0 14px 35px #000b;text-align:center;font-weight:bold}
.trophy-toast[hidden]{display:none!important}
@media(max-width:410px){.trophy-grid{grid-template-columns:1fr}.trophy-dialog{padding:13px}}
@media(prefers-reduced-motion:reduce){.trophy-toast{transition:none}}
</style>
<script id="ai-study-trophy-script">
(function(){
'use strict';
const achievements=[
 ['first','🌱','はじめの一歩','回答1問','回答数',1,'responses','ノートを開いたその瞬間が始まり！'],
 ['ans10','📗','十問十色','回答10問','回答数',10,'responses','まずは10問、いい調子！'],
 ['ans25','📚','勉強エンジン始動','回答25問','回答数',25,'responses','学習が習慣になってきたね'],
 ['ans50','🎒','努力家','回答50問','回答数',50,'responses','積み重ねが見えてきた！'],
 ['ans100','⚔️','SAA修行者','回答100問','回答数',100,'responses','100問を突破した実力'],
 ['ans200','🧭','知識の探検家','回答200問','回答数',200,'responses','200回のチャレンジ！'],
 ['ans300','🏰','問題の住人','回答300問','回答数',300,'responses','すごい学習量！'],
 ['ok1','✨','初正解','正解1問','正解数',1,'correct','最初の正解！'],
 ['ok10','⭐','十連星','累計10問正解','正解数',10,'correct','正しい判断を積み重ねたよ'],
 ['ok25','🌟','知識が芽吹く','累計25問正解','正解数',25,'correct','理解が広がってきたね'],
 ['ok50','💎','判断力アップ','累計50問正解','正解数',50,'correct','50問分の成果だよ'],
 ['ok100','🥇','百戦錬磨','累計100問正解','正解数',100,'correct','100問正解！'],
 ['ok200','👑','解答マスター','累計200問正解','正解数',200,'correct','たくさん理解した証だね'],
 ['streak3','🔥','三連撃','3問連続正解','連続正解',3,'bestStreak','3連続正解！'],
 ['streak5','⚡','波に乗ってる','5問連続正解','連続正解',5,'bestStreak','集中力ばっちり！'],
 ['streak10','🚀','覚醒の十連撃','10問連続正解','連続正解',10,'bestStreak','10連続は大きいよ'],
 ['day2','🌤️','また会えたね','2日連続学習','継続',2,'bestDays','2日続けて勉強したね'],
 ['day3','🪴','三日坊主卒業','3日連続学習','継続',3,'bestDays','続ける力がついてきた'],
 ['day7','🌈','一週間の積み重ね','7日連続学習','継続',7,'bestDays','継続は力！'],
 ['day14','🏅','学習習慣マスター','14日連続学習','継続',14,'bestDays','努力が日常になったよ'],
 ['unique10','🧩','問題探検','異なる問題を10問回答','初見挑戦',10,'unique','新しい知識に出会おう'],
 ['unique30','🗺️','知識の地図','異なる問題を30問回答','初見挑戦',30,'unique','広い範囲を学んだね'],
 ['unique50','🌍','AWS探究者','異なる問題を50問回答','初見挑戦',50,'unique','いろんな分野に触れたよ'],
 ['retry1','🔄','リベンジ成功','間違えた問題を後で1回正解','復習',1,'recoveries','間違いを理解に変えた！'],
 ['retry5','🛠️','弱点クラッシャー','間違えた問題を後で5回正解','復習',5,'recoveries','苦手が強みに変わるね'],
 ['guess3','🎯','直感が光る','迷い・推測で3問正解','挑戦',3,'uncertainWins','解説で根拠も確かめてね'],
 ['guess10','🧠','推理名人','迷い・推測で10問正解','挑戦',10,'uncertainWins','勘を知識に変えていこう'],
 ['perfect1','🏆','パーフェクト！','演習・模試で1回満点','特別',1,'perfect','アイ先生から大きな花丸！'],
 ['perfect3','🎊','満点コレクター','演習・模試で3回満点','特別',3,'perfect','3回も満点、お見事！'],
 ['sure1','🔍','思い込みを発見','確信して間違えた問題を1問発見','発見',1,'sureMistakes','気づくことが成長の入り口！']
];
let filter='all';
let previous=null;
let toastTimer=null;
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $t=id=>document.getElementById(id);
function metrics(){
  const records=(Array.isArray(attempts)?attempts:[]).filter(x=>x&&typeof x==='object')
      .slice().sort((a,b)=>Date.parse(a.ts||0)-Date.parse(b.ts||0));
  let correct=0,bestStreak=0,streak=0,sureMistakes=0,uncertainWins=0,recoveries=0;
  const wrongIds=new Set();
  const days=new Set();
  for(const r of records){
    if(r.correct){correct++;streak++;bestStreak=Math.max(bestStreak,streak);
      if(wrongIds.has(r.id)){recoveries++;wrongIds.delete(r.id)}
      if(r.confidence==='迷い'||r.confidence==='推測')uncertainWins++;
    }else{
      streak=0;if(r.id)wrongIds.add(r.id);
      if(r.confidence==='確信')sureMistakes++;
    }
    const d=new Date(r.ts);if(!Number.isNaN(d.getTime()))
      days.add(d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'));
  }
  let bestDays=0,daysStreak=0,prev=null;
  for(const key of [...days].sort()){
    const day=Date.parse(key+'T12:00:00');
    daysStreak=prev!==null&&Math.round((day-prev)/86400000)===1?daysStreak+1:1;
    bestDays=Math.max(bestDays,daysStreak);prev=day;
  }
  return {responses:records.length,correct,bestStreak,bestDays,
    unique:new Set(records.map(x=>x.id).filter(Boolean)).size,
    recoveries,uncertainWins,perfect:Array.isArray(perfectAwards)?perfectAwards.length:0,sureMistakes};
}
function earned(stats){return achievements.filter(t=>(stats[t[6]]||0)>=t[5])}
function paintTrophyHome(){
  const side=document.querySelector('#screen-home .home-sidebar');
  if(!side)return;
  const s=metrics(),unlocked=earned(s).length, pct=Math.round(100*unlocked/achievements.length);
  let node=$t('trophyHomeCard');
  if(!node){
    node=document.createElement('section');
    node.id='trophyHomeCard';node.className='card dash-card trophy-home';
    side.insertBefore(node,side.firstChild);
  }
  node.innerHTML='<div class="trophy-header"><h2 style="margin:0">🏆 トロフィー</h2><span>✨</span></div>'+
    '<div class="trophy-count">'+unlocked+' / '+achievements.length+'</div>'+
    '<div class="trophy-progress"><span style="width:'+pct+'%"></span></div>'+
    '<div class="trophy-sub">これまでの学習履歴から自動判定。獲得を目指そう！</div>'+
    '<button class="btn secondary" type="button" id="showTrophies">トロフィー一覧を見る →</button>';
  $t('showTrophies').addEventListener('click',openTrophies);
}
function drawGrid(){
  const grid=$t('trophyGrid');if(!grid)return;
  const stats=metrics(),ids=new Set(earned(stats).map(t=>t[0]));
  const visible=achievements.filter(t=>filter==='all'||(filter==='unlocked'?ids.has(t[0]):!ids.has(t[0])));
  grid.innerHTML=visible.length?visible.map(t=>{
    const open=ids.has(t[0]);
    return '<article class="trophy-item '+(open?'':'locked')+'"><span class="glyph" aria-hidden="true">'+(open?t[1]:'🔒')+'</span>'+
      '<span class="tier">'+safe(t[4])+' · '+(open?'獲得済み':'未獲得')+'</span>'+
      '<strong>'+safe(t[2])+'</strong><small>'+safe(t[7])+'</small>'+
      '<div class="trophy-condition">'+safe(t[3])+' · '+Math.min(stats[t[6]]||0,t[5])+'/'+t[5]+'</div></article>';
  }).join(''):'<p class="muted">ここにはまだトロフィーがないよ。</p>';
  const count=$t('trophyModalCount');if(count)count.textContent=ids.size+' / '+achievements.length+' 獲得';
  document.querySelectorAll('[data-trophy-filter]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn.dataset.trophyFilter===filter)));
}
function ensureModal(){
  if($t('trophyModal'))return;
  const shade=document.createElement('div');shade.id='trophyModal';shade.className='trophy-shade';shade.hidden=true;
  shade.innerHTML='<section class="trophy-dialog" role="dialog" aria-modal="true" aria-labelledby="trophyTitle">'+
    '<header><h2 id="trophyTitle">🏆 学習トロフィー</h2><button class="btn secondary" type="button" id="closeTrophies">閉じる ×</button></header>'+
    '<p class="tiny" id="trophyModalCount"></p>'+
    '<div class="trophy-filters"><button data-trophy-filter="all" aria-pressed="true">すべて</button>'+
    '<button data-trophy-filter="unlocked" aria-pressed="false">獲得済み</button>'+
    '<button data-trophy-filter="locked" aria-pressed="false">未獲得</button></div>'+
    '<div class="trophy-grid" id="trophyGrid"></div>'+
    '<p class="tiny">※記録はこの端末の学習履歴をもとに計算。トロフィーは認定試験の合否を保証するものではありません。</p></section>';
  document.body.append(shade);
  shade.addEventListener('click',e=>{if(e.target===shade)closeTrophies()});
  $t('closeTrophies').addEventListener('click',closeTrophies);
  shade.querySelectorAll('[data-trophy-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.trophyFilter;drawGrid()}));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!shade.hidden)closeTrophies()});
  const toast=document.createElement('div');toast.id='trophyToast';toast.className='trophy-toast';toast.hidden=true;toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');
  document.body.append(toast);
}
function openTrophies(){
  ensureModal();drawGrid();const box=$t('trophyModal');box.hidden=false;box.querySelector('#closeTrophies').focus();
}
function closeTrophies(){$t('trophyModal').hidden=true;const btn=$t('showTrophies');if(btn)btn.focus()}
function trophyRender(){
  ensureModal();paintTrophyHome();
  if(!$t('trophyModal').hidden)drawGrid();
}
function trophyRefresh(){
  const ids=new Set(earned(metrics()).map(t=>t[0]));
  const newly=previous?[...ids].filter(id=>!previous.has(id)):[];
  previous=ids;
  trophyRender();
  if(newly.length){
    const t=achievements.find(t=>t[0]===newly[0]);
    const message=t[1]+' トロフィー獲得！ '+t[2]+(newly.length>1?' ＋'+(newly.length-1)+'個':'');
    const toast=$t('trophyToast');toast.textContent=message;toast.hidden=false;
    if(typeof sayAi==='function')sayAi('🏆 '+t[2]+' 獲得！ よく頑張ったねっ💕','トロフィー獲得');
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true},4500);
  }
}
window.trophyRender=trophyRender;
window.trophyRefresh=trophyRefresh;
previous=new Set(earned(metrics()).map(t=>t[0]));
trophyRender();
})();
</script>
"""

def install_trophy_ui(study:Path)->bool:
    """Inject trophy UI into the current local PWA without changing questions."""
    study=Path(study)
    path=study/'index.html'
    sw=study/'sw.js'
    original=path.read_text(encoding='utf-8')
    if MARKER in original:
        return False
    if original.count(SAVE_ORIGINAL)!=1 or original.count(RENDER_ORIGINAL)!=1:
        raise ValueError('Unknown AI Study version; trophy patch refused safely')
    if original.count('</body>')!=1:
        raise ValueError('AI Study document structure unexpected')
    updated=original.replace(SAVE_ORIGINAL,SAVE_PATCHED)
    updated=updated.replace(RENDER_ORIGINAL,RENDER_PATCHED)
    updated=updated.replace('</body>',MARKER+'\n'+TROPHY_UI+'</body>')
    if not sw.is_file():raise ValueError('Missing PWA service worker')
    sw_text=sw.read_text(encoding='utf-8')
    old_cache=re.search(r"const CACHE='ai-study-[^']+';",sw_text)
    if not old_cache:raise ValueError('Unknown AI Study PWA cache; refused')
    new_cache="const CACHE='ai-study-trophy-"+hashlib.sha256(updated.encode()).hexdigest()[:12]+"';"
    sw_updated=sw_text[:old_cache.start()]+new_cache+sw_text[old_cache.end():]
    a=path.with_suffix('.html.trophy.tmp');b=sw.with_suffix('.js.trophy.tmp')
    a.write_text(updated,encoding='utf-8');b.write_text(sw_updated,encoding='utf-8')
    a.replace(path)
    try:b.replace(sw)
    except Exception:
        restore=path.with_suffix('.html.restore.tmp')
        restore.write_text(original,encoding='utf-8');restore.replace(path)
        raise
    return True


if __name__=='__main__':
    cmd=sys.argv[1:] if len(sys.argv)>1 else []
    try:
        if cmd==['setup-mobile']:setup_mobile_sync()
        elif cmd==['deploy-mobile']:publish_mobile(force=True)
        elif cmd==['status-mobile']:
            _,_,out=mobile_paths()
            p=out/'mobile_publish_status.json'
            print(p.read_text(encoding='utf-8') if p.exists() else 'No mobile deployment yet')
        else:print('Usage: py -3 live_progress.py setup-mobile|deploy-mobile|status-mobile')
    except Exception as exc:
        print('[MOBILE] ERROR:',str(exc)[:210])
        sys.exit(1)


