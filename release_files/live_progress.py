"""Progress and fail-closed LOCAL AI Study sync. No network or model API calls."""
import datetime, functools, hashlib, html, io, json, re, zipfile
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


# No unattended AI-only question is eligible for publication, including old
# Gemini PASS records. An explicit independent/local approval record, bound to
# the exact question bytes and AWS documentation evidence, is required.
def review_payload_digest(question):
    if not isinstance(question,dict):
        raise ValueError('問題の形式が不正')
    fields=('id','exam','type','domain','topic','difficulty',
            'question','choices','correct','explanation')
    canonical={k:question.get(k) for k in fields}
    encoded=json.dumps(canonical,ensure_ascii=False,sort_keys=True,
                       separators=(',',':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def is_independently_approved(question, approvals):
    """Fail closed on every absent/stale/AI-written or poorly scoped approval."""
    qid=question.get('id') if isinstance(question,dict) else None
    entry=approvals.get(qid) if isinstance(approvals,dict) and isinstance(qid,str) else None
    if not isinstance(entry,dict):
        return False
    if entry.get('human_approved') is not True or entry.get('official_documentation_verified') is not True:
        return False
    source=entry.get('documentation_url')
    if not isinstance(source,str) or not re.fullmatch(
            r'https://docs[.]aws[.]amazon[.]com/[A-Za-z0-9/_.%#?=&-]+',source):
        return False
    return entry.get('question_sha256')==review_payload_digest(question)


def sync_study_pack(output_dir):
    """Merge independently verified proposals only; AI PASS is not enough."""
    out=Path(output_dir);study=out.parent.parent/'AI_Study'
    path=study/'questions.json';index=study/'index.html';sw=study/'sw.js'
    proposals=out/'AI_Study_追加候補.json'
    staged=out/'revision_staged.json'  # local operator-approved candidates are staged separately
    def report(state,**details):
        result={'status':state,'updated_at':datetime.datetime.now().astimezone().isoformat(timespec='seconds'),**details}
        save_json(out/'study_sync_status.json',result)
        return result
    if not (proposals.is_file() or staged.is_file()) or not all(
            p.is_file() for p in (path,index,sw)):
        return report('WAITING',message='問題パックまたはアプリのファイル待ち')
    try:
        incoming=[]
        # Neither input file may replace or edit the other's records.
        # Treat duplicate IDs across files as ambiguous and fail closed.
        for candidate_file in (proposals,staged):
            if not candidate_file.is_file():
                continue
            obj=json.loads(candidate_file.read_text(encoding='utf-8-sig'))
            items=obj.get('questions') if isinstance(obj,dict) else None
            if not isinstance(items,list):
                raise ValueError('追加候補は questions 配列である必要があります')
            incoming.extend(items)
        base=json.loads(path.read_text(encoding='utf-8-sig'))
        current=base['questions']
        original_html=index.read_text(encoding='utf-8')
        m=re.search(r'(<script id="default-pack" type="application/json">)(.*?)(</script>)',original_html,re.S)
        if not m:raise ValueError('初期問題データの埋め込みタグがありません')
        inline=json.loads(m.group(2))['questions']
        if not isinstance(current,list) or not isinstance(inline,list):
            raise ValueError('問題データは配列である必要があります')
        ids=[q['id'] for q in current]
        if ids != [q['id'] for q in inline] or len(ids)!=len(set(ids)):
            raise ValueError('questions.jsonとindex.htmlが不一致。元データを保護して中止')
        # Local work/ file only. It must not be included in the public ZIP.
        approvals_file=out.parent/'content_approvals.json'
        registry=json.loads(approvals_file.read_text(encoding='utf-8')) if approvals_file.exists() else {}
        approvals=registry.get('approvals',{}) if isinstance(registry,dict) else {}
        if not isinstance(approvals,dict):
            raise ValueError('独立承認台帳の形式が不正')
        existing=set(ids); seen=set(); add=[]; blocked=0
        for q in incoming:
            qid=q.get('id') if isinstance(q,dict) else None
            if not isinstance(qid,str) or not qid.startswith('SAA-AUTO-') or qid in seen:
                raise ValueError('不正な問題IDまたはパック内で重複したID')
            seen.add(qid)
            if qid in existing:continue
            if not is_independently_approved(q,approvals):
                blocked+=1
                continue
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
        if not add:
            return report('BLOCKED_UNVERIFIED' if blocked else 'UNCHANGED',
                          total=len(current),newly_added=0,unverified_skipped=blocked,
                          message='人手確認・AWS資料との照合がないAI候補は同期しません' if blocked else '')

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
        return report('SYNCED',total=len(merged['questions']),newly_added=len(add),unverified_skipped=blocked,
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
RENDER_PATCHED=RENDER_ORIGINAL[:-1]+";if(typeof trophyRender==='function')trophyRender();if(typeof aiGrowthRender==='function')aiGrowthRender()}"

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
.trophy-item[data-tier="ゴールド"]{border-color:#d5a958}
.trophy-item[data-tier="レジェンド"]{border-color:#ce88f3;background:#342954}
#trophyTierSelect{background:#253553;color:#ecedff;border:1px solid #6679a0;border-radius:8px;padding:7px;margin:8px 0 12px}
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
const trophyExtras=[
  ["bonus_responses_75","🪜","七十五の階段","回答数75問","回答数",75,"responses","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_responses_150","🛤️","150問の旅路","回答数150問","回答数",150,"responses","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_responses_250","⚔️","進撃の250問","回答数250問","回答数",250,"responses","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_responses_500","🧱","五百問の壁","回答数500問","回答数",500,"responses","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_responses_1000","🚢","千問の航海","回答数1000問","回答数",1000,"responses","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_correct_75","🌼","正解の積み重ね","累計正解75問","正解数",75,"correct","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_correct_125","👣","確かな一歩","累計正解125問","正解数",125,"correct","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_correct_150","🕯️","理解の灯火","累計正解150問","正解数",150,"correct","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_correct_250","🔨","知識の鍛冶屋","累計正解250問","正解数",250,"correct","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_correct_500","🌌","正解の星座","累計正解500問","正解数",500,"correct","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_unique_20","🪻","新顔歓迎","異なる問題を20問","初見挑戦",20,"unique","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_unique_75","🧪","75問の発見","異なる問題を75問","初見挑戦",75,"unique","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_unique_100","🗾","百問百景","異なる問題を100問","初見挑戦",100,"unique","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_unique_125","🔭","見聞を広げる","異なる問題を125問","初見挑戦",125,"unique","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_unique_150","🌐","世界が広がる","異なる問題を150問","初見挑戦",150,"unique","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_unique_175","🏛️","知の回廊","異なる問題を175問","初見挑戦",175,"unique","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_unique_200","📖","問題図鑑","異なる問題を200問","初見挑戦",200,"unique","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_bestStreak_4","✨","四連のひらめき","連続正解4問","連続正解",4,"bestStreak","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_bestStreak_7","💫","七連の集中","連続正解7問","連続正解",7,"bestStreak","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_bestStreak_12","⚡","十二の閃光","連続正解12問","連続正解",12,"bestStreak","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_bestStreak_15","🌊","好調の波","連続正解15問","連続正解",15,"bestStreak","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_bestStreak_20","🛡️","鉄壁の二十連","連続正解20問","連続正解",20,"bestStreak","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_bestStreak_30","🐉","連勝の伝説","連続正解30問","連続正解",30,"bestStreak","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_bestDays_4","☀️","四日目の約束","連続学習4日","継続",4,"bestDays","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_bestDays_5","🖐️","五日連続の証","連続学習5日","継続",5,"bestDays","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_bestDays_10","🌱","十日の日課","連続学習10日","継続",10,"bestDays","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_bestDays_21","🎋","三週間の軌跡","連続学習21日","継続",21,"bestDays","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_bestDays_30","🗓️","一か月の積み重ね","連続学習30日","継続",30,"bestDays","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_recoveries_2","🔁","もう一度の勝利","間違えた問題を後で正解2回","復習",2,"recoveries","苦手を一つずつ理解に変えた成果！","ブロンズ"],
  ["bonus_recoveries_3","📐","失敗は先生","間違えた問題を後で正解3回","復習",3,"recoveries","苦手を一つずつ理解に変えた成果！","ブロンズ"],
  ["bonus_recoveries_10","🧹","リベンジ10","間違えた問題を後で正解10回","復習",10,"recoveries","苦手を一つずつ理解に変えた成果！","シルバー"],
  ["bonus_recoveries_15","🪓","苦手攻略隊","間違えた問題を後で正解15回","復習",15,"recoveries","苦手を一つずつ理解に変えた成果！","ゴールド"],
  ["bonus_recoveries_25","⚗️","弱点の錬金術師","間違えた問題を後で正解25回","復習",25,"recoveries","苦手を一つずつ理解に変えた成果！","レジェンド"],
  ["bonus_uncertainWins_5","🌾","仮説の芽","迷い・推測で正解5問","挑戦",5,"uncertainWins","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_uncertainWins_15","🕵️","推理を磨く","迷い・推測で正解15問","挑戦",15,"uncertainWins","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_uncertainWins_25","🔮","迷いの向こう","迷い・推測で正解25問","挑戦",25,"uncertainWins","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_uncertainWins_40","🧬","仮説の達人","迷い・推測で正解40問","挑戦",40,"uncertainWins","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_uncertainWins_50","🧠","考え抜いた証","迷い・推測で正解50問","挑戦",50,"uncertainWins","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_perfect_2","🎀","満点ふたつ","満点達成2回","特別",2,"perfect","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_perfect_5","🌟","五つ星の満点","満点達成5回","特別",5,"perfect","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_perfect_10","🏵️","満点の達人","満点達成10回","特別",10,"perfect","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_perfect_20","👑","パーフェクト伝説","満点達成20回","特別",20,"perfect","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_sureCorrect_10","🧠","確信の一歩","確信して正解10問","理解",10,"sureCorrect","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_sureCorrect_25","🔎","根拠を持って","確信して正解25問","理解",25,"sureCorrect","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_sureCorrect_50","🔐","確信の蓄積","確信して正解50問","理解",50,"sureCorrect","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_sureCorrect_100","💠","自信と実力","確信して正解100問","理解",100,"sureCorrect","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_studyDays_5","💐","五日分の努力","累計学習日数5日","継続",5,"studyDays","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_studyDays_10","🌅","十日間の前進","累計学習日数10日","継続",10,"studyDays","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_studyDays_15","🌙","半月の学び","累計学習日数15日","継続",15,"studyDays","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_studyDays_30","🏔️","毎日積み上げる","累計学習日数30日","継続",30,"studyDays","勉強した分だけ、自分の力になるよ！","レジェンド"],
  ["bonus_domainsSeen_2","🗺️","分野をまたぐ","挑戦した分野数2分野","分野",2,"domainsSeen","分野を横断する視点を育てよう！","ブロンズ"],
  ["bonus_domainsSeen_3","🪐","三つの世界","挑戦した分野数3分野","分野",3,"domainsSeen","分野を横断する視点を育てよう！","ブロンズ"],
  ["bonus_domainsSeen_4","🧭","四方に広がる","挑戦した分野数4分野","分野",4,"domainsSeen","分野を横断する視点を育てよう！","シルバー"],
  ["bonus_balancedCoverage_10","🌉","四分野を一周","4分野それぞれ10問回答","分野",10,"balancedCoverage","各分野をバランスよく学んだね！","ゴールド"],
  ["bonus_balancedCoverage_20","🛰️","四分野を極める","4分野それぞれ20問回答","分野",20,"balancedCoverage","AWS SAAの4分野すべてで演習を積んだよ！","レジェンド"],
  ["bonus_domainsMastered_1","🌿","得意分野の種","正答率70%以上・5問以上の分野数1分野","分野",1,"domainsMastered","分野を横断する視点を育てよう！","ブロンズ"],
  ["bonus_domainsMastered_2","🪵","強みがふたつ","正答率70%以上・5問以上の分野数2分野","分野",2,"domainsMastered","分野を横断する視点を育てよう！","シルバー"],
  ["bonus_domainsMastered_3","🏗️","三分野の柱","正答率70%以上・5問以上の分野数3分野","分野",3,"domainsMastered","分野を横断する視点を育てよう！","ゴールド"],
  ["bonus_domainsMastered_4","💎","多方面で安定","正答率70%以上・5問以上の分野数4分野","分野",4,"domainsMastered","分野を横断する視点を育てよう！","レジェンド"],
  ["bonus_perfectMax_5","🏅","五問の完全勝利","一度の満点演習の問題数5問","満点",5,"perfectMax","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_perfectMax_10","🏆","十問パーフェクト","一度の満点演習の問題数10問","満点",10,"perfectMax","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_perfectMax_20","🥇","二十問の栄光","一度の満点演習の問題数20問","満点",20,"perfectMax","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_bestRate20_70","📈","20問で7割","累計20問以上時点の最高正答率70％","正答率",70,"bestRate20","積み重ねた正答率が力になったね！","ブロンズ"],
  ["bonus_bestRate50_75","💡","50問で75％","累計50問以上時点の最高正答率75％","正答率",75,"bestRate50","積み重ねた正答率が力になったね！","ブロンズ"],
  ["bonus_bestRate100_80","📊","100問で8割","累計100問以上時点の最高正答率80％","正答率",80,"bestRate100","積み重ねた正答率が力になったね！","ブロンズ"],
  ["bonus_bestRate150_85","🎖️","150問で85％","累計150問以上時点の最高正答率85％","正答率",85,"bestRate150","積み重ねた正答率が力になったね！","ブロンズ"],
  ["bonus_maxDaily_10","🍀","今日は10問","1日の回答数10問","一日挑戦",10,"maxDaily","勉強した分だけ、自分の力になるよ！","ブロンズ"],
  ["bonus_maxDaily_20","🌺","学びの20問","1日の回答数20問","一日挑戦",20,"maxDaily","勉強した分だけ、自分の力になるよ！","シルバー"],
  ["bonus_maxDaily_30","🏃","一日30問","1日の回答数30問","一日挑戦",30,"maxDaily","勉強した分だけ、自分の力になるよ！","ゴールド"],
  ["bonus_maxDaily_50","🥋","特訓の50問","1日の回答数50問","一日挑戦",50,"maxDaily","勉強した分だけ、自分の力になるよ！","レジェンド"]
];
achievements.push(...trophyExtras);
let filter='all';
let tierFilter='all';
let previous=null;
let toastTimer=null;
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $t=id=>document.getElementById(id);
function metrics(){
  const records=(Array.isArray(attempts)?attempts:[]).filter(x=>x&&typeof x==='object')
      .slice().sort((a,b)=>Date.parse(a.ts||0)-Date.parse(b.ts||0));
  let correct=0,bestStreak=0,streak=0,sureMistakes=0,uncertainWins=0,recoveries=0;
  let sureCorrect=0,domainsMastered=0,bestRate20=0,bestRate50=0,bestRate100=0,bestRate150=0;
  const wrongIds=new Set(),days=new Set(),dayCounts=new Map(),domainStats=new Map();
  for(const r of records){
    if(r.correct){
      correct++;streak++;bestStreak=Math.max(bestStreak,streak);
      if(wrongIds.has(r.id)){recoveries++;wrongIds.delete(r.id)}
      if(r.confidence==='迷い'||r.confidence==='推測')uncertainWins++;
      if(r.confidence==='確信')sureCorrect++;
    }else{
      streak=0;if(r.id)wrongIds.add(r.id);
      if(r.confidence==='確信')sureMistakes++;
    }
    if(r.domain){
      const d=domainStats.get(r.domain)||{n:0,c:0};d.n++;if(r.correct)d.c++;
      domainStats.set(r.domain,d);
      domainsMastered=Math.max(domainsMastered,[...domainStats.values()].filter(v=>v.n>=5&&v.c/v.n>=.7).length);
    }
    const date=new Date(r.ts);
    if(!Number.isNaN(date.getTime())){
      const key=date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');
      days.add(key);dayCounts.set(key,(dayCounts.get(key)||0)+1);
    }
  }
  let runningCorrect=0;
  for(let i=0;i<records.length;i++){
    if(records[i].correct)runningCorrect++;
    const rate=100*runningCorrect/(i+1);
    if(i+1>=20)bestRate20=Math.max(bestRate20,rate);
    if(i+1>=50)bestRate50=Math.max(bestRate50,rate);
    if(i+1>=100)bestRate100=Math.max(bestRate100,rate);
    if(i+1>=150)bestRate150=Math.max(bestRate150,rate);
  }
  let bestDays=0,daysStreak=0,prev=null;
  for(const key of [...days].sort()){
    const day=Date.parse(key+'T12:00:00');
    daysStreak=prev!==null&&Math.round((day-prev)/86400000)===1?daysStreak+1:1;
    bestDays=Math.max(bestDays,daysStreak);prev=day;
  }
  return {responses:records.length,correct,bestStreak,bestDays,studyDays:days.size,
    maxDaily:Math.max(0,...dayCounts.values()),
    unique:new Set(records.map(x=>x.id).filter(Boolean)).size,domainsSeen:domainStats.size,domainsMastered,
    balancedCoverage:Object.keys(pack.domains||{}).length?Math.min(...Object.keys(pack.domains).map(k=>(domainStats.get(k)||{n:0}).n)):0,
    recoveries,uncertainWins,sureCorrect,bestRate20,bestRate50,bestRate100,bestRate150,
    perfect:Array.isArray(perfectAwards)?perfectAwards.length:0,
    perfectMax:Math.max(0,...(Array.isArray(perfectAwards)?perfectAwards:[]).map(a=>Number(a.count)||0)),
    sureMistakes};
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
function trophyTier(t){
  if(t[8])return t[8];
  const x=t[5],metric=t[6];
  if(metric==='bestDays')return x>=14?'レジェンド':x>=7?'ゴールド':x>=3?'シルバー':'ブロンズ';
  if(metric==='bestStreak')return x>=10?'レジェンド':x>=5?'ゴールド':x>=3?'シルバー':'ブロンズ';
  if(metric==='perfect')return x>=3?'ゴールド':x>=1?'シルバー':'ブロンズ';
  if(x>=200)return 'レジェンド';
  if(x>=50)return 'ゴールド';
  if(x>=10)return 'シルバー';
  return 'ブロンズ';
}
function drawGrid(){
  const grid=$t('trophyGrid');if(!grid)return;
  const stats=metrics(),ids=new Set(earned(stats).map(t=>t[0]));
  const visible=achievements.filter(t=>(filter==='all'||(filter==='unlocked'?ids.has(t[0]):!ids.has(t[0])))
    &&(tierFilter==='all'||trophyTier(t)===tierFilter));
  grid.innerHTML=visible.length?visible.map(t=>{
    const open=ids.has(t[0]),tier=trophyTier(t);
    return '<article class="trophy-item '+(open?'':'locked')+'" data-tier="'+safe(tier)+'"><span class="glyph" aria-hidden="true">'+(open?t[1]:'🔒')+'</span>'+
      '<span class="tier">'+safe(tier)+' · '+safe(t[4])+' · '+(open?'獲得済み':'未獲得')+'</span>'+
      '<strong>'+safe(t[2])+'</strong><small>'+safe(t[7])+'</small>'+
      '<div class="trophy-condition">'+safe(t[3])+' · '+Math.min(stats[t[6]]||0,t[5])+'/'+t[5]+'</div></article>';
  }).join(''):'<p class="muted">この条件のトロフィーはないよ。</p>';
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
    '<label class="tiny" for="trophyTierSelect">ランク： <select id="trophyTierSelect" aria-label="トロフィーランク"><option value="all">全ランク</option><option>ブロンズ</option><option>シルバー</option><option>ゴールド</option><option>レジェンド</option></select></label>'+
    '<div class="trophy-grid" id="trophyGrid"></div>'+
    '<p class="tiny">※記録はこの端末の学習履歴をもとに計算。トロフィーは認定試験の合否を保証するものではありません。</p></section>';
  document.body.append(shade);
  shade.addEventListener('click',e=>{if(e.target===shade)closeTrophies()});
  $t('closeTrophies').addEventListener('click',closeTrophies);
  shade.querySelectorAll('[data-trophy-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.trophyFilter;drawGrid()}));
  $t('trophyTierSelect').addEventListener('change',e=>{tierFilter=e.target.value;drawGrid()});
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

<!-- AI_STUDY_GROWTH_V1 -->
<style id="ai-study-growth-style">
.growth-card{background:linear-gradient(145deg,#342344,#182c48);border:1px solid #ac78c2}
.growth-track{height:9px;background:#141b32;border-radius:10px;overflow:hidden;margin:9px 0}
.growth-track>span{display:block;height:100%;background:linear-gradient(90deg,#f7bd70,#f690d8)}
.growth-modal{position:fixed;inset:0;z-index:180;display:flex;align-items:center;justify-content:center;padding:10px;background:#05091be6}
.growth-modal[hidden]{display:none!important}
.growth-panel{width:min(680px,100%);max-height:calc(100dvh - 20px);overflow:auto;background:#1b2540;border:1px solid #d38bc3;border-radius:16px;padding:14px;color:#ebf0ff}
.growth-panel header{display:flex;gap:12px;justify-content:space-between;align-items:center;margin-bottom:12px}
.growth-panel header h2{margin:0;font-size:clamp(18px,4.5vw,23px)}
.growth-panel header button{white-space:nowrap;flex-shrink:0;padding:10px 13px}
.growth-stage{border-radius:18px;background:radial-gradient(circle at 25% 15%,#7c5584,#232a51 65%);border:1px solid #86709d;padding:16px;display:flex;align-items:center;gap:18px;overflow:hidden}
.growth-stage[data-scene="sakura"]{background:radial-gradient(circle at 20% 10%,#d983ad,#8d538a,#2b3158)}
.growth-stage[data-scene="night"]{background:radial-gradient(circle at 70% 10%,#477ab2,#232958,#0d152c)}
.growth-stage[data-scene="sparkle"]{background:radial-gradient(circle at 20% 20%,#ffd48a,#ae6ba0,#382454)}
.growth-stage[data-scene="lab"]{background:linear-gradient(135deg,#276f75,#2e3c69,#1c2850)}
.growth-stage[data-scene="royal"]{background:radial-gradient(circle,#ad87d4,#5a4687,#24244c)}
.growth-portrait{width:min(42%,210px);aspect-ratio:1;flex-shrink:0;border:3px solid #ffcaee;border-radius:50%;overflow:hidden;box-shadow:0 0 27px #eca9ee99;background:#34385e}
.growth-portrait img{display:block;width:100%;height:100%;object-fit:cover}
.growth-stage[data-scene="sparkle"] .growth-portrait,.growth-stage[data-scene="royal"] .growth-portrait{box-shadow:0 0 39px #ffe7a0}
.growth-info{min-width:0;flex:1}
.growth-info b{color:#ffe8b5;font-size:19px}
.growth-info .tiny{color:#ecdeff}
.growth-speech{margin-top:12px;background:#ffeaf8;color:#553c59;border-radius:11px;padding:12px;font-size:13px;font-weight:650;line-height:1.6}
.growth-actions{display:flex;gap:8px;margin-top:10px}
.growth-actions button{flex:1;padding:10px;min-width:0}
.growth-scenes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:11px 0}
.growth-scenes button{border:1px solid #7183b0;background:#2b3a5b;color:#f1ecff;border-radius:10px;padding:10px 4px;font-size:12px}
.growth-scenes button[aria-pressed="true"]{border:2px solid #ffbde4;background:#68476e}
.growth-scenes button:disabled{opacity:.42}
.growth-unlocks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.growth-unlock{background:#283556;border-radius:12px;padding:11px;border:1px solid #637397;font-size:12px}
.growth-unlock.locked{opacity:.55;filter:grayscale(.75)}
.growth-unlock strong{display:block;color:#ffe2a8;margin:5px 0}
@media(max-width:440px){.growth-stage{flex-direction:column;gap:8px}.growth-portrait{width:min(55vw,190px)}.growth-info{text-align:center}.growth-scenes{grid-template-columns:repeat(2,minmax(0,1fr))}.growth-unlocks{grid-template-columns:1fr}}
</style>
<script id="ai-study-growth-script">
(()=>{
'use strict';
const $g=id=>document.getElementById(id);
const rewards=[
[1,'🎀','いつものアイ先生','アイ先生と学習開始'],
[2,'😊','笑顔','一緒に学習しよう'],
[3,'🌸','桜色ルーム','背景を変更できる'],
[5,'💬','応援メッセージ','会話ボタンで応援'],
[7,'🌙','星空ルーム','背景を変更できる'],
[8,'🖤','衣装の解放記録','衣装画像は制作待ち'],
[10,'✨','きらきら演出','背景を変更できる'],
[15,'🔬','クラウドラボ','背景を変更できる'],
[20,'👑','クラウドの相棒','ロイヤル背景を解放'],
[30,'💝','特別な応援','継続へのメッセージ']
];
const scenes=[['base',1,'💛 いつもの部屋'],['sakura',3,'🌸 桜色'],['night',7,'🌙 星空'],['sparkle',10,'✨ きらきら'],['lab',15,'🔬 ラボ'],['royal',20,'👑 ロイヤル']];
const storageKey='ai-study-growth-scene-v1';
let selected='base',talk=0;
try{selected=localStorage.getItem(storageKey)||'base'}catch(e){}
function calculate(){
 const rows=Array.isArray(attempts)?attempts:[];
 const unique=new Set(),recovered=new Set(),mistakes=new Set();
 let xp=0,correct=0,recoveries=0;
 for(const r of rows){
  if(!r||typeof r!=='object')continue;
  const key=String(r.id||'');xp+=5;
  if(r.correct){correct++;if(key&&!unique.has(key))xp+=10;
   if(key&&mistakes.has(key)&&!recovered.has(key)){xp+=15;recoveries++;recovered.add(key)}
  }else if(key){mistakes.add(key);recovered.delete(key)}
  if(key)unique.add(key);
 }
 const perfect=Array.isArray(perfectAwards)?perfectAwards.length:0;xp+=perfect*25;
 let level=1,threshold=100,remaining=xp;
 while(remaining>=threshold&&level<100){remaining-=threshold;level++;threshold=100+Math.floor((level-1)/5)*50}
 return {xp,level,remaining,next:level>=100?0:threshold,correct,answered:rows.length,perfect,recoveries};
}
function stageName(n){return n>=20?'👑 クラウドの相棒':n>=10?'✨ ベテランの相棒':n>=5?'💖 頼れるパートナー':'🌱 新米パートナー'}
function summary(s){
 const pct=s.next?Math.round(s.remaining/s.next*100):100;
 return '<b>💕 アイ先生 Lv.'+s.level+'</b><div class="tiny">'+stageName(s.level)+'</div><div class="tiny">累計 '+s.xp+' XP ・ 報酬 '+rewards.filter(r=>s.level>=r[0]).length+'/'+rewards.length+'</div><div class="growth-track"><span style="width:'+pct+'%"></span></div><div class="tiny">'+(s.next?s.remaining+'/'+s.next+' XP':'最大レベル！')+'</div>';
}
function ensureModal(){
 if($g('growthModal'))return;
 const node=document.createElement('div');node.id='growthModal';node.className='growth-modal';node.hidden=true;
 node.innerHTML='<section class="growth-panel" role="dialog" aria-modal="true" aria-labelledby="growthTitle"><header><h2 id="growthTitle">💕 アイ先生 育成ルーム</h2><button class="btn secondary" id="growthClose" type="button">閉じる ×</button></header>'+
 '<div class="growth-stage" id="growthStage" data-scene="base"><div class="growth-portrait"><img src="./ai-teacher-avatar.webp" alt="オリジナルのアイ先生" width="346" height="350"></div><div class="growth-info" id="growthSummary"></div></div>'+
 '<div class="growth-speech" id="growthSpeech" aria-live="polite">ユウ、今日も一緒に頑張ろうねっ💕</div>'+
 '<div class="growth-actions"><button class="btn secondary" id="growthTalk" type="button">💬 話す</button><button class="btn secondary" id="growthPractice" type="button">📚 勉強する</button></div>'+
 '<h3 style="font-size:15px;margin:20px 0 8px">🎨 解放したルームを選ぼう</h3><div class="growth-scenes" id="growthScenes"></div>'+
 '<h3 style="font-size:15px;margin:20px 0 8px">🎁 成長報酬</h3><div class="growth-unlocks" id="growthRewards"></div>'+
 '<p class="tiny">XPは学習履歴から算出。背景・演出は実際に切替可能。衣装画像・音声は今後追加するよ。</p></section>';
 document.body.appendChild(node);
 $g('growthClose').addEventListener('click',()=>node.hidden=true);
 node.addEventListener('click',e=>{if(e.target===node)node.hidden=true});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!node.hidden)node.hidden=true});
 $g('growthTalk').addEventListener('click',()=>{
  const s=calculate(),lines=['ユウ、今日も会いに来てくれたんだね💕','いまLv.'+s.level+'！これまでの努力が形になってるよ✨','間違えた問題こそ伸びしろ！一緒に復習しよっ','累計'+s.answered+'問！少しずつでも強くなってるね'];
  $g('growthSpeech').textContent=lines[talk++%lines.length];
 });
 $g('growthPractice').addEventListener('click',()=>{node.hidden=true;const b=document.querySelector('.tab[data-tab="study"]');if(b)b.click()});
 $g('growthScenes').addEventListener('click',e=>{
  const b=e.target.closest('button[data-scene]');if(!b||b.disabled)return;
  selected=b.dataset.scene;try{localStorage.setItem(storageKey,selected)}catch(e){}
  updateModal();$g('growthSpeech').textContent='背景を変えたよ！気分一新、勉強しよっ✨';
 });
}
function updateModal(){
 const s=calculate();
 if(!scenes.some(r=>r[0]===selected&&s.level>=r[1]))selected='base';
 $g('growthStage').dataset.scene=selected;
 $g('growthSummary').innerHTML=summary(s)+'<p class="tiny">回答'+s.answered+'問 ／ 正解'+s.correct+'問<br>復習成功'+s.recoveries+'回 ／ 満点'+s.perfect+'回</p>';
 $g('growthScenes').innerHTML=scenes.map(r=>'<button type="button" data-scene="'+r[0]+'" aria-pressed="'+(selected===r[0])+'" '+(s.level<r[1]?'disabled':'')+'>'+r[2]+'<br><small>'+(s.level>=r[1]?'解放済み':'Lv.'+r[1]+'で解放')+'</small></button>').join('');
 $g('growthRewards').innerHTML=rewards.map(r=>'<div class="growth-unlock '+(s.level<r[0]?'locked':'')+'"><span>Lv.'+r[0]+' '+r[1]+'</span><strong>'+r[2]+' '+(s.level>=r[0]?'✓':'🔒')+'</strong><small>'+r[3]+'</small></div>').join('');
}
function open(){ensureModal();updateModal();$g('growthModal').hidden=false}
function render(){
 const main=document.querySelector('#screen-home .home-main');if(!main)return;
 ensureModal();let card=$g('growthHomeCard');
 if(!card){card=document.createElement('section');card.className='card dash-card growth-card';card.id='growthHomeCard';main.insertBefore(card,main.querySelector('.home-split')||main.firstChild)}
 const s=calculate();
 card.innerHTML='<h2>💕 アイ先生の育成</h2><div style="display:flex;gap:12px;align-items:center"><img src="./ai-teacher-avatar.webp" alt="アイ先生" width="76" height="76" style="border-radius:50%;border:2px solid #f4ade5;object-fit:cover">'+summary(s)+'</div><button class="btn secondary" type="button" id="growthOpen" style="width:100%;margin-top:12px">アイ先生に会う・ルームを育てる →</button>';
 $g('growthOpen').addEventListener('click',open);if(!$g('growthModal').hidden)updateModal();
}
window.aiGrowthRender=render;
render();
})();
</script>
"""

def install_trophy_ui(study:Path)->bool:
    """Install/upgrade trophy UI while preserving study questions and local answers."""
    study=Path(study)
    path=study/'index.html'
    sw=study/'sw.js'
    original=path.read_text(encoding='utf-8')
    if original.count('</body>')!=1:
        raise ValueError('AI Study document structure unexpected')
    if MARKER in original:
        old=re.compile(re.escape(MARKER)+r'\s*<style id="ai-study-trophy-style">.*?</style>\s*<script id="ai-study-trophy-script">.*?</script>\s*(?:<!-- AI_STUDY_GROWTH_V1 -->\s*<style id="ai-study-growth-style">.*?</style>\s*<script id="ai-study-growth-script">.*?</script>\s*)?(?=</body>)',re.S)
        if len(old.findall(original))!=1 or original.count(MARKER)!=1:
            raise ValueError('Unknown trophy HTML markup; patch refused safely')
        updated=old.sub(lambda _:MARKER+'\n'+TROPHY_UI,original,count=1)
    else:
        if original.count(SAVE_ORIGINAL)!=1 or original.count(RENDER_ORIGINAL)!=1:
            raise ValueError('Unknown AI Study version; trophy patch refused safely')
        updated=original.replace(SAVE_ORIGINAL,SAVE_PATCHED)
        updated=updated.replace(RENDER_ORIGINAL,RENDER_PATCHED)
        updated=updated.replace('</body>',MARKER+'\n'+TROPHY_UI+'</body>')
    if updated==original:
        return False
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


# This is deliberately independent from the verified PC/mobile study bank.
# A private, self-contained practice page may show AI-reviewed draft candidates
# without claiming their answers are fact-checked or updating learning scores.
PREVIEW_HTML=r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>AI Study 未検証候補 練習室</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{font:16px/1.7 system-ui,-apple-system,sans-serif;background:#101726;color:#f0f3fa;margin:0;padding:24px}
main{max-width:820px;margin:0 auto}.head{background:#26324a;border:1px solid #4b5a76;padding:22px;border-radius:16px}
h1{font-size:1.5rem;margin:0 0 8px}.warning{color:#ffe1a1;font-weight:700}
#quiz{margin-top:20px;padding:25px;background:#1b2638;border-radius:16px;border:1px solid #45516d}
#question{white-space:pre-line;font-size:1.13rem;font-weight:650;margin:18px 0}
.choice{display:block;width:100%;text-align:left;background:#2a3852;color:#f4f6fb;border:1px solid #5a6b86;border-radius:12px;padding:14px;margin:10px 0;cursor:pointer;font:inherit}
.choice:focus-visible,button:focus-visible{outline:3px solid #ffd47d}.choice.selected{border:2px solid #ffc267;background:#38435c}
button:disabled{opacity:.55;cursor:not-allowed}.bar{display:flex;gap:12px;flex-wrap:wrap;margin-top:22px}
.action{background:#ffe0a3;color:#161e2d;border:0;padding:12px 20px;border-radius:10px;font:inherit;font-weight:700;cursor:pointer}
.action.secondary{background:#3d4e69;color:#fff}.result{margin-top:20px;border-top:1px solid #65738b;padding-top:14px}
#feedbackBox{margin-top:18px}#feedbackBox select,#feedbackBox textarea{display:block;width:100%;margin:8px 0 14px;padding:10px;background:#152238;color:#fff;border:1px solid #6b7892;border-radius:8px;font:inherit}
#feedbackBox textarea{min-height:76px}#feedbackBox .action{margin:5px 8px 5px 0}#stats{white-space:pre-line}
#explanation{white-space:pre-line}.subtle{color:#c1cbdb;font-size:.9rem}
</style></head><body><main><div class="head"><h1>🎓 AI Study：未検証候補の練習室</h1>
<p class="warning">⚠ AIレビュー済み・AWS公式資料未照合。正答・解説に誤りが含まれる可能性があります。</p>
<p>ここは正式問題集とは別のローカル練習画面です。成績・トロフィー・元問題集を変更せず、ネットにも送信しません。</p>
<p id="count" class="subtle"></p><p id="stats" class="subtle" aria-live="polite"></p><p id="storageStatus" class="subtle"></p><button id="exportFeedback" class="action secondary" type="button">練習履歴・報告をJSON保存</button> <label class="subtle">保存済みJSONを読み込む <input id="importFeedback" type="file" accept="application/json,.json"></label></div>
<section id="quiz"><div id="progress" class="subtle"></div><div id="question"></div>
<div id="choices"></div><div class="bar">
<button id="grade" class="action">解答・解説を表示</button><button id="next" class="action secondary">次の問題 →</button></div>
<div id="result" class="result" hidden><div id="correct"></div><p id="explanation"></p>
<p class="warning">この解説は未検証です。疑問があればAWS公式資料で確認してください。</p></div></section>
<section id="feedbackBox" class="head"><h2>未検証問題の品質報告</h2><p class="subtle">報告はこのページ内の一時記録です。AWS公式検証・自動採用には使用されません。閉じる前にJSON保存し、次回は読み込んでください。</p><label>回答の自信度 <select id="confidence"><option value="1">自信なし</option><option value="2" selected>普通</option><option value="3">確信あり</option></select></label><label>問題の指摘 <select id="reportReason"><option value="正答が疑わしい">正答が疑わしい</option><option value="解説が不正確">解説が不正確</option><option value="重複問題">重複問題</option><option value="その他">その他</option></select></label><label>補足（任意、500文字まで）<textarea id="reportNote" maxlength="500" placeholder="例：このAWSサービスには記載の機能がない"></textarea></label><button id="reportIssue" type="button" class="action secondary">この問題を報告として保存</button><p id="reportStatus" class="subtle" aria-live="polite"></p></section>
</main><script>
const questions=__PAYLOAD__;
let index=0;
const selected=new Set();
const el=id=>document.getElementById(id);

const REASONS=['正答が疑わしい','解説が不正確','重複問題','その他'];
const DOMAINS=['D1','D2','D3','D4'];
function blankProgress(){return {schema:1,attempts:Object.create(null),reports:Object.create(null)};}
function normalizeProgress(value){
  if(!value||typeof value!=='object'||value.schema!==1||Array.isArray(value))throw Error('対応していない履歴形式');
  const clean=blankProgress();
  const attempts=value.attempts||{},reports=value.reports||{};
  if(typeof attempts!=='object'||Array.isArray(attempts)||typeof reports!=='object'||Array.isArray(reports))throw Error('履歴形式が不正');
  if(Object.keys(attempts).length>5000||Object.keys(reports).length>5000)throw Error('履歴件数が上限超過');
  for(const [id,a] of Object.entries(attempts)){
    if(!/^SAA-AUTO-\d{5,}$/.test(id)||!a||!DOMAINS.includes(a.domain))continue;
    if(!Number.isSafeInteger(a.tries)||a.tries<1||a.tries>100000||
       !Number.isSafeInteger(a.repeatCorrect)||a.repeatCorrect<0||a.repeatCorrect>=a.tries)continue;
    clean.attempts[id]={domain:a.domain,tries:a.tries,firstCorrect:a.firstCorrect===true,
      lastCorrect:a.lastCorrect===true,repeatCorrect:a.repeatCorrect,
      confidence:[1,2,3].includes(a.confidence)?a.confidence:2};
  }
  for(const [id,r] of Object.entries(reports)){
    if(!/^SAA-AUTO-\d{5,}$/.test(id)||!r||!DOMAINS.includes(r.domain)||!REASONS.includes(r.reason))continue;
    clean.reports[id]={domain:r.domain,reason:r.reason,note:typeof r.note==='string'?r.note.slice(0,500):'',
      reportedAt:typeof r.reportedAt==='string'?r.reportedAt.slice(0,32):''};
  }
  return clean;
}
function loadProgress(){return blankProgress();}
let practiceProgress=loadProgress();
function persistProgress(){
  el('storageStatus').textContent='履歴はこのページ内だけの一時記録です。閉じる前にJSON保存してください。';
  return false;
}
function summarizeProgress(data){
  const byDomain=Object.fromEntries(DOMAINS.map(d=>[d,{first:0,firstCorrect:0,repeats:0,repeatCorrect:0}]));
  for(const a of Object.values(data.attempts)){
    const d=byDomain[a.domain];if(!d)continue;
    d.first++;if(a.firstCorrect)d.firstCorrect++;
    d.repeats+=a.tries-1;d.repeatCorrect+=a.repeatCorrect;
  }
  return byDomain;
}
function renderStats(){
  const stats=summarizeProgress(practiceProgress);
  el('stats').textContent='未検証練習の記録（公式成績・トロフィーとは別）\n'+
    DOMAINS.map(d=>{const x=stats[d];return d+' 初見 '+x.firstCorrect+'/'+x.first+
      '・再挑戦 '+x.repeatCorrect+'/'+x.repeats;}).join(' | ')+
    '\n品質報告 '+Object.keys(practiceProgress.reports).length+'件';
}
function recordAttempt(q,correct){
  let a=practiceProgress.attempts[q.id];
  const confidence=Number(el('confidence').value);
  if(a){a.tries++;a.lastCorrect=correct;if(correct)a.repeatCorrect++;}
  else{a={domain:q.domain,tries:1,firstCorrect:correct,lastCorrect:correct,repeatCorrect:0};
    practiceProgress.attempts[q.id]=a;}
  a.confidence=[1,2,3].includes(confidence)?confidence:2;
  persistProgress();renderStats();
}
el('count').textContent=questions.length+'問のAI品質保留候補（この画面の問題は正式採用数に含まれません）。';
function show(){
  const q=questions[index];selected.clear();
  el('progress').textContent=(index+1)+' / '+questions.length+'問 • '+q.id+' • '+q.domain+' • '+(q.type==='multiple'?'2つ選択':'1つ選択');
  el('question').textContent=q.question;
  el('choices').replaceChildren();
  Object.entries(q.choices).forEach(([letter,value])=>{
    const b=document.createElement('button');b.className='choice';b.type='button';
    b.textContent=letter+'. '+value;
    b.onclick=()=>{
      if(selected.has(letter))selected.delete(letter);
      else if(q.type==='single'){selected.clear();selected.add(letter);}
      else if(selected.size<2)selected.add(letter);
      [...el('choices').children].forEach((child,i)=>child.classList.toggle('selected',selected.has(Object.keys(q.choices)[i])));
    };
    el('choices').append(b);
  });
  el('result').hidden=true;
  el('next').disabled=index===questions.length-1;
  el('grade').disabled=false;
  el('reportStatus').textContent=practiceProgress.reports[q.id]?'この問題には保存済みの報告があります。':'';
  el('reportNote').value=practiceProgress.reports[q.id]?.note||'';
}
el('grade').onclick=()=>{
  const q=questions[index];
  if(selected.size!==q.correct.length){el('reportStatus').textContent='必要な選択肢を選んでから採点してください。';return;}
  const picked=[...selected].sort().join(',');
  const correct=q.correct.slice().sort().join(',');
  recordAttempt(q,picked===correct);
  el('grade').disabled=true;
  [...el('choices').children].forEach(b=>b.disabled=true);
  el('correct').textContent='あなたの回答: '+picked+' / AI暫定正解: '+correct+(picked===correct?' （一致）':' （不一致）');
  el('explanation').textContent=q.explanation;
  el('result').hidden=false;
};
el('next').onclick=()=>{if(index<questions.length-1){index++;show();}};
el('reportIssue').onclick=()=>{
  const q=questions[index],reason=el('reportReason').value;
  if(!REASONS.includes(reason))return;
  practiceProgress.reports[q.id]={domain:q.domain,reason,note:el('reportNote').value.trim().slice(0,500),
    reportedAt:new Date().toISOString()};
  const saved=persistProgress();renderStats();
  el('reportStatus').textContent=saved?'問題ID '+q.id+' の報告を保存しました。':'一時記録しました。JSONを保存して残してください。';
};
el('exportFeedback').onclick=()=>{
  const blob=new Blob([JSON.stringify(practiceProgress,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='AI_Study_未検証練習履歴.json';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
el('importFeedback').onchange=async event=>{
  const file=event.target.files?.[0];if(!file)return;
  try{
    if(file.size>1024*1024)throw Error('ファイルが大きすぎます');
    const imported=normalizeProgress(JSON.parse(await file.text()));
    if(!confirm('現在の未検証練習記録を、読み込んだJSONで置き換えますか？'))return;
    practiceProgress=imported;persistProgress();renderStats();show();
    el('reportStatus').textContent='履歴を読み込みました。';
  }catch(error){el('reportStatus').textContent='読み込み失敗: '+String(error.message).slice(0,100);}
  finally{event.target.value='';}
};
renderStats();
el('storageStatus').textContent='ブラウザー内には保存しません。閉じる前にJSON保存してください。';
show();
</script></body></html>'''


def preview_candidates(state):
    """Only Gemini-PASS quality-held candidates. No revision/rejects or secrets."""
    generated=state.get('generated') or {}
    trials=state.get('revision_trials') or {}
    if not isinstance(generated,dict) or not isinstance(trials,dict):
        raise ValueError('候補データの形式が不正')
    ready=[]
    for uid,record in sorted(generated.items()):
        if (not isinstance(uid,str) or not uid.startswith('SAA-AUTO-')
            or not isinstance(record,dict) or record.get('status')!='QUALITY_HOLD'
            or uid in trials):
            continue
        q=record.get('candidate')
        if not isinstance(q,dict) or q.get('id')!=uid or q.get('exam')!='SAA-C03':
            continue
        audit=record.get('audit') or []
        reviews=[x.get('review') for x in audit
                 if isinstance(x,dict) and isinstance(x.get('review'),dict)]
        if not reviews or reviews[-1].get('verdict')!='PASS':
            continue
        typ=q.get('type')
        if typ not in ('single','multiple'):
            continue
        letters='ABCDE' if typ=='multiple' else 'ABCD'
        choices=q.get('choices')
        if isinstance(choices,list) and len(choices)==len(letters):
            choices=dict(zip(letters,choices))
        if not isinstance(choices,dict) or set(choices)!=set(letters):
            continue
        correct=q.get('correct')
        if (not isinstance(correct,list) or len(correct)!=(2 if typ=='multiple' else 1)
            or len(set(correct))!=len(correct) or not set(correct)<=set(letters)):
            continue
        if (not isinstance(q.get('question'),str) or len(q['question'])<40
            or not isinstance(q.get('explanation'),str) or len(q['explanation'])<75
            or any(not isinstance(x,str) or not x.strip() for x in choices.values())):
            continue
        ready.append({key:q[key] for key in ('id','domain','type','question','explanation','correct')})
        ready[-1]['choices']={k:choices[k] for k in letters}
    return ready


def preview_practice(root=None, *, open_page=False):
    """Generate a private, zero-cost offline quiz view; never touch the PWA."""
    root=Path(root) if root is not None else Path(__file__).resolve().parent
    statepath=root/'work'/'state.json'
    if not statepath.is_file():
        print('[PREVIEW] 状態ファイルがありません。変更なし。')
        return {'status':'NO_STATE','count':0}
    state=json.loads(statepath.read_text(encoding='utf-8-sig'))
    candidates=preview_candidates(state)
    if not candidates:
        print('[PREVIEW] 対象のQUALITY_HOLD候補はありません。変更なし。')
        return {'status':'NO_CANDIDATES','count':0}
    # Escape closing SCRIPT tags and HTML syntax in untrusted model text.
    payload=json.dumps(candidates,ensure_ascii=False,separators=(',',':'))
    payload=payload.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    payload=payload.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    page=PREVIEW_HTML.replace('__PAYLOAD__',payload)
    dest=root/'work'/'outputs'/'AI_Study_未検証練習室.html'
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.tmp')
    tmp.write_text(page,encoding='utf-8')
    tmp.replace(dest)
    print('[PREVIEW] 練習用',len(candidates),'問を作成:',dest)
    print('[PREVIEW] 公式未検証・正式問題集には未追加。API利用なし。')
    if open_page:
        import webbrowser
        webbrowser.open(dest.resolve().as_uri())
    return {'status':'CREATED','count':len(candidates),'path':str(dest)}


def prepare_daily_practice(root=None, *, open_page=False, today=None, max_questions=20):
    """Deliver previously unseen AI-PASS/QUALITY_HOLD candidates, privately.

    Never modifies the main PC/mobile question bank, study history, source data,
    paid API counters, or provider keys. Delivery ledger is only a list of IDs.
    """
    root=Path(root) if root is not None else Path(__file__).resolve().parent
    if (root/'work'/'supply_campaign.json').exists():
        return prepare_supply_practice(root,open_page=open_page,today=today)
    day=today or datetime.datetime.now().astimezone().date().isoformat()
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',day):
        raise ValueError('不正な日付')
    if type(max_questions) is not int or not 1<=max_questions<=100:
        raise ValueError('日次出題数が不正')
    work=root/'work';out=work/'outputs'
    statefile=work/'state.json'
    if not statefile.exists():
        print('[DAILY] 生成状態なし。新問はまだありません。')
        return {'status':'NO_STATE','new_questions':0}
    state=json.loads(statefile.read_text(encoding='utf-8-sig'))
    candidates=preview_candidates(state)
    ledger_path=work/'practice_delivery.json'
    ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else {}
    if not isinstance(ledger,dict) or not isinstance(ledger.get('delivered_ids',[]),list):
        raise ValueError('練習配信台帳が不正')
    delivered=ledger.get('delivered_ids',[])
    if len(delivered)!=len(set(delivered)) or any(
            not isinstance(uid,str) for uid in delivered):
        raise ValueError('練習配信IDが不正')
    existing_page=out/'AI_Study_本日の新問.html'
    # Idempotent same-day generation: retain the exact morning set even if the
    # watchdog restarts or gets another hourly tick.
    if ledger.get('date')==day and existing_page.exists():
        result={'status':'ALREADY_READY','date':day,
                'new_questions':int(ledger.get('new_questions',0)),
                'available_candidates':len(candidates),
                'path':str(existing_page)}
        if open_page:
            import webbrowser
            webbrowser.open(existing_page.resolve().as_uri())
        return result
    unseen=[q for q in candidates if q['id'] not in set(delivered)]
    selected=unseen[:max_questions]
    out.mkdir(parents=True,exist_ok=True)
    if selected:
        payload=json.dumps(selected,ensure_ascii=False,separators=(',',':'))
        # HTML script-data escape: never execute provider-authored markup.
        payload=payload.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        payload=payload.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        page=PREVIEW_HTML.replace('__PAYLOAD__',payload)
        page=page.replace('AI Study：未検証候補の練習室',
                          'AI Study：'+day+' 新問（公式未検証）')
        page=page.replace('AI品質保留候補（この画面の問題は正式採用数に含まれません）',
                          '本日の新問（この画面の問題は正式採用数に含まれません）')
    else:
        page=('<!doctype html><html lang="ja"><meta charset="utf-8">'
              '<title>AI Study 日次新問 0問</title><body>'
              '<h1>新規問題は0問です</h1><p>日付：'+day+'</p>'
              '<p>AIレビューを通過した未配信の候補がありません。'
              '自動生成が停止していないか、API利用上限・PC稼働状況を確認してください。'
              '既存の正式問題集は変更されていません。</p></body></html>')
    tmp=existing_page.with_suffix('.html.tmp')
    tmp.write_text(page,encoding='utf-8')
    tmp.replace(existing_page)
    report={'status':'READY' if selected else 'NO_NEW',
            'date':day,'new_questions':len(selected),
            'available_candidates':len(candidates),
            'held_unseen_remaining':len(unseen)-len(selected),
            'path':str(existing_page),
            'notice':'Geminiレビューのみ。AWS公式未照合。正答は暫定。'}
    ledger={'date':day,'new_questions':len(selected),
            'delivered_ids':delivered+[q['id'] for q in selected]}
    save_json(ledger_path,ledger)
    save_json(out/'daily_practice_status.json',report)
    print('[DAILY]',day,'本日の新問:',len(selected),
          '/ 今回配信できる未検証候補:',len(candidates))
    print('[DAILY] 問題表示:',existing_page,'/ API 0回 / 正式問題集は変更なし')
    if open_page:
        import webbrowser
        webbrowser.open(existing_page.resolve().as_uri())
    return report


def supply_quality_error(q):
    """Conservative local guard; this is not independent AWS fact checking."""
    if q.get('domain') not in ('D1','D2','D3','D4'):
        return 'invalid domain'
    if q.get('type')=='multiple' and not re.search(r'2\s*つ|２つ|二つ',q.get('question','')):
        return 'missing selection count'
    explanation=q.get('explanation','')
    for letter in q.get('choices',{}):
        if not re.search(r'(?:【|\b|^|\n)'+letter+r'(?:】|[.:：、）)])\s*\S.{8,}',explanation):
            return 'missing choice explanation: '+letter
    # Known false-PASS family: reject for independent review, including negations.
    text=json.dumps(q,ensure_ascii=False).lower()
    if 'sqs' in text and re.search(r'cross.region.{0,30}(clone|replicat)|クロスリージョン.{0,30}(クローン|複製)|fifo.{0,25}(スケールできない|拡張できない)',text):
        return 'SQS/FIFO claim requires independent verification'
    return ''


def supply_fingerprint(q):
    """Ignore IDs, labels and answer ordering; compare the architecture decision."""
    norm=lambda s:re.sub(r'[\W_]+','',str(s).lower())
    choices=q.get('choices',{})
    if isinstance(choices,list):choices=dict(zip('ABCDE',choices))
    return norm(q.get('question',''))+'|'+ '|'.join(sorted(norm(choices.get(k,'')) for k in q.get('correct',[])))


@functools.lru_cache(maxsize=2048)
def _supply_shingles(text):
    return frozenset(text[i:i+3] for i in range(len(text)-2))


def supply_similar(left,right):
    """Cheap character-shingle overlap screen before the text similarity check.

    A conservative heuristic, not a proof of semantic uniqueness. Gemini must
    still review scenario novelty; official verification remains separate.
    """
    import difflib
    if left==right:return True
    a=_supply_shingles(left)
    b=_supply_shingles(right)
    if not a or not b or len(a & b)/min(len(a),len(b))<.65:return False
    return difflib.SequenceMatcher(None,left,right,autojunk=False).ratio()>=.88


def prepare_supply_practice(root, *, open_page=False, today=None):
    """Serialize practice-today and watchdog deliveries across Windows processes."""
    import os
    path=Path(root)/'work'/'supply_delivery.lock'
    with path.open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:return _prepare_supply_practice(root,open_page=open_page,today=today)
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def _prepare_supply_practice(root, *, open_page=False, today=None):
    """Journal first, render second: a crash replays the same deck, never re-counts.

    The private ledger is the source of truth. It contains replayable daily decks
    and immutable delivery receipts. Existing state and the verified PWA are read-only.
    """
    import difflib
    root=Path(root);work=root/'work';out=work/'outputs'
    day=today or datetime.datetime.now().astimezone().date().isoformat()
    datetime.date.fromisoformat(day)
    config=json.loads((work/'supply_campaign.json').read_text(encoding='utf-8'))
    target=config.get('target');daily=config.get('daily_delivery_target')
    if type(target) is not int or not 1<=target<=500 or type(daily) is not int or not 1<=daily<=100:
        raise ValueError('Invalid supply targets')
    state=json.loads((work/'state.json').read_text(encoding='utf-8-sig'))
    path=work/'supply_delivery.json'
    if path.exists():
        ledger=json.loads(path.read_text(encoding='utf-8'))
        if ledger.get('schema')!=1 or not isinstance(ledger.get('receipts'),dict) or not isinstance(ledger.get('days'),dict):
            raise ValueError('Invalid supply delivery journal; refusing reset')
    else:
        oldpath=work/'practice_delivery.json'
        old=json.loads(oldpath.read_text(encoding='utf-8')) if oldpath.exists() else {}
        baseline=set(old.get('delivered_ids',[]))
        # Previously generated records do not become a fake new campaign increment.
        baseline.update((state.get('generated') or {}).keys())
        baseline.update((state.get('existing') or {}).keys())
        baseline.update((state.get('pending') or {}).keys())
        ledger={'schema':1,'baseline_ids':sorted(baseline),'receipts':{},'days':{}}
    baseline=set(ledger['baseline_ids']);receipts=ledger['receipts']
    candidates={q['id']:q for q in preview_candidates(state) if not supply_quality_error(q)}
    active_ids=set(receipts)&set(candidates)
    selected=[q for q in ledger['days'].get(day,[]) if q['id'] in candidates]
    selected_ids={q['id'] for q in selected}
    fingerprints=[r['fingerprint'] for r in receipts.values()]
    # Compare against baseline, pending and every revision history as well.
    def collect(obj):
        if isinstance(obj,dict):
            if 'question' in obj and 'choices' in obj:yield obj
            else:
                for v in obj.values():yield from collect(v)
        elif isinstance(obj,list):
            for v in obj:yield from collect(v)
    corpus=[(q.get('id'),supply_fingerprint(q)) for q in collect(state)]
    rejected=[]
    for uid,q in candidates.items():
        if len(selected)>=daily or len(active_ids)>=target:break
        if uid in baseline or uid in receipts or uid in selected_ids:continue
        fp=supply_fingerprint(q)
        comparison=set(fingerprints+[fp for old_id,fp in corpus if old_id!=uid])
        if any(supply_similar(fp,old) for old in comparison):
            rejected.append(uid);continue
        selected.append(q);selected_ids.add(uid);fingerprints.append(fp)
        receipts[uid]={'date':day,'domain':q['domain'],'fingerprint':fp}
        active_ids.add(uid)
    changed=ledger['days'].get(day)!=selected
    ledger['days'][day]=selected
    out.mkdir(parents=True,exist_ok=True)
    save_json(path,ledger)  # Write-ahead receipt/deck, including the one-time baseline.
    runtime_path=out/'supply_run.json'
    run=json.loads(runtime_path.read_text(encoding='utf-8')) if runtime_path.exists() else {}
    reason=run.get('reason','未配信の品質審査済み候補が不足。PC稼働・設定・予算を確認してください。')
    report={'status':'READY' if selected else 'NO_NEW','date':day,'new_questions':len(selected),
            'delivered_total':len(active_ids),'historical_deliveries':len(receipts),
            'target':target,'remaining':max(0,target-len(active_ids)),
            'daily_target':daily,'shortfall':max(0,daily-len(selected)),
            'provisional_count':len(candidates),'independently_verified':0,
            'verified_notice':'この配信は全件未検証。正式問題集の検証済み件数とは別。',
            'duplicate_rejections':rejected,'reason':reason,
            'path':str(out/'AI_Study_本日の新問.html')}
    summary=('新規出題可能: 今日 '+str(len(selected))+'件 / 累計 '+str(len(active_ids))+'/'+str(target)+'件。'
             +' 未検証 '+str(len(selected))+'件 / この配信の検証済み 0件。目標不足 '+str(report['shortfall'])+'件。 '+reason)
    if selected:
        payload=json.dumps(selected,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        payload=payload.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        page=PREVIEW_HTML.replace('__PAYLOAD__',payload).replace('<p id="count"', '<p>'+html.escape(summary)+'</p><p id="count"')
    else:
        page='<meta charset="utf-8"><h1>新規問題は0問です</h1><p>'+html.escape(summary)+'</p>'
    dest=Path(report['path']);tmp=dest.with_suffix('.html.tmp')
    tmp.write_text(page,encoding='utf-8');tmp.replace(dest)
    save_json(out/'daily_practice_status.json',report)
    if open_page:
        import webbrowser
        webbrowser.open(dest.resolve().as_uri())
    return dict(report,status=('ALREADY_READY' if selected and not changed else report['status']))


if __name__=='__main__':
    cmd=sys.argv[1:] if len(sys.argv)>1 else []
    try:
        if cmd==['practice-today']:prepare_daily_practice(open_page=True)
        elif cmd==['practice-preview']:preview_practice(open_page=True)
        elif cmd==['setup-mobile']:setup_mobile_sync()
        elif cmd==['deploy-mobile']:publish_mobile(force=True)
        elif cmd==['status-mobile']:
            _,_,out=mobile_paths()
            p=out/'mobile_publish_status.json'
            print(p.read_text(encoding='utf-8') if p.exists() else 'No mobile deployment yet')
        else:print('Usage: py -3 live_progress.py practice-today|practice-preview|setup-mobile|deploy-mobile|status-mobile')
    except Exception as exc:
        print('[MOBILE] ERROR:',str(exc)[:210])
        sys.exit(1)


