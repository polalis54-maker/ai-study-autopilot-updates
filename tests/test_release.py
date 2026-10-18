"""Offline behavioral checks for releases. No credentials, network or spending."""
import ast
import json
import pathlib
import types
import urllib.request
from unittest.mock import patch

p = pathlib.Path("release_files/update_watchdog.py")
source = p.read_text(encoding="utf-8")
tree = ast.parse(source)
functions = {f.name:f for f in tree.body if isinstance(f,ast.FunctionDef)}
assert sum(1 for f in tree.body if isinstance(f,ast.FunctionDef) and f.name=="make")==1
imports = [alias.name for node in tree.body if isinstance(node,ast.Import) for alias in node.names]
assert "urllib.request" in imports, "Missing urllib.request import causes NameError"
assert "urllib.error" in imports
assert "from batch_generator import" not in source

class FakeA:
    OPENAI_MODEL="gpt-5-mini"
    today=lambda self:"2026-10-18"
    parse_reply=staticmethod(lambda x:json.loads(x))
    @staticmethod
    def validate(q,strict=False):
        if q.get("question")=="BAD":
            raise ValueError("Invalid fake question")
        return q

a=FakeA()
scope={"a":a,"json":json,"urllib":urllib,"CALL_CAP":25,
       "ONE_TIME_EXTRA_DATE":"2026-10-18","ONE_TIME_EXTRA_LIMIT":50}
subset=[functions[x] for x in
    ("daily_call_cap","used_today","fix_retry_due","structured_batch_call","salvage_batch")]
module=ast.fix_missing_locations(ast.Module(body=subset,type_ignores=[]))
exec(compile(module,str(p),"exec"),scope)

assert scope["daily_call_cap"]()==50
assert scope["daily_call_cap"]("2026-10-19")==25
state={"last_attempt":"2026-10-18","auto_retry_date":"2026-10-18",
       "history":[{"date":"2026-10-18","calls":23,"errors":["other failure"]},
                  {"date":"2026-10-18","calls":7,"errors":["NameError: name 'urllib' is not defined"]}]}
assert scope["used_today"](state)==30
assert scope["fix_retry_due"](state), "Should recover despite first retry used"
state["post_fix_retry_date"]="2026-10-18"
assert not scope["fix_retry_due"](state), "Must never automatically retry this fix twice"
state.pop("post_fix_retry_date")
state["history"][-1]["errors"]=["Non-recoverable error"]
assert not scope["fix_retry_due"](state), "Do not retry unrelated failures"
state["history"][-1]["errors"]=["NameError: name 'urllib' is not defined"]
a.today=lambda:"2026-10-19"
assert not scope["fix_retry_due"](state), "Temporary consent is date-scoped"
a.today=lambda:"2026-10-18"

class Client:
    calls=0
    limit=20
    keys={"openai":"testing-not-a-real-token"}

class Response:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):
        return json.dumps({"status":"completed","output":[
            {"content":[{"type":"output_text","text":'{"questions":[]}'}]}
        ]}).encode("utf-8")

client=Client()
with patch.object(urllib.request,"urlopen",lambda request,timeout:Response()):
    d=scope["structured_batch_call"](client,"prompt",{"specs":[]})
assert d=={"questions":[]} and client.calls==1

class PartialAPI:
    def call(self,*args):
        return {"questions":[
            {"id":"q1","exam":"SAA-C03","type":"single","domain":"D1",
             "difficulty":"中級","question":"VALID","choices":[],
             "correct":["A"]},
            {"id":"q2","exam":"SAA-C03","type":"single","domain":"D1",
             "difficulty":"中級","question":"BAD","choices":[],
             "correct":["B"]}
        ]}

specs=[{"id":i,"type":"single","domain":"D1","difficulty":"中級"}
       for i in ("q1","q2")]
accepted=scope["salvage_batch"](PartialAPI(),specs,"prompt")
assert [q["id"] for q in accepted]==["q1"], "Keep valid neighbor"
print("PASS: urllib import, JSON schema pathway, partial salvage, same-day recovery, date-scoped cap")
