#!/usr/bin/env python3
"""
marksix_fetch.py — 自動抓取香港六合彩最新開獎，更新 marksix.html

用法：
  python3 marksix_fetch.py          # 抓取並更新
  python3 marksix_fetch.py --dry    # 只顯示，不寫入

依賴：pip3 install requests
"""

import re
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import date

try:
    import requests
except ImportError:
    print("❌ 請先安裝：pip3 install requests")
    sys.exit(1)

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import pick_engine  # 4×3 選號引擎（sfg-v1，2026-08-09）
GAME = 'm6'

DATA_FILE = Path(__file__).parent / "data_m6.js"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
# 2026-08-05 換源：舊源 en.lottolyzer.com 的 hong-kong/mark-six 路徑已被站方改掛
# 台灣威力彩（頁面 title 變 "Super Lotto 638 - Taiwan"），期號欄格式也從 26/082 變純數字，
# 導致正則永遠不匹配 →「無新資料」假象（7/30 之後停更 5 天才發現）。
# 新主源 cpzhan 帶「期數」欄可直接對到期號；備援 pilio 只有日期，期號用主源或遞推補。
BASE_URL = "https://www.cpzhan.com/liu-he-cai/all-results"
FALLBACK_URL = "https://www.pilio.idv.tw/ltohk/list.asp"



def draw_str_to_p(draw_str: str) -> int:
    """'26/067' → 26067"""
    parts = draw_str.split('/')
    return int(parts[0]) * 1000 + int(parts[1])


def read_current_latest(html: str) -> int:
    m = re.search(r"const BASE_REC = \[\s*\{p:(\d+)", html)
    return int(m.group(1)) if m else 0

def read_latest_dt(html: str):
    m = re.search(r'const BASE_REC = \[.*?"dt":"(\d{4}-\d{2}-\d{2})"', html, re.DOTALL)
    if m:
        from datetime import datetime
        return datetime.strptime(m.group(1), '%Y-%m-%d').date()
    return None


def _rows_of(html: str) -> list:
    """把 HTML 表格拆成每列的欄位字串陣列"""
    out = []
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL):
        tds = [re.sub(r'<[^>]+>', '', t).replace('&nbsp;', ' ').strip()
               for t in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
        if tds:
            out.append(tds)
    return out


def fetch_from_cpzhan(from_p: int) -> list:
    """主源：cpzhan 全年結果表（年份, 期數, 日期, N1..N6, 特碼）"""
    r = requests.get(BASE_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if '六合彩' not in r.text:
        raise ValueError('主源頁面不含「六合彩」字樣，疑似被改掛其他彩種')

    draws = []
    for tds in _rows_of(r.text):
        if len(tds) < 10 or not re.match(r'^20\d\d$', tds[0]):
            continue
        if not (tds[1].isdigit() and re.match(r'^20\d\d-\d\d-\d\d$', tds[2])):
            continue
        p = int(tds[0][2:]) * 1000 + int(tds[1])
        if p <= from_p:
            continue
        nums = [int(x) for x in tds[3:9] if x.isdigit() and 1 <= int(x) <= 49]
        if len(nums) != 6 or not tds[9].isdigit():
            continue
        draws.append({'p': p, 'draw': f'{tds[0][2:]}/{int(tds[1]):03d}',
                      'dt': tds[2], 'n': sorted(nums), 'e': int(tds[9])})
    return draws


def fetch_from_pilio(from_p: int, latest_dt) -> list:
    """備援：pilio 只給日期＋號碼，沒有期號 → 依日期排序從 from_p 遞推期號"""
    r = requests.get(FALLBACK_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if '六合彩' not in r.text:
        raise ValueError('備援頁面不含「六合彩」字樣')

    found = []
    for tds in _rows_of(r.text):
        # 日期欄長相：'08/0426(二)' = MM/DD + 民國後兩碼西元年 + (週幾)
        if len(tds) < 3:
            continue
        m = re.match(r'^(\d\d)/(\d\d)(\d\d)\(', tds[0])
        if not m:
            continue
        mm, dd, yy = m.groups()
        dt = f'20{yy}-{mm}-{dd}'
        nums = [int(x) for x in re.findall(r'\d+', tds[1]) if 1 <= int(x) <= 49]
        extra = int(tds[2]) if tds[2].isdigit() else 0
        if len(nums) == 6 and extra:
            found.append({'dt': dt, 'n': sorted(nums), 'e': extra})

    # 只留比現有最新一期更晚的日期，由舊到新遞推期號
    if latest_dt:
        found = [d for d in found if d['dt'] > latest_dt.isoformat()]
    found.sort(key=lambda d: d['dt'])
    draws = []
    for i, d in enumerate(found, start=1):
        p = from_p + i
        draws.append({'p': p, 'draw': f'{p // 1000}/{p % 1000:03d}', **d})
    return draws


def fetch_draws(from_p: int, latest_dt=None) -> list:
    results = []
    try:
        results = fetch_from_cpzhan(from_p)
        if results:
            print(f"✅ 找到 {len(results)} 筆新資料（主源 cpzhan）")
    except Exception as e:
        print(f"⚠️ 主源失敗（{e}），改用備援 pilio")
        try:
            results = fetch_from_pilio(from_p, latest_dt)
            if results:
                print(f"✅ 找到 {len(results)} 筆新資料（備援 pilio，期號為遞推值）")
        except Exception as e2:
            print(f"❌ 備援也失敗：{e2}")
            return []
    return sorted(results, key=lambda x: x['p'], reverse=True)


def calc_absent(records: list) -> dict:
    ab = {}
    for n in range(1, 50):
        count = 0
        for r in records:
            if n in r['n']:
                break
            count += 1
        ab[n] = count
    return ab


def build_pair_stat(records):
    pairs = {}
    for r in records:
        s = sorted(r['n'])
        for i in range(len(s)-1):
            for j in range(i+1, len(s)):
                k = f"{s[i]}-{s[j]}"
                pairs[k] = pairs.get(k, 0) + 1
    return pairs

def unpop_score(n):
    """冷門度（0~100）：避開大眾熱門簽法——生日範圍(1~31)、月份(1~12)、
    華人幸運號(3,6,8,9,18,28,38,48)與西方幸運7；尾4因忌諱少人簽反而加分"""
    s = 40.0
    if n >= 32: s += 35
    if n > 12:  s += 15
    if n % 10 == 4: s += 10
    if n in (3, 6, 7, 8, 9, 18, 28, 38, 48): s -= 25
    return s

def gen_pending(records: list) -> dict:
    """sfg-v2 四組×3碼 ＋ fpx-v1 不出牌排除區（2026-08-12 事前註冊，皆在 pick_engine）。

    v2 與 v1 的差異：候選池除避上期外，再排除 fpx-v1 排除區（排除顆數浮動，
    ＝「沉寂深度的歷史回歸率低於理論值」的號碼；顆數不再固定 15）。
    規格全文與驗算 CLI 見 pick_engine.py；排除區已含在回傳的 excluded 欄位。
    誠實揭露：平坦度卡自己證明這些偏離是噪音——排除區是縮池慣例非預測，
    excludedHits 追蹤就是裁決台。
    """
    if not records:
        return {}
    return pick_engine.gen_pending_core(GAME, records)


def build_log_entries(new_sorted, base_pending, base_picklog, all_records, st_mg):
    """結算新開獎（回傳新到舊）。第1期用 BASE_PENDING（事前預測）；
    其後各期用該期之前的歷史重算預測補結算（out-of-sample，標記 backfill）。"""
    logged = {e.get('period') for e in base_picklog}
    entries = []
    for idx, d in enumerate(new_sorted):
        if d['p'] in logged:
            continue
        if idx == 0 and base_pending and base_pending.get('strategies'):
            strat, ts, backfill = base_pending['strategies'], base_pending.get('ts', 0), False
            meta = {k: base_pending[k] for k in ('v', 'algo', 'seed', 'hi', 'exclAlgo') if k in base_pending}
            if base_pending.get('relaxed'):
                meta['relaxed'] = base_pending['relaxed']
            excl = base_pending.get('excluded')
        else:
            hist = [r for r in all_records if r['p'] < d['p']]
            if len(hist) < 40:
                continue
            core = gen_pending(hist)
            strat, ts, backfill = core.get('strategies'), int(time.time() * 1000), True
            meta = {k: core[k] for k in ('v', 'algo', 'seed', 'hi', 'exclAlgo') if k in core}
            if core.get('relaxed'):
                meta['relaxed'] = core['relaxed']
            excl = core.get('excluded')
        if not strat:
            continue
        hit_nums = {g: sorted(set(nums) & set(d['n'])) for g, nums in strat.items()}
        hits = {g: len(m) for g, m in hit_nums.items()}
        entry = {
            'period':     d['p'],
            'strategies': strat,
            'result':     sorted(d['n']),
            'hits':       hits,
            'hitNums':    hit_nums,
            'ts':         ts,
        }
        entry.update(meta)
        if excl:
            entry['excluded'] = excl
            entry['excludedHits'] = len(set(excl) & set(d['n']))
        if backfill:
            entry['backfill'] = True
        entries.append(entry)
        tag = '補結算' if backfill else '命中紀錄'
        print(f"→ {tag} {d['p']}：" + ', '.join(f"{k}:{v}" for k, v in hits.items()))
    return list(reversed(entries))


# ── 讀取 BASE_ST mg ────────────────────────────────────────────
def read_base_st(html: str) -> dict:
    m = re.search(r"const BASE_ST = \{(.*?)\};", html, re.DOTALL)
    if not m: return {}
    return {int(e.group(1)): int(e.group(2))
            for e in re.finditer(r"(\d+):\{mg:(\d+)", m.group(1))}


# ── 通用：替換 JS 常數 ─────────────────────────────────────────
def replace_js_const(html: str, name: str, new_val: str, comment: str = "") -> str:
    marker = f"const {name} = "
    idx = html.find(marker)
    if idx == -1: return html
    val_start = idx + len(marker)
    pos, depth, in_str, escape = val_start, 0, False, False
    while pos < len(html):
        c = html[pos]
        if escape: escape = False
        elif in_str:
            if c == '\\': escape = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c in '{[': depth += 1
            elif c in '}]': depth -= 1
            elif c == ';' and depth == 0: break
        pos += 1
    end = pos + 1
    while end < len(html) and html[end] != '\n': end += 1
    return html[:idx] + marker + new_val + ";" + (f" {comment}" if comment else "") + html[end:]


# ── Pick 狀態 ─────────────────────────────────────────────────
def _extract_js_value(html: str, name: str):
    marker = f"const {name} = "
    idx = html.find(marker)
    if idx == -1: return None
    vs = idx + len(marker)
    if html[vs:vs+4] == 'null': return None
    pos, depth, in_str, escape = vs, 0, False, False
    while pos < len(html):
        c = html[pos]
        if escape: escape = False
        elif in_str:
            if c == '\\': escape = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c in '{[': depth += 1
            elif c in '}]':
                depth -= 1
                if depth == 0: pos += 1; break
        pos += 1
    try: return json.loads(html[vs:pos])
    except: return None

def read_pick_state(html):
    return _extract_js_value(html, 'BASE_PICKLOG') or [], _extract_js_value(html, 'BASE_PENDING')

def write_pick_state(html, picklog, pending):
    html = replace_js_const(html, 'BASE_PICKLOG',
                             json.dumps(picklog, ensure_ascii=False, separators=(',',':')))
    if pending is None:
        html = replace_js_const(html, 'BASE_PENDING', 'null',
                                 '// {strategies:{G1:[...],...}, ts:N}')
    else:
        html = replace_js_const(html, 'BASE_PENDING',
                                 json.dumps(pending, ensure_ascii=False, separators=(',',':')))
    return html


# ── 更新 marksix.html ─────────────────────────────────────────
def update_html(new_draws: list, dry_run: bool = False,
                force_repick: bool = False):
    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)

    actually_new = sorted([d for d in new_draws if d['p'] > current_latest],
                           key=lambda x: x['p'], reverse=True)
    if not actually_new:
        print(f"✅ 已是最新（{actually_new[0]['draw'] if actually_new else current_latest}），無需更新")
        return

    print("新增：" + "、".join(
        f"{d['draw']}({d['dt']})({','.join(f'{n:02d}' for n in d['n'])},特{d['e']:02d})"
        for d in actually_new))

    st_mg = read_base_st(html)
    base_picklog, base_pending = read_pick_state(html)

    # ── 解析現有 BASE_REC ──────────────────────────────────────
    rec_match = re.search(r"(const BASE_REC = \[)(.*?)(\n\];?)", html, re.DOTALL)
    if not rec_match:
        print("❌ 無法解析 BASE_REC"); return

    existing_js = rec_match.group(2)
    cleaned = existing_js.strip().rstrip(",").strip()
    existing_json = "[" + re.sub(r'\b([a-zA-Z][a-zA-Z0-9]*)\b:', r'"\1":', cleaned) + "]"
    try:
        existing = json.loads(existing_json)
    except json.JSONDecodeError as e:
        print(f"❌ BASE_REC 解析失敗：{e}"); return

    all_records = actually_new + existing
    total = len(all_records)
    oldest_draw = all_records[-1].get('draw', str(all_records[-1]['p']))
    newest_draw = all_records[0].get('draw', str(all_records[0]['p']))
    newest_dt   = all_records[0].get('dt', '')

    # ── 計算命中（第1期用 BASE_PENDING，其後各期補結算）─────────
    new_log_entries = build_log_entries(
        sorted(actually_new, key=lambda x: x['p']),
        base_pending, base_picklog, all_records, st_mg)

    # ── 重建 BASE_REC ──────────────────────────────────────────
    rec_lines = []
    for i in range(0, len(all_records), 4):
        chunk  = all_records[i:i+4]
        parts  = [f'{{p:{r["p"]},draw:"{r.get("draw","")}",dt:"{r.get("dt","")}",n:[{",".join(str(n) for n in r["n"])}],e:{r.get("e",0)}}}'
                  for r in chunk]
        suffix = "," if i + 4 < len(all_records) else ""
        rec_lines.append("  " + ",".join(parts) + suffix)
    new_base_rec = "const BASE_REC = [\n" + "\n".join(rec_lines) + "\n];"
    html = html[:rec_match.start()] + new_base_rec + html[rec_match.end():]

    # ── 更新 ab 值 ─────────────────────────────────────────────
    ab = calc_absent(all_records)
    for n in range(1, 50):
        html = re.sub(rf'(\b{n}:{{[^}}]*?\bab:)\d+', rf'\g<1>{ab[n]}', html)

    # ── 更新注釋 ───────────────────────────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    html = re.sub(r"// ── BASE DATA（.*?）──",
        f"// ── BASE DATA（{oldest_draw}–{newest_draw}，共{total}期，{newest_dt}，更新 {today}）──", html)

    # ── 產生新預測 ─────────────────────────────────────────────
    core = gen_pending(all_records)
    # ── 演算法改版閘門（2026-08-16）────────────────────────────
    # BASE_PENDING 一經發布即是「事前註冊」的預測。演算法改版時，
    # 若該期尚未開獎（forPeriod 未變），不得回頭抽換已發布的號碼，
    # 否則「事後不可改」就只是一句口號。新版待本期結算後自然生效。
    # 註：現行流程下 update_html 只在抓到新開獎時才執行，forPeriod 必然
    #     前進一期，故本閘門平時不會觸發。它擋的是補抓歷史、重複抓到
    #     同一期，以及日後若有人把 pending 改成「每次執行都重算」的情形。
    if (base_pending and not force_repick
            and base_pending.get('forPeriod') == core.get('forPeriod')
            and base_pending.get('algo') != core.get('algo')):
        print(f"→ 演算法已改版（{base_pending.get('algo')} → {core.get('algo')}），"
              f"但第 {core.get('forPeriod')} 期預測早已發布，保留原號碼不抽換；"
              f"新版自下期開獎後生效。（要立即換版：--force-repick）")
        core = dict(base_pending)
    new_strategies = core.get('strategies', {})
    new_pending = {
        **core,           # sfg-v2 已含 excluded / exclDepths / exclAlgo
        'ts': core.get('ts') or int(time.time() * 1000),
    }
    html = write_pick_state(html, new_log_entries + base_picklog, new_pending)

    if new_strategies:
        print("→ 下期預測：" + ' | '.join(
            f"{k}:[{','.join(f'{n:02d}' for n in v)}]" for k,v in new_strategies.items()))

    if dry_run:
        print(f"\n[Dry Run] 將更新至 {newest_draw}（{newest_dt}），共{total}期，不寫入")
        return

    DATA_FILE.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → {newest_draw}（{newest_dt}），共 {total} 期（{today}）")

    # ── Git commit + push ─────────────────────────────────────
    repo = DATA_FILE.parent
    new_info = "、".join(
        f"{d['draw']}({d['dt']})[{','.join(f'{n:02d}' for n in d['n'])},特{d['e']:02d}]"
        for d in actually_new)
    try:
        # HOOK: 未來如需「開獎當晚即時本機通知中2+」，在此檢查
        #   max((e.get('hits') or {}).values() or [0]) >= 2 for e in new_log_entries
        #   後 osascript 通知；目前推播統一由隔日 10:13 lottery-daily 單一出口發（2026-08-09 拍板）
        subprocess.run(["git", "add", "data_m6.js"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", f"六合彩 {new_info}"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=repo, check=True, capture_output=True)
        print("→ 已推上 GitHub（約1分鐘後生效）")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git 推送失敗（{e}）")


# ── 主程式 ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="自動抓取香港六合彩最新開獎")
    parser.add_argument("--dry", action="store_true", help="只顯示，不寫入")
    parser.add_argument("--force-repick", action="store_true",
                        help="演算法改版時，強制重算「尚未開獎」那期的預測"
                             "（預設保留已發布號碼，見改版閘門）")
    args = parser.parse_args()

    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)
    print(f"目前最新：{current_latest}（{current_latest//1000:02d}/{current_latest%1000:03d}）")
    print("抓取中...")

    latest_dt = read_latest_dt(html)
    draws = fetch_draws(current_latest, latest_dt)
    if not draws:
        print("✅ 無新資料（今日可能尚未開獎，或已是最新）")
        if latest_dt:
            gap_days = (date.today() - latest_dt).days
            if gap_days >= 4:
                draw_str = f"{current_latest//1000:02d}/{current_latest%1000:03d}"
                msg = f"六合彩更新可能失敗！停在{draw_str}（{gap_days}天前），請手動檢查。"
                subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "⚠️ 彩券更新警告" sound name "Basso"'], capture_output=True)
                print(f"⚠️ 資料已 {gap_days} 天未更新，已發送 macOS 通知")
        return

    update_html(draws, dry_run=args.dry, force_repick=args.force_repick)


if __name__ == "__main__":
    main()
