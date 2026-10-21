"""Offline human-attested revision approval and safe PC sync (never Netlify)."""
import ast
import copy
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path('release_files').resolve()))
import live_progress as lp
src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'reviewed_revision_for_staging','revision_approve'}
funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
assert len(funcs)==len(wanted)
qid='SAA-AUTO-00020'
doc_url='https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html'
q={'id':qid,'exam':'SAA-C03','domain':'D2','topic':'Multi-AZ','type':'single',
   'difficulty':'中級',
   'question':'企業はAWSのRDSを利用しています。障害時に迅速な回復が必要です。運用負担を少なくして自動フェイルオーバーする構成は何ですか？',
   'choices':['Multi AZ','Read Replica','EBS','SQS'],'correct':['A'],
   'explanation':'Multi-AZ構成はスタンバイを持ち、高可用性のため自動フェイルオーバーが利用できます。'
                 'Read Replicaは主に読み取り性能の改善が目的であり自動フェイルオーバーとは別物です。'
                 'EBSはブロックストレージ、SQSはメッセージキューのため、この要件に一致しません。',
   'source':{'kind':'original','label':'generator'},'language':'ja'}
class A:
    STATEFILE='local_state_never_mutate'
    state={'generated':{qid:{'status':'REVISE_UNRESOLVED',
           'candidate':copy.deepcopy(q)}},
           'revision_trials':{qid:{'status':'REVIEWED_HOLD',
             'original_status':'REVISE_UNRESOLVED','candidate':copy.deepcopy(q),
             'review':{'verdict':'PASS','issues':[]}}}}
    @classmethod
    def jread(cls,p,default=None):
        if str(p)==cls.STATEFILE:
            return cls.state
        return json.loads(Path(p).read_text(encoding='utf8')) if Path(p).exists() else default
    @classmethod
    def jwrite(cls,p,data):
        dest=Path(p);dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        tmp.replace(dest)
    @staticmethod
    def state_default():return {}
    @staticmethod
    def validate(q,strict=False):assert strict and q['id']==qid
    @staticmethod
    def meets_exam_quality(r):return True
    @staticmethod
    def today():return '2026-10-21'
class Lock:
    busy=False
    got=0
    released=0
    @classmethod
    def windows_lock(cls,*a):
        if cls.busy:return None
        cls.got+=1;return object()
    @classmethod
    def release_lock(cls,*a):cls.released+=1
class Stop:
    stopped=True
    @classmethod
    def exists(cls):return cls.stopped
def no_netlify(*a,**k):raise AssertionError('Netlify must not auto-publish')
lp.publish_mobile=no_netlify
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    out=root/'work'/'outputs';out.mkdir(parents=True)
    study=root/'AI_Study';study.mkdir()
    baseline={'questions':[{'id':'original','question':'keep me'}]}
    (study/'questions.json').write_text(json.dumps(baseline),encoding='utf8')
    (study/'index.html').write_text('<script id="default-pack" type="application/json">'+json.dumps(baseline)+'</script>',encoding='utf8')
    (study/'sw.js').write_text("const CACHE='ai-study-vold';",encoding='utf8')
    ns={'a':A,'ua':Lock,'STOP':Stop,'LOCK':root/'autopilot.lock',
        'ROOT':root,'re':re,'question_is_near_duplicate':lambda *a:False,
        'input':lambda prompt:qid}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'<approval>', 'exec'),ns)
    prepared=ns['reviewed_revision_for_staging'](A.state,qid)
    (out/'revision_staged.json').write_text(json.dumps({'questions':[prepared]}),encoding='utf8')
    before_state=copy.deepcopy(A.state)
    before_pack=(study/'questions.json').read_bytes()
    # Attestation must not be forged by a missing or incorrect confirmation.
    ns['input']=lambda prompt:'NO'
    assert ns['revision_approve'](qid,doc_url)==2
    assert (study/'questions.json').read_bytes()==before_pack
    assert not (root/'work'/'content_approvals.json').exists()
    for invalid in ('http://docs.aws.amazon.com/example',
                    'https://docs.aws.amazon.com.evil.test/anything',
                    'https://example.com/notaws'):
        assert ns['revision_approve'](qid,invalid)==2
    # Explicit operator confirmation records the digest and local-only sync.
    ns['input']=lambda prompt:qid
    assert ns['revision_approve'](qid,doc_url)==0
    approvals=json.loads((root/'work'/'content_approvals.json').read_text())['approvals']
    assert approvals[qid]['human_approved'] is True
    assert approvals[qid]['official_documentation_verified'] is True
    assert approvals[qid]['question_sha256']==lp.review_payload_digest(prepared)
    current=json.loads((study/'questions.json').read_text(encoding='utf8'))['questions']
    assert [x['id'] for x in current]==['original',qid]
    assert current[1]['choices']==prepared['choices']
    assert A.state==before_state
    # Repeat does not require typing again or duplicate the candidate.
    ns['input']=lambda _: (_ for _ in ()).throw(AssertionError('repeat should not reconfirm'))
    assert ns['revision_approve'](qid,doc_url)==0
    assert len(json.loads((study/'questions.json').read_text())['questions'])==2
    assert Lock.got==Lock.released
    Stop.stopped=False
    assert ns['revision_approve'](qid,doc_url)==2
    Stop.stopped=True
    Lock.busy=True
    assert ns['revision_approve'](qid,doc_url)==2
    Lock.busy=False
    # Source question, audit, and revision trial never overwritten.
    assert A.state==before_state
assert "if len(sys.argv)==4 and sys.argv[1]=='revision-approve'" in src
print('PASS explicit operator confirmation, AWS URL guard, digest, idempotent local sync')
