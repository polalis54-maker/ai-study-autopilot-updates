#!/usr/bin/env python3
"""Read-only AI Study status. Never uses model API or changes saved questions."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'work'
OUT = WORK / 'outputs'

def read_json(path):
    try:
        obj = json.loads(path.read_text(encoding='utf-8-sig'))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}

def holding_background_lock():
    if os.name != 'nt':
        return None
    import msvcrt
    path = WORK / 'autopilot.lock'
    if not path.exists():
        return False
    try:
        with path.open('r+b') as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return False
    except OSError:
        return None

def last_lines(path, count=8):
    try:
        lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
        return lines[-count:]
    except OSError:
        return []

def inspect():
    state = read_json(WORK/'state.json')
    last = read_json(OUT/'last_result.json')
    live = read_json(OUT/'live_progress.json')
    update = read_json(WORK/'updates'/'current.json')
    version = update.get('version') or read_json(ROOT/'VERSION.json').get('version') or '?'
    existing = state.get('existing') or {}
    generated = state.get('generated') or {}
    failed = state.get('failed_generations') or {}
    reviewed_pass = sum(v.get('status') == 'AI_PASS' for v in existing.values() if isinstance(v, dict))
    generated_pass = sum(v.get('status') == 'AI_PASS' for v in generated.values() if isinstance(v, dict))
    lock = holding_background_lock()
    print('=== AI Study Autopilot 稼働確認（API料金ゼロ） ===')
    print('現在のローカル版: v' + str(version))
    print('自動実行:', '起動中（待機中の場合あり）' if lock else ('停止中' if lock is False else '判定できません'))
    print('既存問題レビュー: %d / 55（AI PASS %d）' % (len(existing), reviewed_pass))
    print('新規生成保存: %d（AI PASS %d）' % (len(generated), generated_pass))
    print('形式エラー等で未保存: %d（累計記録）' % len(failed))
    print('累計API呼び出し: %s' % state.get('total_calls', 0))
    print('最後に開始した日: %s' % (state.get('last_attempt') or '未実行'))
    if last:
        print('最後の記録日: %s / 使用API: %s回' % (last.get('date', '?'), last.get('calls','?')))
        if last.get('errors'):
            print('直近エラー: ' + str(last['errors'][0])[:260])
        else:
            print('直近エラー: 記録なし')
    if live:
        timestamp = live.get('updated_at', '')
        phase = live.get('phase', '')
        print('最終進捗: %s / %s' % (live.get('status','?'), phase))
        print('進捗更新時刻: ' + str(timestamp))
        if live.get('status') == 'RUNNING' and lock is False:
            print('注意: 進捗は処理中のままですが常駐は停止。古い表示の可能性があります。')
    updates = last_lines(OUT/'updates.log', 3)
    if updates:
        print('\n--- 自動更新ログ ---')
        for line in updates: print('  ' + line[:240])
    schedule = last_lines(OUT/'scheduler.log', 6)
    if schedule:
        print('\n--- バックグラウンド処理ログ ---')
        for line in schedule: print('  ' + line[:240])
    if (OUT/'live_progress.html').exists():
        print('\nリアルタイム進捗: OPEN_LIVE_STATUS.cmd から開けます。')
    print('注意: AI PASSは公式資料で正確性を確認した意味ではありません。')
    print('=== 確認終了 ===')

if __name__ == '__main__':
    try: inspect()
    except Exception as exc:
        print('稼働確認エラー: ' + str(exc))
        sys.exit(1)
