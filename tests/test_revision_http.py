"""Offline protocol check for the actual Responses API revision wire format.

Exercises the production schema and parsing code using mocked HTTP, no secrets,
no remote calls, and no changes to user data.
"""
import ast
import copy
import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

src=Path('release_files/update_watchdog.py').read_text(encoding='utf8')
tree=ast.parse(src)
wanted={'structured_batch_call','validated_revision_candidate'}
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
fields=[n for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id in ('FIELDS','SCHEMA') for t in n.targets)]
assert len(functions)==2 and len(fields)==2
ns={'json':json,'urllib':__import__('urllib'),
    'GENERATION_MODEL':'gpt-4.1-mini'}
ns['a']=SimpleNamespace(parse_reply=json.loads,validate=lambda q,strict=False: q)
exec(compile(ast.Module(body=fields+functions,type_ignores=[]),
             '<wire-tests>','exec'),ns)

original={'id':'SAA-AUTO-00001','exam':'SAA-C03','domain':'D2',
          'topic':'RTO RPO','type':'single','difficulty':'中級',
          'question':'Original with wrong answer',
          'choices':['A','B','C','D'],'correct':['A'],
          'explanation':'wrong','source':{'kind':'original','label':'first pass'},
          'language':'ja'}
revised={k:v for k,v in original.items() if k in ns['FIELDS']}
revised['question']='A unique and coherent recovery design scenario'
revised['explanation']='A is correct for recovery time; B, C and D do not meet RTO.'
client=SimpleNamespace(calls=0,limit=1,keys={'openai':'TEST_NOT_SECRET'})
requests=[]
class Response:
    def __init__(self,obj):self.obj=obj
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self):return json.dumps(self.obj).encode('utf8')
def urlopen(req,timeout):
    body=json.loads(req.data.decode('utf8'))
    requests.append((req.full_url,body,timeout))
    return Response({'status':'completed','output':[
      {'content':[{'type':'output_text','text':json.dumps({'questions':[revised]})}]}]})
with patch.object(urllib.request,'urlopen',urlopen):
    response=ns['structured_batch_call'](client,'revise only',
               {'specs':[{'id':original['id'],'domain':original['domain'],
                          'type':'single','topic':'RTO RPO','difficulty':'中級'}],
                'original':original,'issues':['RTO explanation is wrong']})
assert client.calls==1
url,body,timeout=requests[0]
assert url=='https://api.openai.com/v1/responses'
assert body['model']=='gpt-4.1-mini'
assert body['text']['format']['type']=='json_schema'
assert body['text']['format']['strict']==True
assert len(json.loads(body['input'])['specs'])==1
proposed=ns['validated_revision_candidate'](response,original)
assert proposed['source']==original['source']
assert proposed['review_status']=='ai_review_pending'
assert original['question']=='Original with wrong answer'
for key in ('id','domain','difficulty','type','topic','exam'):
    bad=copy.deepcopy(revised)
    bad[key]='WRONG'
    try:
        ns['validated_revision_candidate']({'questions':[bad]},original)
        assert False,key
    except ValueError:pass
for invalid in ({'questions':[]},{'questions':[revised,revised]},
                {'questions':'not a list'},{'questions':[None]}):
    try:
        ns['validated_revision_candidate'](invalid,original)
        assert False,invalid
    except ValueError:pass
multi=copy.deepcopy(original)
multi['type']='multiple'
multi['question']='Choose the best plans 2つ選択'
multi['correct']=['A','B']
candidate=copy.deepcopy(revised)
candidate['type']='multiple'
candidate['question']='No count given'
try:
    ns['validated_revision_candidate']({'questions':[candidate]},multi)
    assert False,'missing multiple count'
except ValueError:pass
# Fail closed on an incomplete provider response, even when text is present.
client=SimpleNamespace(calls=0,limit=1,keys={'openai':'TEST_NOT_SECRET'})
with patch.object(urllib.request,'urlopen',
                  lambda *args,**kwargs: Response({'status':'incomplete',
                      'incomplete_details':{'reason':'max_output_tokens'}})):
    try:
        ns['structured_batch_call'](client,'revise only',{})
        assert False,'incomplete must fail'
    except ValueError:pass
print('PASS revision Responses JSON schema, wire request, incomplete output, fixed attributes')
