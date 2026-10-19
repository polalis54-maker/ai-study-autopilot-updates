"""Tests for trophy patch. Offline, no user history, credentials, or network."""
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('live_progress','release_files/live_progress.py')
t=importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
js=t.TROPHY_UI.split('<script id="ai-study-trophy-script">',1)[-1].split('</script>',1)[0]
assert "window.trophyRefresh=trophyRefresh" in js
assert "window.trophyRender=trophyRender" in js
assert "Array.isArray(attempts)" in js and "perfectAwards" in js
assert "localStorage.setItem" not in js, "Trophy module should not mutate existing history"
assert "fetch(" not in js, "Trophies must be local and cost zero"
assert len(re.findall(r"(?m)^\s*\['[a-z0-9]+',",js))==30
assert len(re.findall(r"(?m)^\s*\['[a-z0-9]+',",js))==len(set(re.findall(r"(?m)^\s*\['([a-z0-9]+)',",js)))

with tempfile.TemporaryDirectory() as root:
    study=Path(root)/'AI_Study';study.mkdir()
    html='<html lang="ja"><head></head><body><script>'+t.SAVE_ORIGINAL+'\n'+t.RENDER_ORIGINAL+'</script></body></html>'
    (study/'index.html').write_text(html,encoding='utf-8')
    (study/'sw.js').write_text("const CACHE='ai-study-v0.9';\n",encoding='utf-8')
    original_questions=json.dumps({'questions':[{'id':'SAA-ORIG-0001','question':'How do IAM roles work?'}]},ensure_ascii=False)
    (study/'questions.json').write_text(original_questions,encoding='utf-8')
    assert t.install_trophy_ui(study) is True
    final=(study/'index.html').read_text(encoding='utf-8')
    assert t.SAVE_PATCHED in final and t.RENDER_PATCHED in final
    assert t.MARKER in final
    assert final.count('ai-study-trophy-script')==1
    assert t.install(study) is False, "Re-runs must not duplicate trophy UI"
    assert (study/'questions.json').read_text(encoding='utf-8')==original_questions
    assert "ai-study-trophy-" in (study/'sw.js').read_text(encoding='utf-8')
    js_path=Path(root)/'trophies.js';js_path.write_text(js,encoding='utf-8')
    # Node.js is preinstalled on GitHub ubuntu-latest runners.
    subprocess.run(['node','--check',str(js_path)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    bad=Path(root)/'unknown';bad.mkdir()
    (bad/'index.html').write_text('<body>Another app</body>',encoding='utf-8')
    (bad/'sw.js').write_text("const CACHE='ai-study-v1';",encoding='utf-8')
    try:t.install_trophy_ui(bad)
    except ValueError:pass
    else:raise AssertionError("Unknown app should remain unchanged")
    assert (bad/'index.html').read_text(encoding='utf-8')=='<body>Another app</body>'

print('PASS: 30 unique milestones, source JS syntax, existing history unchanged, duplicate-safe injection and cache refresh')
