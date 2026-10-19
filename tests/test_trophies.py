"""Tests for trophy patch. Offline, no user history, credentials, or network."""
import importlib.util
import json
import re
import subprocess
import tempfile
from pathlib import Path
import sys

spec=importlib.util.spec_from_file_location('live_progress','release_files/live_progress.py')
t=importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
# The same module is also run as a CLI script to publish Netlify updates.
# Defining the installer after the __main__ dispatch caused NameError at deploy time.
src=Path('release_files/live_progress.py').read_text(encoding='utf-8')
assert src.index('def install_trophy_ui(') < src.index("if __name__=='__main__':"), "Trophy functions must exist before CLI dispatch"
cli=subprocess.run([sys.executable,'release_files/live_progress.py','status-mobile'],capture_output=True,text=True,check=True)
assert cli.returncode==0
js=t.TROPHY_UI.split('<script id="ai-study-trophy-script">',1)[-1].split('</script>',1)[0]
assert "window.trophyRefresh=trophyRefresh" in js
assert "window.trophyRender=trophyRender" in js
assert "Array.isArray(attempts)" in js and "perfectAwards" in js
assert "localStorage.setItem" not in js, "Trophy module should not mutate existing history"
assert "fetch(" not in js, "Trophies must be local and cost zero"
assert len(re.findall(r"(?m)^\s*\['[a-z0-9]+',",js))==30
extras=re.findall(r'(?m)^\s*\["bonus_[a-zA-Z0-9_]+",',js)
assert len(extras)==70, f"Expected 70 additional trophies, got {len(extras)}"
assert 'achievements.push(...trophyExtras)' in js
assert 'tierFilter' in js and 'trophyTierSelect' in js
assert 'balancedCoverage' in js and 'bestRate100' in js

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
    assert t.install_trophy_ui(study) is False, "Re-runs must not duplicate trophy UI"
    # Simulate a previously published v1 trophy block and verify safe in-place upgrade.
    previous=(study/'index.html').read_text(encoding='utf-8')
    reduced=re.sub(r'const trophyExtras=\[.*?\];\nachievements.push\(\.\.\.trophyExtras\);', 'const trophyExtras=[];\nachievements.push(...trophyExtras);', previous, flags=re.S)
    assert reduced!=previous
    (study/'index.html').write_text(reduced,encoding='utf-8')
    assert t.install_trophy_ui(study) is True
    upgraded=(study/'index.html').read_text(encoding='utf-8')
    assert upgraded==previous
    assert upgraded.count('ai-study-trophy-script')==1
    assert t.install_trophy_ui(study) is False
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

# Evaluate the actual 100-achievement logic against representative learning history.
runtime=js[js.index('const achievements='):js.index("let filter='all';")]+'\n'+js[js.index('function metrics(){'):js.index('function trophyTier(t)')]
node_test="""
const assert=require('node:assert/strict');
const p={domains:{D1:'Security',D2:'Resilience',D3:'Performance',D4:'Costs'}};
const before=Array.from({length:40},(_,i)=>({id:'Q'+i,domain:'D'+(i%4+1),
  correct:(i%5!==0),confidence:'確信',ts:new Date(Date.UTC(2026,9,1)+i*60000).toISOString()}));
const awards=[{count:10}];
const evaluate=new Function('attempts','perfectAwards','pack',process.env.ACHIEVEMENTS_SOURCE+
  '; return {length:achievements.length,ids:achievements.map(t=>t[0]),statistics:metrics(),earned:earned(metrics()).length};');
const first=evaluate(before,awards,p);
assert.equal(first.length,100);
assert.equal(new Set(first.ids).size,100);
assert.equal(first.statistics.domainsSeen,4);
assert.equal(first.statistics.balancedCoverage,10);
assert.equal(first.statistics.responses,40);
assert.equal(first.statistics.unique,40);
const extra={id:'Q40',domain:'D1',correct:false,confidence:'確信',ts:new Date(Date.UTC(2026,9,1)+50*60000).toISOString()};
const second=evaluate([...before,extra],awards,p);
assert.ok(second.statistics.bestRate20>=first.statistics.bestRate20);
assert.ok(second.statistics.domainsMastered>=first.statistics.domainsMastered);
assert.ok(second.earned>=first.earned);
console.log('PASS: 100 unique trophies, four-domain coverage, and monotonic progress');
"""
import os
env=dict(os.environ,ACHIEVEMENTS_SOURCE=runtime)
subprocess.run(['node','-e',node_test],check=True,env=env)
print('PASS: 100 achievements, runtime metrics, v1->v2 migration, no loss to question history, JS syntax')

# Growth-room integration checks for the v0.5.0 release.
assert '<!-- AI_STUDY_GROWTH_V1 -->' in t.TROPHY_UI
assert 'window.aiGrowthRender=render' in t.TROPHY_UI
assert 'if(typeof aiGrowthRender' in t.RENDER_PATCHED
# Only scene selection may be stored. Never overwrite study history.
growth_js=t.TROPHY_UI.split('<script id="ai-study-growth-script">',1)[1].split('</script>',1)[0]
assert 'localStorage.setItem' not in js
assert 'localStorage.setItem(storageKey,selected)' in growth_js
assert "const storageKey='ai-study-growth-scene-v1'" in growth_js
assert 'ai-teacher-avatar.webp' in growth_js
assert 'growthStage' in growth_js and 'growthScenes' in growth_js
assert 'growthTalk' in growth_js and 'growthPractice' in growth_js
assert 'fetch(' not in growth_js

# Regression: growth room must be visible on first load, before the practice form.
assert 'window.aiGrowthRender=render;\nrender();' in t.TROPHY_UI
assert "document.querySelector('#screen-home .home-main')" in t.TROPHY_UI
assert "main.querySelector('.home-split')" in t.TROPHY_UI

with tempfile.TemporaryDirectory() as d:
    growth_path=Path(d)/'growth.js';growth_path.write_text(growth_js,encoding='utf-8')
    subprocess.run(['node','--check',str(growth_path)],check=True)
