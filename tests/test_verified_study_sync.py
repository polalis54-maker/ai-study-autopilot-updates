"""Regression: Gemini PASS is not permission to publish AI-generated content."""
import importlib.util
import copy
import json
import tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('lp','release_files/live_progress.py')
lp=importlib.util.module_from_spec(spec);spec.loader.exec_module(lp)
def question(id):
    return {'id':id,'exam':'SAA-C03','type':'single','domain':'D2','topic':'RTO/RPO',
            'difficulty':'中級',
            'question':'あるAWSアプリのRTOを短縮しつつ、データ復旧要件を満たしたい場合の設計を選んでください。',
            'choices':{'A':'Multi-AZ','B':'Read Replica','C':'S3 bucket','D':'SQS'},
            'correct':['A'],
            'explanation':'Multi-AZ は自動フェイルオーバーに対応し、復旧時間を短縮できます。リードレプリカは読み取り性能向上が中心で、障害対応時に手動昇格が必要な場合があります。',
            'source':{'kind':'original','label':'AI only'},
            'review_status':'ai_reviewed_unverified'}
def approval(q):
    return {'human_approved':True,'official_documentation_verified':True,
            'documentation_url':'https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html',
            'question_sha256':lp.review_payload_digest(q)}
def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    study=root/'AI_Study';out=root/'work'/'outputs'
    study.mkdir();out.mkdir(parents=True)
    base={'questions':[{'id':'Q-BASE','question':'existing question'}]}
    incoming={'questions':[question('SAA-AUTO-00020'),question('SAA-AUTO-00024')]}
    write(study/'questions.json',base)
    (study/'index.html').write_text('<script id="default-pack" type="application/json">'+json.dumps(base)+'</script>',encoding='utf8')
    (study/'sw.js').write_text("const CACHE='ai-study-v1';",encoding='utf8')
    write(out/'AI_Study_追加候補.json',incoming)
    originals={p:p.read_bytes() for p in [study/'questions.json',study/'index.html',study/'sw.js']}
    result=lp.sync_study_pack(out)
    assert result['status']=='BLOCKED_UNVERIFIED',result
    assert result['unverified_skipped']==2
    assert all(p.read_bytes()==blob for p,blob in originals.items())
    assert not (out/'AI_Study_公開用.zip').exists()
    # A completed background run must never auto-deploy when all candidates are held.
    lp.publish_mobile=lambda *args,**kwargs: (_ for _ in ()).throw(
        AssertionError('unverified content must never auto-publish to Netlify'))
    lp.update(out,status='COMPLETE',phase='tested locally')
    assert json.loads((out/'study_sync_status.json').read_text(encoding='utf8'))['status']=='BLOCKED_UNVERIFIED'
    approval_file=root/'work'/'content_approvals.json'
    # Tampered/AI-only approvals or invalid evidence are still rejected.
    for case in (
        {'human_approved':False,'official_documentation_verified':True},
        {'human_approved':True,'official_documentation_verified':False},
        {'human_approved':True,'official_documentation_verified':True,
         'documentation_url':'https://example.com/fake','question_sha256':lp.review_payload_digest(incoming['questions'][0])},
        {**approval(incoming['questions'][0]),'documentation_url':'https://docs.aws.amazon.com.evil.org/ref'},
        {**approval(incoming['questions'][0]),'documentation_url':'http://docs.aws.amazon.com/ref'},
        {**approval(incoming['questions'][0]),'question_sha256':'0'*64},
    ):
        write(approval_file,{'approvals':{'SAA-AUTO-00020':case}})
        assert lp.sync_study_pack(out)['status']=='BLOCKED_UNVERIFIED'
        assert all(p.read_bytes()==blob for p,blob in originals.items())
    write(approval_file,{'approvals':{'SAA-AUTO-00020':approval(incoming['questions'][0])}})
    result=lp.sync_study_pack(out)
    assert result['status']=='SYNCED',result
    assert result['newly_added']==1 and result['unverified_skipped']==1,result
    current=json.loads((study/'questions.json').read_text(encoding='utf8'))['questions']
    assert [q['id'] for q in current]==['Q-BASE','SAA-AUTO-00020']
    assert current[1]['correct']==['A']
    assert 'SAA-AUTO-00024' not in (study/'index.html').read_text(encoding='utf8')
    import zipfile
    with zipfile.ZipFile(out/'AI_Study_公開用.zip') as z:
        assert 'work/content_approvals.json' not in z.namelist()
        assert 'content_approvals.json' not in z.namelist()
        assert len(json.loads(z.read('questions.json'))['questions'])==2
    result=lp.sync_study_pack(out)
    assert result['status']=='BLOCKED_UNVERIFIED'
    assert result['newly_added']==0 and result['unverified_skipped']==1
    # Exact-content binding refuses approval after content changes.
    incoming['questions'][1]['explanation']+=' CHANGED'
    write(out/'AI_Study_追加候補.json',incoming)
    write(approval_file,{'approvals':{'SAA-AUTO-00024':approval(question('SAA-AUTO-00024'))}})
    result=lp.sync_study_pack(out)
    assert result['status']=='BLOCKED_UNVERIFIED',result
print('PASS independent human + AWS evidence approval, digest binding, no leaked files')
