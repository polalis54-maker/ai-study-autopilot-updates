"""Offline end-to-end: revision trial -> staged PWA format -> verified-only sync.

Does not use API credentials, local user files or internet.
"""
import ast
import copy
import importlib.util
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'reviewed_revision_for_staging','revision_stage'}
subset=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
assert len(subset)==2
spec=importlib.util.spec_from_file_location('lp','release_files/live_progress.py')
lp=importlib.util.module_from_spec(spec);spec.loader.exec_module(lp)
id='SAA-AUTO-00020'
q={'id':id,'exam':'SAA-C03','domain':'D2','topic':'Multi-AZ failover',
   'type':'single','difficulty':'中級','language':'ja',
   'question':'ある企業がAWSのRDSを利用しています。DB障害からの迅速な復旧を実現し、運用負担を減らす構成として最適なものはどれですか？',
   'choices':['Multi-AZ','Read Replica','S3','SNS'],'correct':['A'],
   'explanation':'Multi-AZ構成は可用性向上のためにスタンバイを維持し、対象障害時に自動フェイルオーバーできます。'
                 '読み取りレプリカは主に読み取り分散用です。S3はDBの自動フェイルオーバーを提供しません。'
                 'SNSは通知サービスであり、RDSの代替構成にはなりません。',
   'source':{'kind':'original','label':'generated'}}
def state_fixture():
    return {'generated':{id:{'status':'REVISE_UNRESOLVED','candidate':dict(q)}},
        'revision_trials':{id:{'status':'REVIEWED_HOLD','original_status':'REVISE_UNRESOLVED',
             'candidate':copy.deepcopy(q),
             'review':{'verdict':'PASS','issues':[],'exam_quality':{'reason':'pass'}}}}}
class A:
    STATEFILE='work/state.json'
    state=state_fixture()
    saved={}
    @staticmethod
    def state_default():return {}
    @classmethod
    def jread(cls,path,default=None):
        return cls.saved.get(str(path),cls.state if str(path)==cls.STATEFILE else default)
    @classmethod
    def jwrite(cls,path,data):
        cls.saved[str(path)]=copy.deepcopy(data)
    @staticmethod
    def validate(q,strict=False):
        assert strict and q['id']==id
    @staticmethod
    def meets_exam_quality(r):return True
class UA:
    busy=False
    taken=0
    released=0
    @classmethod
    def windows_lock(cls,*a):
        if cls.busy:return None
        cls.taken+=1
        return object()
    @classmethod
    def release_lock(cls,lock):cls.released+=1
class STOP:
    stopped=True
    @classmethod
    def exists(cls):return cls.stopped
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    staged=root/'work'/'outputs'/'revision_staged.json'
    staged.parent.mkdir(parents=True)
    ns={'a':A,'ua':UA,'STOP':STOP,'ROOT':root,'LOCK':root/'autopilot.lock','re':re,
        'question_is_near_duplicate':lambda *args:False}
    exec(compile(ast.Module(body=subset,type_ignores=[]),'<stage>', 'exec'),ns)
    before=copy.deepcopy(A.state)
    prepared=ns['reviewed_revision_for_staging'](A.state,id)
    assert prepared['choices']=={'A':'Multi-AZ','B':'Read Replica','C':'S3','D':'SNS'}
    assert prepared['correct']==['A']
    assert prepared['review_status']=='ai_reviewed_unverified'
    assert prepared['source']['kind']=='original'
    assert ns['revision_stage'](id)==0
    assert ns['revision_stage'](id)==0, 'should be idempotent'
    assert len(A.saved[str(staged)]['questions'])==1
    assert A.state==before
    assert UA.taken==UA.released==2
    STOP.stopped=False
    assert ns['revision_stage'](id)==2
    STOP.stopped=True
    UA.busy=True
    assert ns['revision_stage'](id)==2
    UA.busy=False
    assert len(A.saved[str(staged)]['questions'])==1
    for mutation in ('bad_status','bad_review','bad_format','changed_original','bad_explanation'):
        state=state_fixture()
        if mutation=='bad_status':state['revision_trials'][id]['status']='REVISION_ERROR'
        if mutation=='bad_review':state['revision_trials'][id]['review']['verdict']='REVISE'
        if mutation=='bad_format':state['revision_trials'][id]['candidate']['choices']=['A','B']
        if mutation=='changed_original':state['generated'][id]['status']='BLOCKED'
        if mutation=='bad_explanation':state['revision_trials'][id]['candidate']['explanation']='short'
        try:ns['reviewed_revision_for_staging'](state,id);assert False,mutation
        except ValueError:pass
    # Now verify the real downstream PC sync using staged-only content.
    study=root/'AI_Study';study.mkdir()
    base={'questions':[{'id':'base','question':'already present'}]}
    (study/'questions.json').write_text(json.dumps(base),encoding='utf8')
    (study/'index.html').write_text('<script id="default-pack" type="application/json">'+json.dumps(base)+'</script>',encoding='utf8')
    (study/'sw.js').write_text("const CACHE='ai-study-v1';",encoding='utf8')
    staged.write_text(json.dumps(A.saved[str(staged)],ensure_ascii=False),encoding='utf8')
    original_files={name:(study/name).read_bytes() for name in ('questions.json','index.html','sw.js')}
    result=lp.sync_study_pack(staged.parent)
    assert result['status']=='BLOCKED_UNVERIFIED',result
    assert all((study/name).read_bytes()==raw for name,raw in original_files.items())
    approvals=root/'work'/'content_approvals.json'
    approvals.write_text(json.dumps({'approvals':{id:{
        'human_approved':True,'official_documentation_verified':True,
        'documentation_url':'https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html',
        'question_sha256':lp.review_payload_digest(prepared)}}}),encoding='utf8')
    result=lp.sync_study_pack(staged.parent)
    assert result['status']=='SYNCED' and result['newly_added']==1,result
    questions=json.loads((study/'questions.json').read_text(encoding='utf8'))['questions']
    assert len(questions)==2 and questions[1]['id']==id
    assert questions[1]['choices']==prepared['choices']
    assert A.state==before
assert "if len(sys.argv)==3 and sys.argv[1]=='revision-stage'" in src
print('PASS held revision -> stage -> no auto-publish -> explicitly approved PWA sync')
