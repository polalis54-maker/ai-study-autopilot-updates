"""Idempotent achievement UI patch for AI Study PWA.

Derives achievements from existing attempt/perfect-award history. Does not touch
questions, exam answers, API credentials, or user progress.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

MARKER="<!-- AI_STUDY_TROPHIES_V1 -->"
SAVE_ORIGINAL="function save(){return commitState()}"
SAVE_PATCHED="function save(){const ok=commitState();if(ok&&typeof trophyRefresh==='function')trophyRefresh();return ok}"
RENDER_ORIGINAL="function render(){({home:renderHome,study:renderStudy,review:renderReview,analysis:renderAnalysis,manage:renderManage}[tab])();if(!session || tab!=='study'){let [line,mood]=defaultAiLine(tab);sayAi(line,mood)}syncTeacherActions()}"
RENDER_PATCHED=RENDER_ORIGINAL[:-1]+";if(typeof trophyRender==='function')trophyRender()}"

TROPHY_UI=r"""
<style id="ai-study-trophy-style">
.trophy-home{background:linear-gradient(140deg,#3c2946,#1c2948);border-color:#6e517c}
.trophy-header{display:flex;justify-content:space-between;align-items:center;gap:10px}
.trophy-home .trophy-count{font-size:30px;font-weight:850;color:#ffe2a0;margin:5px 0}
.trophy-home .trophy-sub{color:#ccdaf3;font-size:12px}
.trophy-progress{height:9px;background:#151d32;border-radius:12px;overflow:hidden;margin:9px 0}
.trophy-progress>span{display:block;height:100%;background:linear-gradient(90deg,#f7b76a,#ff83c6);border-radius:12px}
.trophy-home button{width:100%;margin-top:10px}
.trophy-shade{position:fixed;inset:0;background:#070b19de;z-index:150;display:flex;align-items:center;justify-content:center;padding:12px}
.trophy-shade[hidden]{display:none!important}
.trophy-dialog{width:min(720px,100%);max-height:min(86dvh,850px);overflow:auto;background:#17213a;border:1px solid #8c6797;border-radius:19px;padding:18px;box-shadow:0 24px 65px #000b}
.trophy-dialog header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.trophy-dialog h2{font-size:19px;margin:0}
.trophy-dialog .trophy-filters{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}
.trophy-filters button{padding:8px 11px;border:1px solid #53617c;background:#243454;color:#d9e8ff;border-radius:10px;font-size:12px}
.trophy-filters button[aria-pressed=true]{background:#714774;color:#fff;border-color:#ff9bcc}
.trophy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.trophy-item{background:#242d48;border:1px solid #556782;padding:13px;border-radius:13px;min-width:0}
.trophy-item.locked{opacity:.62;filter:grayscale(.7)}
.trophy-item .glyph{font-size:28px;float:right}
.trophy-item strong{display:block;color:#ffe6ad;font-size:13px}
.trophy-item small{color:#b8c6e0;display:block;margin-top:5px;font-size:12px;line-height:1.5}
.trophy-item .tier{color:#ffc7eb;font-size:10px;font-weight:700}
.trophy-item .trophy-condition{color:#b0d7ec;font-size:11px;margin-top:4px}
.trophy-toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:155;width:min(420px,calc(100% - 30px));background:linear-gradient(110deg,#493359,#24375f);border:2px solid #ffc47b;border-radius:16px;padding:14px 17px;color:#fff;box-shadow:0 14px 35px #000b;text-align:center;font-weight:bold}
.trophy-toast[hidden]{display:none!important}
@media(max-width:410px){.trophy-grid{grid-template-columns:1fr}.trophy-dialog{padding:13px}}
@media(prefers-reduced-motion:reduce){.trophy-toast{transition:none}}
</style>
<script id="ai-study-trophy-script">
(function(){
'use strict';
const achievements=[
 ['first','🌱','はじめの一歩','回答1問','回答数',1,'responses','ノートを開いたその瞬間が始まり！'],
 ['ans10','📗','十問十色','回答10問','回答数',10,'responses','まずは10問、いい調子！'],
 ['ans25','📚','勉強エンジン始動','回答25問','回答数',25,'responses','学習が習慣になってきたね'],
 ['ans50','🎒','努力家','回答50問','回答数',50,'responses','積み重ねが見えてきた！'],
 ['ans100','⚔️','SAA修行者','回答100問','回答数',100,'responses','100問を突破した実力'],
 ['ans200','🧭','知識の探検家','回答200問','回答数',200,'responses','200回のチャレンジ！'],
 ['ans300','🏰','問題の住人','回答300問','回答数',300,'responses','すごい学習量！'],
 ['ok1','✨','初正解','正解1問','正解数',1,'correct','最初の正解！'],
 ['ok10','⭐','十連星','累計10問正解','正解数',10,'correct','正しい判断を積み重ねたよ'],
 ['ok25','🌟','知識が芽吹く','累計25問正解','正解数',25,'correct','理解が広がってきたね'],
 ['ok50','💎','判断力アップ','累計50問正解','正解数',50,'correct','50問分の成果だよ'],
 ['ok100','🥇','百戦錬磨','累計100問正解','正解数',100,'correct','100問正解！'],
 ['ok200','👑','解答マスター','累計200問正解','正解数',200,'correct','たくさん理解した証だね'],
 ['streak3','🔥','三連撃','3問連続正解','連続正解',3,'bestStreak','3連続正解！'],
 ['streak5','⚡','波に乗ってる','5問連続正解','連続正解',5,'bestStreak','集中力ばっちり！'],
 ['streak10','🚀','覚醒の十連撃','10問連続正解','連続正解',10,'bestStreak','10連続は大きいよ'],
 ['day2','🌤️','また会えたね','2日連続学習','継続',2,'bestDays','2日続けて勉強したね'],
 ['day3','🪴','三日坊主卒業','3日連続学習','継続',3,'bestDays','続ける力がついてきた'],
 ['day7','🌈','一週間の積み重ね','7日連続学習','継続',7,'bestDays','継続は力！'],
 ['day14','🏅','学習習慣マスター','14日連続学習','継続',14,'bestDays','努力が日常になったよ'],
 ['unique10','🧩','問題探検','異なる問題を10問回答','初見挑戦',10,'unique','新しい知識に出会おう'],
 ['unique30','🗺️','知識の地図','異なる問題を30問回答','初見挑戦',30,'unique','広い範囲を学んだね'],
 ['unique50','🌍','AWS探究者','異なる問題を50問回答','初見挑戦',50,'unique','いろんな分野に触れたよ'],
 ['retry1','🔄','リベンジ成功','間違えた問題を後で1回正解','復習',1,'recoveries','間違いを理解に変えた！'],
 ['retry5','🛠️','弱点クラッシャー','間違えた問題を後で5回正解','復習',5,'recoveries','苦手が強みに変わるね'],
 ['guess3','🎯','直感が光る','迷い・推測で3問正解','挑戦',3,'uncertainWins','解説で根拠も確かめてね'],
 ['guess10','🧠','推理名人','迷い・推測で10問正解','挑戦',10,'uncertainWins','勘を知識に変えていこう'],
 ['perfect1','🏆','パーフェクト！','演習・模試で1回満点','特別',1,'perfect','アイ先生から大きな花丸！'],
 ['perfect3','🎊','満点コレクター','演習・模試で3回満点','特別',3,'perfect','3回も満点、お見事！'],
 ['sure1','🔍','思い込みを発見','確信して間違えた問題を1問発見','発見',1,'sureMistakes','気づくことが成長の入り口！']
];
let filter='all';
let previous=null;
let toastTimer=null;
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $t=id=>document.getElementById(id);
function metrics(){
  const records=(Array.isArray(attempts)?attempts:[]).filter(x=>x&&typeof x==='object')
      .slice().sort((a,b)=>Date.parse(a.ts||0)-Date.parse(b.ts||0));
  let correct=0,bestStreak=0,streak=0,sureMistakes=0,uncertainWins=0,recoveries=0;
  const wrongIds=new Set();
  const days=new Set();
  for(const r of records){
    if(r.correct){correct++;streak++;bestStreak=Math.max(bestStreak,streak);
      if(wrongIds.has(r.id)){recoveries++;wrongIds.delete(r.id)}
      if(r.confidence==='迷い'||r.confidence==='推測')uncertainWins++;
    }else{
      streak=0;if(r.id)wrongIds.add(r.id);
      if(r.confidence==='確信')sureMistakes++;
    }
    const d=new Date(r.ts);if(!Number.isNaN(d.getTime()))
      days.add(d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'));
  }
  let bestDays=0,daysStreak=0,prev=null;
  for(const key of [...days].sort()){
    const day=Date.parse(key+'T12:00:00');
    daysStreak=prev!==null&&Math.round((day-prev)/86400000)===1?daysStreak+1:1;
    bestDays=Math.max(bestDays,daysStreak);prev=day;
  }
  return {responses:records.length,correct,bestStreak,bestDays,
    unique:new Set(records.map(x=>x.id).filter(Boolean)).size,
    recoveries,uncertainWins,perfect:Array.isArray(perfectAwards)?perfectAwards.length:0,sureMistakes};
}
function earned(stats){return achievements.filter(t=>(stats[t[6]]||0)>=t[5])}
function paintTrophyHome(){
  const side=document.querySelector('#screen-home .home-sidebar');
  if(!side)return;
  const s=metrics(),unlocked=earned(s).length, pct=Math.round(100*unlocked/achievements.length);
  let node=$t('trophyHomeCard');
  if(!node){
    node=document.createElement('section');
    node.id='trophyHomeCard';node.className='card dash-card trophy-home';
    side.insertBefore(node,side.firstChild);
  }
  node.innerHTML='<div class="trophy-header"><h2 style="margin:0">🏆 トロフィー</h2><span>✨</span></div>'+
    '<div class="trophy-count">'+unlocked+' / '+achievements.length+'</div>'+
    '<div class="trophy-progress"><span style="width:'+pct+'%"></span></div>'+
    '<div class="trophy-sub">これまでの学習履歴から自動判定。獲得を目指そう！</div>'+
    '<button class="btn secondary" type="button" id="showTrophies">トロフィー一覧を見る →</button>';
  $t('showTrophies').addEventListener('click',openTrophies);
}
function drawGrid(){
  const grid=$t('trophyGrid');if(!grid)return;
  const stats=metrics(),ids=new Set(earned(stats).map(t=>t[0]));
  const visible=achievements.filter(t=>filter==='all'||(filter==='unlocked'?ids.has(t[0]):!ids.has(t[0])));
  grid.innerHTML=visible.length?visible.map(t=>{
    const open=ids.has(t[0]);
    return '<article class="trophy-item '+(open?'':'locked')+'"><span class="glyph" aria-hidden="true">'+(open?t[1]:'🔒')+'</span>'+
      '<span class="tier">'+safe(t[4])+' · '+(open?'獲得済み':'未獲得')+'</span>'+
      '<strong>'+safe(t[2])+'</strong><small>'+safe(t[7])+'</small>'+
      '<div class="trophy-condition">'+safe(t[3])+' · '+Math.min(stats[t[6]]||0,t[5])+'/'+t[5]+'</div></article>';
  }).join(''):'<p class="muted">ここにはまだトロフィーがないよ。</p>';
  const count=$t('trophyModalCount');if(count)count.textContent=ids.size+' / '+achievements.length+' 獲得';
  document.querySelectorAll('[data-trophy-filter]').forEach(btn=>btn.setAttribute('aria-pressed',String(btn.dataset.trophyFilter===filter)));
}
function ensureModal(){
  if($t('trophyModal'))return;
  const shade=document.createElement('div');shade.id='trophyModal';shade.className='trophy-shade';shade.hidden=true;
  shade.innerHTML='<section class="trophy-dialog" role="dialog" aria-modal="true" aria-labelledby="trophyTitle">'+
    '<header><h2 id="trophyTitle">🏆 学習トロフィー</h2><button class="btn secondary" type="button" id="closeTrophies">閉じる ×</button></header>'+
    '<p class="tiny" id="trophyModalCount"></p>'+
    '<div class="trophy-filters"><button data-trophy-filter="all" aria-pressed="true">すべて</button>'+
    '<button data-trophy-filter="unlocked" aria-pressed="false">獲得済み</button>'+
    '<button data-trophy-filter="locked" aria-pressed="false">未獲得</button></div>'+
    '<div class="trophy-grid" id="trophyGrid"></div>'+
    '<p class="tiny">※記録はこの端末の学習履歴をもとに計算。トロフィーは認定試験の合否を保証するものではありません。</p></section>';
  document.body.append(shade);
  shade.addEventListener('click',e=>{if(e.target===shade)closeTrophies()});
  $t('closeTrophies').addEventListener('click',closeTrophies);
  shade.querySelectorAll('[data-trophy-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.trophyFilter;drawGrid()}));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!shade.hidden)closeTrophies()});
  const toast=document.createElement('div');toast.id='trophyToast';toast.className='trophy-toast';toast.hidden=true;toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');
  document.body.append(toast);
}
function openTrophies(){
  ensureModal();drawGrid();const box=$t('trophyModal');box.hidden=false;box.querySelector('#closeTrophies').focus();
}
function closeTrophies(){$t('trophyModal').hidden=true;const btn=$t('showTrophies');if(btn)btn.focus()}
function trophyRender(){
  ensureModal();paintTrophyHome();
  if(!$t('trophyModal').hidden)drawGrid();
}
function trophyRefresh(){
  const ids=new Set(earned(metrics()).map(t=>t[0]));
  const newly=previous?[...ids].filter(id=>!previous.has(id)):[];
  previous=ids;
  trophyRender();
  if(newly.length){
    const t=achievements.find(t=>t[0]===newly[0]);
    const message=t[1]+' トロフィー獲得！ '+t[2]+(newly.length>1?' ＋'+(newly.length-1)+'個':'');
    const toast=$t('trophyToast');toast.textContent=message;toast.hidden=false;
    if(typeof sayAi==='function')sayAi('🏆 '+t[2]+' 獲得！ よく頑張ったねっ💕','トロフィー獲得');
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true},4500);
  }
}
previous=new Set(earned(metrics()).map(t=>t[0]));
trophyRender();
})();
</script>
"""

def install(study:Path)->bool:
    """Inject trophy UI into the current local PWA without changing questions."""
    study=Path(study)
    path=study/'index.html'
    sw=study/'sw.js'
    original=path.read_text(encoding='utf-8')
    if MARKER in original:
        return False
    if original.count(SAVE_ORIGINAL)!=1 or original.count(RENDER_ORIGINAL)!=1:
        raise ValueError('Unknown AI Study version; trophy patch refused safely')
    if original.count('</body>')!=1:
        raise ValueError('AI Study document structure unexpected')
    updated=original.replace(SAVE_ORIGINAL,SAVE_PATCHED)
    updated=updated.replace(RENDER_ORIGINAL,RENDER_PATCHED)
    updated=updated.replace('</body>',MARKER+'\n'+TROPHY_UI+'</body>')
    if not sw.is_file():raise ValueError('Missing PWA service worker')
    sw_text=sw.read_text(encoding='utf-8')
    old_cache=re.search(r"const CACHE='ai-study-[^']+';",sw_text)
    if not old_cache:raise ValueError('Unknown AI Study PWA cache; refused')
    new_cache="const CACHE='ai-study-trophy-"+hashlib.sha256(updated.encode()).hexdigest()[:12]+"';"
    sw_updated=sw_text[:old_cache.start()]+new_cache+sw_text[old_cache.end():]
    a=path.with_suffix('.html.trophy.tmp');b=sw.with_suffix('.js.trophy.tmp')
    a.write_text(updated,encoding='utf-8');b.write_text(sw_updated,encoding='utf-8')
    a.replace(path)
    try:b.replace(sw)
    except Exception:
        restore=path.with_suffix('.html.restore.tmp')
        restore.write_text(original,encoding='utf-8');restore.replace(path)
        raise
    return True
