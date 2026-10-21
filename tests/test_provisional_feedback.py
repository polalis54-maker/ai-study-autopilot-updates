"""Offline provisional feedback contract; no browser storage or network access."""
import re
import subprocess
import tempfile
from pathlib import Path
import importlib.util

spec=importlib.util.spec_from_file_location("lp","release_files/live_progress.py")
lp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)
html=lp.PREVIEW_HTML
assert "未検証問題の品質報告" in html
assert "function normalizeProgress(value)" in html
assert "function recordAttempt(q,correct)" in html
assert "function summarizeProgress(data)" in html
assert "function persistProgress()" in html
assert "JSON保存" in html and "JSONを読み込む" in html
assert "localStorage" not in html and "fetch(" not in html
assert "practiceProgress.reports[q.id]" in html
assert "recordAttempt(q,picked===correct)" in html
assert "new Blob(" in html and "URL.createObjectURL(blob)" in html
assert "file.size>1024*1024" in html
assert "a.tries-1" in html and "a.repeatCorrect" in html
assert "el('grade').disabled=true" in html
assert "reportNote" in html and "slice(0,500)" in html
js=re.search(r"<script>(.*?)</script>",html,re.S)
assert js is not None
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/"feedback.js"
    path.write_text(js.group(1).replace("__PAYLOAD__","[]"),encoding="utf-8")
    subprocess.run(["node","--check",str(path)],check=True)
print("PASS: provisional feedback UI, JSON export/import, no network/browser storage, JavaScript syntax")
