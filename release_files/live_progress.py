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
        sync_study_pack(out)


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
