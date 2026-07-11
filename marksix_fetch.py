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

DATA_FILE = Path(__file__).parent / "data_m6.js"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
BASE_URL = "https://en.lottolyzer.com/history/hong-kong/mark-six/page/{}/per-page/50/summary-view"

# 每組策略出號數（2026-07-12 由 6 擴至 8，各策略選號邏輯不變）
PICK_N = 8


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


def fetch_draws(from_p: int) -> list:
    results = []
    for page in range(1, 4):
        url = BASE_URL.format(page)
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"❌ 抓取失敗（page {page}）：{e}")
            break

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL)
        page_draws = []
        found_old = False

        for row in rows:
            tds = [re.sub(r'<[^>]+>', '', t).strip()
                   for t in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
            if (len(tds) >= 3 and re.match(r'\d\d/\d+', tds[0])
                    and re.match(r'20\d\d-\d\d-\d\d', tds[1] if len(tds) > 1 else '')):
                p = draw_str_to_p(tds[0])
                if p <= from_p:
                    found_old = True
                    continue
                nums = [int(x) for x in tds[2].split(',')
                        if x.strip().isdigit() and 1 <= int(x) <= 49]
                extra = int(tds[3]) if len(tds) > 3 and tds[3].strip().isdigit() else 0
                if len(nums) == 6:
                    page_draws.append({'p': p, 'draw': tds[0], 'dt': tds[1],
                                       'n': sorted(nums), 'e': extra})

        results.extend(page_draws)
        if found_old or not page_draws:
            break
        time.sleep(0.5)

    if results:
        print(f"✅ 找到 {len(results)} 筆新資料")
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


# ── 預測邏輯（1-49，選6）─────────────────────────────────────
def z_zone(n: int) -> int:
    if n <= 12: return 1
    if n <= 24: return 2
    if n <= 36: return 3
    return 4

def build_annual(records: list) -> dict:
    T = len(records)
    if not T: return None
    first_p, last_p = records[-1]['p'], records[0]['p']
    freq = [0] * 50
    zone_cnt = {1:0, 2:0, 3:0, 4:0}
    tail_cnt = [0] * 10
    consec_count = 0
    sum_total = 0
    pat_cnt = {}

    for r in records:
        for n in r['n']:
            freq[n] += 1
            zone_cnt[z_zone(n)] += 1
            tail_cnt[n % 10] += 1
        s = sorted(r['n'])
        for i in range(len(s) - 1):
            if s[i+1] == s[i] + 1:
                consec_count += 1
                break
        sum_total += sum(r['n'])
        zp = [0, 0, 0, 0]
        for n in r['n']: zp[z_zone(n) - 1] += 1
        pat = '-'.join(str(x) for x in zp)
        pat_cnt[pat] = pat_cnt.get(pat, 0) + 1

    total_balls = T * 6
    zone_pct = {zn: round(zone_cnt[zn] / total_balls * 100, 1) for zn in [1,2,3,4]}
    tail_bias = {}
    for t in range(10):
        exp = T * 6 * 4 / 49 if t == 0 else T * 6 * 5 / 49
        tail_bias[t] = round((tail_cnt[t] / exp - 1) * 100, 1)

    consec_rate  = round(consec_count / T * 100, 1)
    avg_sum      = round(sum_total / T, 1)
    hot_num      = max(range(1, 50), key=lambda n: freq[n])
    ann_max      = max(freq[1:])
    tail_bias_max = max((v for v in tail_bias.values() if v > 0), default=1)

    return {'periods': T, 'firstP': first_p, 'lastP': last_p,
            'freq': freq, 'tailBias': tail_bias, 'zonePct': zone_pct,
            'consecRate': consec_rate, 'avgSum': avg_sum, 'hotNum': hot_num,
            'annMax': ann_max, 'tailBiasMax': tail_bias_max}

def ann_score(n, annual):
    tb = max(0, annual['tailBias'].get(n % 10, 0))
    return (annual['freq'][n] / annual['annMax']) * 70 + tb / annual['tailBiasMax'] * 30

def build_mom(records, annual):
    rN = min(30, len(records))
    rf = [0] * 50
    for r in records[:rN]:
        for n in r['n']: rf[n] += 1
    ann_per = annual['periods']
    def mom_fn(n):
        e = annual['freq'][n] / ann_per
        return 0 if e < 0.001 else (rf[n] / rN) / e
    return rN, rf, mom_fn

def build_pair_stat(records):
    pairs = {}
    for r in records:
        s = sorted(r['n'])
        for i in range(len(s)-1):
            for j in range(i+1, len(s)):
                k = f"{s[i]}-{s[j]}"
                pairs[k] = pairs.get(k, 0) + 1
    return pairs

def _build_dual(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    s3max   = max((ann_score(n, annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    def dual_fn(n):
        return (ann_score(n, annual)/s3max)*60 + (mom_fn(n)/mom_max)*40
    return dual_fn, mom_fn

def gen_g2(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    return sorted(sorted(cand, key=lambda n: mom_fn(n), reverse=True)[:PICK_N])

def gen_g4(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    cold_thresh = int(annual['periods'] * 6/49 * 0.9)
    picks = sorted([n for n in cand if annual['freq'][n]<=cold_thresh and mom_fn(n)>=1.1], key=mom_fn, reverse=True)
    if len(picks) < PICK_N:
        picks += sorted([n for n in cand if mom_fn(n)>=1.0 and n not in picks], key=mom_fn, reverse=True)
    if len(picks) < PICK_N:
        picks = sorted(cand, key=mom_fn, reverse=True)
    return sorted(picks[:PICK_N])

def gen_g6(cand, records, annual):
    _, mom_fn = _build_dual(cand, records, annual)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    must  = [annual['hotNum']] if annual['hotNum'] in cand else []
    pool  = [n for n in cand if n not in must]
    scored = sorted(pool, key=lambda n: ann_score(n,annual)*0.6+(mom_fn(n)/mom_max)*100*0.4, reverse=True)
    return sorted(must + scored[:PICK_N-len(must)])

def predict_g7(records, st_mg, annual):
    ab   = calc_absent(records)
    cand = [n for n in range(1,50) if ab[n]<st_mg.get(n,999)] or list(range(1,50))
    s3max = max((ann_score(n,annual) for n in cand), default=0.01)
    rN = min(30, len(records))
    rf = [0]*50
    for r in records[:rN]:
        for n in r['n']: rf[n]+=1
    ann_per = annual['periods']
    def s4fn(n):
        e=annual['freq'][n]/ann_per
        return 0 if e<0.001 else (rf[n]/rN)/e
    s4max = max((s4fn(n) for n in cand), default=0.01)
    prelim = sorted(cand, key=lambda n: ann_score(n,annual)/s3max*60+s4fn(n)/s4max*40, reverse=True)
    friend_pool = prelim[:15]
    pairs = build_pair_stat(records)
    def pair_score(n):
        s=0
        for m in friend_pool:
            if m==n: continue
            k='-'.join(str(x) for x in sorted([n,m]))
            s+=pairs.get(k,0)
        return s
    pair_max = max((pair_score(n) for n in cand), default=1) or 1
    scored = sorted(cand,
        key=lambda n: ann_score(n,annual)/s3max*55+s4fn(n)/s4max*35+pair_score(n)/pair_max*10,
        reverse=True)
    return sorted(scored[:PICK_N])

def build_return_dist(records):
    """全體號碼回歸間隔分佈（records 新到舊）。間隔0=下期就回歸"""
    dist, last_seen = {}, {}
    for i, r in enumerate(reversed(records)):
        for n in r['n']:
            if n in last_seen:
                gap = i - last_seen[n] - 1
                dist[gap] = dist.get(gap, 0) + 1
            last_seen[n] = i
    return dist

def gen_g9(records, annual):
    """G9 回歸熱區：沉寂期數落在歷史回歸排名前3間隔的號碼，dual 分數取前 PICK_N"""
    dist = build_return_dist(records)
    top3 = [g for g, _ in sorted(dist.items(), key=lambda x: -x[1])[:3]]
    ab = calc_absent(records)
    pool = [n for n in range(1, 50) if ab[n] in top3] or list(range(1, 50))
    dual_fn, _ = _build_dual(pool, records, annual)
    return sorted(sorted(pool, key=dual_fn, reverse=True)[:PICK_N])

def lcg_picks(seed, num_max, k):
    """Lehmer LCG 選號，與網頁 JS 版 lcgPicks 完全一致（G0 隨機對照組用）"""
    x = seed % 2147483646 + 1
    picks = set()
    while len(picks) < k:
        x = (x * 48271) % 2147483647
        picks.add(1 + x % num_max)
    return sorted(picks)

def avg_gap_per_num(records):
    """每號碼的歷史平均回歸間隔（無紀錄者用理論值 49/6）"""
    tot, cnt, last = {}, {}, {}
    for i, r in enumerate(reversed(records)):
        for n in r['n']:
            if n in last:
                tot[n] = tot.get(n, 0) + (i - last[n] - 1)
                cnt[n] = cnt.get(n, 0) + 1
            last[n] = i
    return {n: (tot.get(n, 0) / cnt[n] if cnt.get(n) else 49 / 6) for n in range(1, 50)}

def gen_g10(records, annual):
    """G10 使用者策略：回歸熱區（間隔占比>11%）主力 + 2碼超期（沉寂≥2×個別平均間隔）"""
    dist = build_return_dist(records)
    total = sum(dist.values()) or 1
    hot_gaps = {g for g, c in dist.items() if c / total > 0.11}
    ab = calc_absent(records)
    ag = avg_gap_per_num(records)
    dual_fn, _ = _build_dual(list(range(1, 50)), records, annual)
    pool_a = sorted([n for n in range(1, 50) if ab[n] in hot_gaps], key=dual_fn, reverse=True)
    pool_b = sorted([n for n in range(1, 50) if ab[n] >= 2 * ag[n]], key=dual_fn, reverse=True)
    picks = pool_a[:PICK_N - 2]
    for src_pool in (pool_b, pool_a[PICK_N - 2:], sorted(range(1, 50), key=dual_fn, reverse=True)):
        for n in src_pool:
            if len(picks) >= PICK_N:
                break
            if n not in picks:
                picks.append(n)
    return sorted(picks[:PICK_N])

def gen_all_predictions(records, st_mg):
    annual = build_annual(records)
    if not annual: return {}
    ab   = calc_absent(records)
    cand = [n for n in range(1,50) if ab[n]<st_mg.get(n,999)] or list(range(1,50))
    # G1 已於 2026-07-02 依 180 期滾動回測移除（均中 0.694 低於隨機期望 0.735）
    # G3/G5/G8 已於 2026-07-07 依 240 期滾動回測移除：與 G7 同屬 dual 分數家族，
    # 兩兩重疊 5.0-5.9/6 碼（G5×G8 達 5.91），均中 0.779 皆低於 G7 的 0.796，留 G7 代表
    strategies = {
        'G2': gen_g2(cand, records, annual),
        'G4': gen_g4(cand, records, annual),
        'G6': gen_g6(cand, records, annual),
        'G7': predict_g7(records, st_mg, annual),
    }
    strategies['G9'] = gen_g9(records, annual)
    strategies['G10'] = gen_g10(records, annual)
    # G0 隨機對照組：以最新期號為種子，作為所有策略的空白對照
    strategies['G0'] = lcg_picks(records[0]['p'], 49, PICK_N)
    return strategies


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
        else:
            hist = [r for r in all_records if r['p'] < d['p']]
            if len(hist) < 40:
                continue
            strat, ts, backfill = gen_all_predictions(hist, st_mg), int(time.time() * 1000), True
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
def update_html(new_draws: list, dry_run: bool = False):
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
    new_strategies = gen_all_predictions(all_records, st_mg)
    new_pending = {'strategies': new_strategies, 'ts': int(time.time() * 1000)}
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
    args = parser.parse_args()

    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)
    print(f"目前最新：{current_latest}（{current_latest//1000:02d}/{current_latest%1000:03d}）")
    print("抓取中...")

    draws = fetch_draws(current_latest)
    if not draws:
        print("✅ 無新資料（今日可能尚未開獎，或已是最新）")
        latest_dt = read_latest_dt(html)
        if latest_dt:
            gap_days = (date.today() - latest_dt).days
            if gap_days >= 4:
                draw_str = f"{current_latest//1000:02d}/{current_latest%1000:03d}"
                msg = f"六合彩更新可能失敗！停在{draw_str}（{gap_days}天前），請手動檢查。"
                subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "⚠️ 彩券更新警告" sound name "Basso"'], capture_output=True)
                print(f"⚠️ 資料已 {gap_days} 天未更新，已發送 macOS 通知")
        return

    update_html(draws, dry_run=args.dry)


if __name__ == "__main__":
    main()
