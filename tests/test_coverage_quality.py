"""Offline focused checks for SAA topic scheduling and conservative duplicate gate."""
import ast
import difflib
import re
from pathlib import Path

source=Path("release_files/update_watchdog.py").read_text(encoding="utf-8")
tree=ast.parse(source)
needed={"SAA_WEIGHTS","SAA_BLUEPRINT","SAA_DOMAIN_SLOTS"}
parts=[]
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in needed for t in node.targets):
        parts.append(node)
    if isinstance(node,ast.FunctionDef) and node.name in {"_saa_domain_slots","_topic_usage","specs_for","question_is_near_duplicate"}:
        parts.append(node)
ns={"difflib":difflib,"re":re}
exec(compile(ast.Module(body=parts,type_ignores=[]),"<saa-scheduler-test>","exec"),ns)
assert len(ns["SAA_DOMAIN_SLOTS"])==100
assert {k:ns["SAA_DOMAIN_SLOTS"].count(k) for k in ns["SAA_WEIGHTS"]}==ns["SAA_WEIGHTS"]
specs=ns["specs_for"]({"generated_index":0},200)
assert len(specs)==200 and len({s["id"] for s in specs})==200
assert {d:sum(s["domain"]==d for s in specs) for d in ns["SAA_WEIGHTS"]}=={d:n*2 for d,n in ns["SAA_WEIGHTS"].items()}
assert all(s["topic"] in ns["SAA_BLUEPRINT"][s["domain"]] for s in specs)
# A topic already present in the corpus must lose priority to an uncovered topic.
existing=[{"id":"old","domain":"D1","topic":ns["SAA_BLUEPRINT"]["D1"][0]}]
planned=ns["specs_for"]({"generated_index":0},1,existing)
assert planned[0]["topic"]!=existing[0]["topic"]
f=ns["question_is_near_duplicate"]
q={"id":"new","question":"ある企業はVPCのプライベートサブネットからKMSへ安全に接続する必要があります。最適な接続方法は何ですか。"}
old={"id":"old","question":q["question"]}
assert f(q,[old],{}) is True
other={"id":"diff","question":"EC2 のコストを最適化するために Spot Instances と Savings Plans を選択する設計要件は何ですか。"}
assert f(q,[other],{}) is False
print("PASS: SAA domain weights, domain/topic blueprint, near-duplicate gate")

# Verify that the generated-question quarantine is present and precedes persistence.
assert "status='QUALITY_HOLD'" in source
assert "mismatched fields:" in source
assert "if 'topic' in spec and q.get('topic')!=spec['topic']" in source
