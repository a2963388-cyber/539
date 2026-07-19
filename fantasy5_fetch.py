#!/usr/bin/env python3
"""
fantasy5_fetch.py — 自動抓取 CA Fantasy 5 最新開獎，更新 fantasy5.html

用法：
  python3 fantasy5_fetch.py          # 抓取並更新
  python3 fantasy5_fetch.py --dry    # 只顯示，不寫入

依賴：pip3 install requests beautifulsoup4
"""

import re
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("❌ 請先安裝：pip3 install requests")
    sys.exit(1)

DATA_FILE = Path(__file__).parent / "data_f5.js"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# 已知錨點：Draw 11916 = 2026-06-22（每天開獎，包含週日）
ANCHOR_DRAW = 11916
ANCHOR_DATE = date(2026, 6, 22)

BASE_URL = "https://en.lottolyzer.com/history/united-states/fantasy-5-california/page/{}/per-page/50/summary-view"

# 每組策略出號數（2026-07-12 由 5 擴至 8，各策略選號邏輯不變）
PICK_N = 8


# ── Draw# ↔ 日期換算 ──────────────────────────────────────────
def draw_to_date(draw: int) -> date:
    return ANCHOR_DATE + timedelta(days=draw - ANCHOR_DRAW)

def date_to_draw(d: date) -> int:
    return ANCHOR_DRAW + (d - ANCHOR_DATE).days


# ── 讀取 fantasy5.html 最新 draw# ────────────────────────────
def read_current_latest(html: str) -> int:
    m = re.search(r"const BASE_REC = \[\s*\{p:(\d+)", html)
    return int(m.group(1)) if m else 0


# ── 抓取 lottolyzer.com 開獎資料 ─────────────────────────────
def fetch_draws(from_draw: int) -> list:
    """
    從 lottolyzer.com 抓取 Fantasy 5 最新開獎。
    回傳 [{p:draw#, dt:date_str, n:[5 nums]}, ...] 最新在前。
    """
    results = []
    page = 1
    max_pages = 3

    while page <= max_pages:
        url = BASE_URL.format(page)
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"❌ 抓取失敗（page {page}）：{e}")
            break

        html = r.text
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        page_draws = []
        found_old = False

        for row in rows:
            tds = [re.sub(r'<[^>]+>', '', t).strip()
                   for t in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
            if len(tds) >= 3 and tds[0].isdigit() and re.match(r'20\d\d-\d\d-\d\d', tds[1] if len(tds) > 1 else ''):
                draw_num = int(tds[0])
                draw_date = tds[1]
                nums = [int(x) for x in tds[2].split(',')
                        if x.strip().isdigit() and 1 <= int(x) <= 39]
                if draw_num <= from_draw:
                    found_old = True
                    continue
                if len(nums) == 5:
                    page_draws.append({'p': draw_num, 'dt': draw_date, 'n': sorted(nums)})

        results.extend(page_draws)
        if found_old or not page_draws:
            break
        page += 1
        time.sleep(0.5)

    if results:
        print(f"✅ 找到 {len(results)} 筆新資料")
    return sorted(results, key=lambda x: x['p'], reverse=True)


# ── 計算各號碼沉寂期數 ────────────────────────────────────────
def calc_absent(records: list) -> dict:
    ab = {}
    for n in range(1, 40):
        count = 0
        for r in records:
            if n in r['n']:
                break
            count += 1
        ab[n] = count
    return ab


# ── 預測邏輯（完全與 539_fetch.py 相同）──────────────────────
def z_zone(n: int) -> int:
    if n <= 9: return 1
    if n <= 19: return 2
    if n <= 29: return 3
    return 4

def build_annual(records: list) -> dict:
    T = len(records)
    if not T:
        return None
    first_p = records[-1]['p']
    last_p  = records[0]['p']
    freq = [0] * 40
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
        for n in r['n']:
            zp[z_zone(n) - 1] += 1
        pat = '-'.join(str(x) for x in zp)
        pat_cnt[pat] = pat_cnt.get(pat, 0) + 1

    total_balls = T * 5
    zone_pct = {zn: round(zone_cnt[zn] / total_balls * 100, 1) for zn in [1, 2, 3, 4]}
    tail_bias = {}
    for t in range(10):
        exp = T * 5 * 3 / 39 if t == 0 else T * 5 * 4 / 39
        tail_bias[t] = round((tail_cnt[t] / exp - 1) * 100, 1)

    consec_rate  = round(consec_count / T * 100, 1)
    avg_sum      = round(sum_total / T, 1)
    hot_num      = max(range(1, 40), key=lambda n: freq[n])
    ann_max      = max(freq[1:])
    tail_bias_max = max((v for v in tail_bias.values() if v > 0), default=1)

    return {
        'periods': T, 'firstP': first_p, 'lastP': last_p,
        'freq': freq, 'tailBias': tail_bias, 'zonePct': zone_pct,
        'consecRate': consec_rate, 'avgSum': avg_sum, 'hotNum': hot_num,
        'annMax': ann_max, 'tailBiasMax': tail_bias_max,
    }

def ann_score(n: int, annual: dict) -> float:
    tb = max(0, annual['tailBias'].get(n % 10, 0))
    return (annual['freq'][n] / annual['annMax']) * 70 + tb / annual['tailBiasMax'] * 30

def build_mom(records: list, annual: dict):
    rN = min(30, len(records))
    rf = [0] * 40
    for r in records[:rN]:
        for n in r['n']:
            rf[n] += 1
    ann_per = annual['periods']
    def mom_fn(n):
        e = annual['freq'][n] / ann_per
        return 0 if e < 0.001 else (rf[n] / rN) / e
    return rN, rf, mom_fn

def _build_dual(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    s3max   = max((ann_score(n, annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    def dual_fn(n):
        return (ann_score(n, annual) / s3max) * 60 + (mom_fn(n) / mom_max) * 40
    return dual_fn, mom_fn

def gen_g2(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    return sorted(sorted(cand, key=lambda n: mom_fn(n), reverse=True)[:PICK_N])

def gen_g4(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    cold_thresh = int(annual['periods'] * 5 / 39 * 0.9)
    picks = sorted([n for n in cand if annual['freq'][n] <= cold_thresh and mom_fn(n) >= 1.1],
                   key=mom_fn, reverse=True)
    if len(picks) < PICK_N:
        extra = sorted([n for n in cand if mom_fn(n) >= 1.0 and n not in picks],
                       key=mom_fn, reverse=True)
        picks = picks + extra
    if len(picks) < PICK_N:
        picks = sorted(cand, key=mom_fn, reverse=True)
    return sorted(picks[:PICK_N])

def tail_chi2(annual, pick, pool):
    """尾數分佈 vs 均勻的卡方統計量（df=9），由 tailBias 反推"""
    T = annual['periods']
    zero_cnt = 3 if pool == 39 else 4
    per_tail = 4 if pool == 39 else 5
    chi2 = 0.0
    for t, b in annual['tailBias'].items():
        exp = T * pick * (zero_cnt if int(t) == 0 else per_tail) / pool
        chi2 += exp * (b / 100.0) ** 2
    return chi2

def gen_g5(cand, records, annual):
    dual_fn, _ = _build_dual(cand, records, annual)
    # 卡方把關（df=9, α=.05 臨界值16.92）：尾數分佈與均勻無顯著差異時不啟用熱尾強制
    hot_tails = ([t for t, b in annual['tailBias'].items() if b >= 8]
                 if tail_chi2(annual, 5, 39) >= 16.92 else [])
    if not hot_tails:
        return sorted(sorted(cand, key=dual_fn, reverse=True)[:PICK_N])
    hot_pool  = sorted([n for n in cand if n % 10 in hot_tails], key=dual_fn, reverse=True)
    cold_pool = sorted([n for n in cand if n % 10 not in hot_tails], key=dual_fn, reverse=True)
    hot_picks = hot_pool[:min(PICK_N - 2, len(hot_pool))]
    rest = [n for n in cold_pool if n not in set(hot_picks)][:PICK_N - len(hot_picks)]
    return sorted((hot_picks + rest)[:PICK_N])

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
    pool = [n for n in range(1, 40) if ab[n] in top3] or list(range(1, 40))
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
    """每號碼的歷史平均回歸間隔（無紀錄者用理論值 39/5）"""
    tot, cnt, last = {}, {}, {}
    for i, r in enumerate(reversed(records)):
        for n in r['n']:
            if n in last:
                tot[n] = tot.get(n, 0) + (i - last[n] - 1)
                cnt[n] = cnt.get(n, 0) + 1
            last[n] = i
    return {n: (tot.get(n, 0) / cnt[n] if cnt.get(n) else 39 / 5) for n in range(1, 40)}

def gen_g10(records, annual):
    """G10 使用者策略：回歸熱區（間隔占比>11%）主力 + 2碼超期（沉寂≥2×個別平均間隔）"""
    dist = build_return_dist(records)
    total = sum(dist.values()) or 1
    hot_gaps = {g for g, c in dist.items() if c / total > 0.11}
    ab = calc_absent(records)
    ag = avg_gap_per_num(records)
    dual_fn, _ = _build_dual(list(range(1, 40)), records, annual)
    pool_a = sorted([n for n in range(1, 40) if ab[n] in hot_gaps], key=dual_fn, reverse=True)
    pool_b = sorted([n for n in range(1, 40) if ab[n] >= 2 * ag[n]], key=dual_fn, reverse=True)
    picks = pool_a[:PICK_N - 2]
    for src_pool in (pool_b, pool_a[PICK_N - 2:], sorted(range(1, 40), key=dual_fn, reverse=True)):
        for n in src_pool:
            if len(picks) >= PICK_N:
                break
            if n not in picks:
                picks.append(n)
    return sorted(picks[:PICK_N])

def unpop_score(n):
    """冷門度（0~100）：避開大眾熱門簽法——生日範圍(1~31)、月份(1~12)、
    幸運號(3,6,7,8,9,18,28,38)；尾4少人簽反而加分"""
    s = 40.0
    if n >= 32: s += 35
    if n > 12:  s += 15
    if n % 10 == 4: s += 10
    if n in (3, 6, 7, 8, 9, 18, 28, 38): s -= 25
    return s

def gen_g11(records, annual):
    """G11 冷門組合（2026-07-15 上線）：dual 分數與冷門度各半加權。
    誠實揭露：不改變命中機率；目標是避開熱門簽法降低撞號，中獎時
    分彩金稀釋較少（唯一能改善條件賠付的方向）。保底至少3碼≥32"""
    pool = list(range(1, 40))
    dual_fn, _ = _build_dual(pool, records, annual)
    dmax = max(dual_fn(n) for n in pool) or 0.01
    umax = max(unpop_score(n) for n in pool)
    score = lambda n: (dual_fn(n) / dmax) * 50 + (unpop_score(n) / umax) * 50
    picks = sorted(pool, key=score, reverse=True)[:PICK_N]
    high = [n for n in picks if n >= 32]
    if len(high) < 3:
        subs = sorted([n for n in pool if n >= 32 and n not in picks], key=score, reverse=True)
        lows = sorted([n for n in picks if n < 32], key=score)
        for c in subs[:3 - len(high)]:
            picks.remove(lows.pop(0))
            picks.append(c)
    return sorted(picks)

def gen_gc(strategies):
    """GC 覆蓋度立柱（2026-07-19 事前註冊）：統計各號碼被多少現役策略
    （不含 G0 隨機對照）圈選，覆蓋度高→低取前 10 碼，同票取小號。
    10 碼基準：均中期望 1.282 碼/期、中≥3星 9.6%；碼數與 8 碼策略不同，
    滿 50 期評估時只與自身隨機基準比較，不與 8 碼策略直接比。
    誠實揭露：各策略共用同一批歷史資料，共識≠獨立證據，期望值不變。"""
    cov = {}
    for g, nums in strategies.items():
        if g == 'G0':
            continue
        for n in nums:
            cov[n] = cov.get(n, 0) + 1
    return sorted(sorted(cov), key=lambda n: -cov[n])[:10]

def gen_all_predictions(records, st_mg):
    annual = build_annual(records)
    if not annual:
        return {}
    ab   = calc_absent(records)
    cand = [n for n in range(1, 40) if ab[n] < st_mg.get(n, 999)] or list(range(1, 40))
    # ── 策略淘汰規則（2026-07-15 事前註冊，禁止事後改動）──────────
    # 1. 新策略上線後累積滿 50 期才可評估；屆時「平均命中 < G0 且
    #    中2+次數 ≤ G0」→ 移除
    # 2. dual 分數家族滿 50 期檢查兩兩平均重疊碼數 > 6/8 → 合併留均中較高者
    # 3. G0 隨機對照組永久保留，不參與淘汰
    # G1/G3/G6/G7/G8 已於 2026-07-02 依 130 期滾動回測移除（均中低於隨機期望 0.641）
    strategies = {
        'G2': gen_g2(cand, records, annual),
        'G4': gen_g4(cand, records, annual),
        'G5': gen_g5(cand, records, annual),
        'G9': gen_g9(records, annual),
    }
    strategies['G10'] = gen_g10(records, annual)
    strategies['G11'] = gen_g11(records, annual)
    # G0 隨機對照組：以最新期號為種子，作為所有策略的空白對照
    strategies['G0'] = lcg_picks(records[0]['p'], 39, PICK_N)
    # GC 覆蓋度立柱：由現役策略投票產生（排 G0），輸出即立柱順序（高→低）
    strategies['GC'] = gen_gc(strategies)
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


# ── 讀取 BASE_ST 的 mg 值 ─────────────────────────────────────
def read_base_st(html: str) -> dict:
    m = re.search(r"const BASE_ST = \{(.*?)\};", html, re.DOTALL)
    if not m:
        return {}
    st_mg = {}
    for entry in re.finditer(r"(\d+):\{mg:(\d+)", m.group(1)):
        st_mg[int(entry.group(1))] = int(entry.group(2))
    return st_mg


# ── 通用：替換 JS 常數值 ──────────────────────────────────────
def replace_js_const(html: str, name: str, new_val: str, comment: str = "") -> str:
    marker = f"const {name} = "
    idx = html.find(marker)
    if idx == -1:
        return html
    val_start = idx + len(marker)
    pos = val_start
    depth = 0
    in_str = False
    escape = False
    while pos < len(html):
        c = html[pos]
        if escape:
            escape = False
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
    while end < len(html) and html[end] != '\n':
        end += 1
    suffix = f" {comment}" if comment else ""
    return html[:idx] + marker + new_val + ";" + suffix + html[end:]


# ── 讀取 / 寫入 pick 狀態 ─────────────────────────────────────
def _extract_js_value(html: str, name: str):
    marker = f"const {name} = "
    idx = html.find(marker)
    if idx == -1:
        return None
    val_start = idx + len(marker)
    if html[val_start:val_start+4] == 'null':
        return None
    pos = val_start
    depth = 0
    in_str = False
    escape = False
    while pos < len(html):
        c = html[pos]
        if escape:
            escape = False
        elif in_str:
            if c == '\\': escape = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c in '{[': depth += 1
            elif c in '}]':
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
        pos += 1
    try:
        return json.loads(html[val_start:pos])
    except Exception:
        return None

def read_pick_state(html: str):
    return _extract_js_value(html, 'BASE_PICKLOG') or [], _extract_js_value(html, 'BASE_PENDING')

def write_pick_state(html: str, picklog: list, pending) -> str:
    pl_val = json.dumps(picklog, ensure_ascii=False, separators=(',', ':'))
    html = replace_js_const(html, 'BASE_PICKLOG', pl_val)
    if pending is None:
        html = replace_js_const(html, 'BASE_PENDING', 'null',
                                 '// {strategies:{G1:[...],...}, forPeriod:N, ts:N}')
    else:
        html = replace_js_const(html, 'BASE_PENDING',
                                 json.dumps(pending, ensure_ascii=False, separators=(',', ':')))
    return html


# ── 更新 fantasy5.html ────────────────────────────────────────
def update_html(new_draws: list, dry_run: bool = False):
    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)

    actually_new = sorted(
        [d for d in new_draws if d['p'] > current_latest],
        key=lambda x: x['p'], reverse=True
    )

    if not actually_new:
        print(f"✅ 已是最新（Draw {current_latest}），無需更新")
        return

    print("新增：" + "、".join(
        f"Draw{d['p']}({d['dt']})({','.join(str(n).zfill(2) for n in d['n'])})"
        for d in actually_new
    ))

    # ── 讀取 pick 狀態 ─────────────────────────────────────────
    st_mg = read_base_st(html)
    base_picklog, base_pending = read_pick_state(html)

    # ── 解析現有 BASE_REC ──────────────────────────────────────
    rec_match = re.search(r"(const BASE_REC = \[)(.*?)(\n\];?)", html, re.DOTALL)
    if not rec_match:
        print("❌ 無法解析 BASE_REC")
        return

    existing_js = rec_match.group(2)
    cleaned = existing_js.strip().rstrip(",").strip()
    # Convert JS object notation to JSON (p→"p", dt→"dt", n→"n")
    existing_json = "[" + re.sub(r'\b([a-z][a-zA-Z]*)\b:', r'"\1":', cleaned) + "]"
    try:
        existing = json.loads(existing_json)
    except json.JSONDecodeError as e:
        print(f"❌ BASE_REC 解析失敗：{e}")
        return

    all_records = actually_new + existing
    total  = len(all_records)
    oldest = all_records[-1]["p"]
    newest = all_records[0]["p"]
    newest_dt = all_records[0].get("dt", "")

    # ── 計算命中（第1期用 BASE_PENDING，其後各期補結算）─────────
    new_log_entries = build_log_entries(
        sorted(actually_new, key=lambda x: x['p']),
        base_pending, base_picklog, all_records, st_mg)

    # ── 重建 BASE_REC ──────────────────────────────────────────
    rec_lines = []
    for i in range(0, len(all_records), 5):
        chunk  = all_records[i:i+5]
        parts  = [f'{{p:{r["p"]},dt:"{r.get("dt","")}",n:[{",".join(str(n) for n in r["n"])}]}}' for r in chunk]
        suffix = "," if i + 5 < len(all_records) else ""
        rec_lines.append("  " + ",".join(parts) + suffix)
    new_base_rec = "const BASE_REC = [\n" + "\n".join(rec_lines) + "\n];"
    html = html[:rec_match.start()] + new_base_rec + html[rec_match.end():]

    # ── 更新 ab 值 ─────────────────────────────────────────────
    ab = calc_absent(all_records)
    for n in range(1, 40):
        html = re.sub(
            rf'(\b{n}:{{[^}}]*?\bab:)\d+',
            rf'\g<1>{ab[n]}',
            html
        )

    # ── 更新頂部注釋 ────────────────────────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    html = re.sub(
        r"// ── BASE DATA（.*?）──",
        f"// ── BASE DATA（{oldest}–{newest}，共{total}期，{newest_dt}，更新 {today}）──",
        html,
    )

    # ── 產生新預測 ─────────────────────────────────────────────
    new_strategies = gen_all_predictions(all_records, st_mg)
    new_pending = {'strategies': new_strategies, 'ts': int(time.time() * 1000)}

    # ── 更新 pick 狀態 ─────────────────────────────────────────
    html = write_pick_state(html, new_log_entries + base_picklog, new_pending)

    if new_strategies:
        print("→ 下期預測：" + ' | '.join(
            f"{k}:[{','.join(f'{n:02d}' for n in v)}]" for k, v in new_strategies.items()
        ))

    if dry_run:
        print(f"\n[Dry Run] 將更新至 Draw {newest}（{newest_dt}），共 {total} 期，不寫入")
        return

    DATA_FILE.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → Draw {newest}（{newest_dt}），共 {total} 期（{today}）")

    # ── Git commit + push ─────────────────────────────────────
    repo = DATA_FILE.parent
    new_info = ", ".join(
        f"Draw{d['p']}({d['dt']})({','.join(f'{n:02d}' for n in d['n'])})"
        for d in actually_new
    )
    msg = f"F5 新增 {new_info}"
    try:
        subprocess.run(["git", "add", "data_f5.js"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=repo, check=True, capture_output=True)
        print("→ 已推上 GitHub（約1分鐘後生效）")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git 推送失敗（{e}）")


# ── 主程式 ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="自動抓取 CA Fantasy 5 最新開獎")
    parser.add_argument("--dry", action="store_true", help="只顯示，不寫入")
    args = parser.parse_args()

    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)
    latest_date = draw_to_date(current_latest)
    print(f"目前最新：Draw {current_latest}（{latest_date}）")
    print("抓取中...")

    draws = fetch_draws(current_latest)
    if not draws:
        print("✅ 無新資料（今日可能尚未開獎，或已是最新）")
        gap_days = (date.today() - latest_date).days
        if gap_days >= 2:
            msg = f"Fantasy5更新可能失敗！停在Draw{current_latest}（{gap_days}天前），請手動檢查。"
            subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "⚠️ 彩券更新警告" sound name "Basso"'], capture_output=True)
            print(f"⚠️ 資料已 {gap_days} 天未更新，已發送 macOS 通知")
        return

    update_html(draws, dry_run=args.dry)


if __name__ == "__main__":
    main()
