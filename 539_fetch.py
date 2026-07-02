#!/usr/bin/env python3
"""
539_fetch.py — 自動抓取今彩539最新開獎，更新 data_539.js

資料源：台灣彩券官方 API（主）→ pilio.idv.tw（備援）

用法：
  python3 539_fetch.py          # 抓取並更新
  python3 539_fetch.py --dry    # 只顯示，不寫入

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
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ 請先安裝：pip3 install requests beautifulsoup4")
    sys.exit(1)

DATA_FILE = Path(__file__).parent / "data_539.js"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
API_URL = "https://api.taiwanlottery.com/TLCAPIWEB/Lottery/Daily539Result"

# 已知錨點：第 115149 期 = 2026-06-19
ANCHOR_PERIOD = 115149
ANCHOR_DATE   = date(2026, 6, 19)


# ── 日期 <-> 期號換算 ─────────────────────────────────────────
def is_draw_day(d: date) -> bool:
    return d.weekday() != 6  # 6 = Sunday

def draw_days_between(start: date, end: date) -> int:
    if start == end:
        return 0
    step = 1 if end > start else -1
    count = 0
    d = start + timedelta(days=step)
    while True:
        if is_draw_day(d):
            count += step
        if d == end:
            break
        d += timedelta(days=step)
    return count

def date_to_period(d: date) -> int:
    diff = draw_days_between(ANCHOR_DATE, d)
    return ANCHOR_PERIOD + diff

def period_to_date(period: int) -> date:
    diff = period - ANCHOR_PERIOD
    if diff == 0:
        return ANCHOR_DATE
    step = 1 if diff > 0 else -1
    d = ANCHOR_DATE
    remaining = abs(diff)
    while remaining > 0:
        d += timedelta(days=step)
        if is_draw_day(d):
            remaining -= 1
    return d


# ── 讀取 index.html 最新期號 ──────────────────────────────────
def read_current_latest(html: str) -> int:
    m = re.search(r"const BASE_REC = \[\s*\{p:(\d+)", html)
    return int(m.group(1)) if m else 0


# ── 抓取開獎資料：台灣彩券官方 API（主源）────────────────────
def official_to_period(op: int) -> int:
    """官方期號 115000160 → 內部期號 115160（民國年115 × 1000 + 當年期序160）"""
    return (op // 1000000) * 1000 + op % 1000

def fetch_draws_api(from_period: int) -> list:
    """從官方 API 抓新開獎，期號直接取自官方（不靠日期推算），必要時回溯前幾個月補漏"""
    draws = []
    covered = False   # 是否已看到 from_period（含）以前的期數 → 代表銜接無缺漏
    d = date.today().replace(day=1)
    for _ in range(3):
        url = f"{API_URL}?period&month={d.year}-{d.month:02d}"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        items = (r.json().get("content") or {}).get("daily539Res") or []
        for it in items:
            p = official_to_period(it["period"])
            if p <= from_period:
                covered = True
                continue
            nums = sorted(it["drawNumberSize"])
            if len(nums) != 5 or not all(1 <= n <= 39 for n in nums):
                print(f"⚠️ 期號 {p} 號碼異常，跳過：{nums}")
                continue
            draws.append({"p": p, "n": nums})
        if covered:
            break
        d = (d - timedelta(days=1)).replace(day=1)

    draws.sort(key=lambda x: x["p"], reverse=True)
    if draws and not covered:
        # 同年度期號應與現有資料連號；跨年（前綴不同）無法檢查
        oldest_new = draws[-1]["p"]
        if oldest_new // 1000 == from_period // 1000 and oldest_new != from_period + 1:
            msg = f"期號不連續：現有最新{from_period}，抓到最舊{oldest_new}，中間缺漏，已中止寫入"
            print(f"❌ {msg}")
            subprocess.run(['osascript', '-e',
                f'display notification "{msg}" with title "⚠️ 彩券更新警告" sound name "Basso"'],
                capture_output=True)
            return []
    if draws:
        print(f"✅ 官方 API 找到 {len(draws)} 筆新資料")
    return draws


# ── 抓取開獎資料：pilio.idv.tw（備援）────────────────────────
def fetch_draws_pilio(from_period: int) -> list:
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    html = r.text
    # date-cell 格式：07/02<br>26(四) → 26 = 西元 2026 年縮寫
    pattern = r'date-cell[^>]*>(\d{2})/(\d{2})<br>(\d{2})\((.*?number-cell.*?)([\d,\s&nbsp;]+)</td>'
    rows = re.findall(pattern, html, re.DOTALL)

    draws = []
    for month, day, yy, _, nums_raw in rows:
        d = date(2000 + int(yy), int(month), int(day))
        period = date_to_period(d)
        if period <= from_period:
            continue
        nums = [int(x) for x in re.findall(r"\d{1,2}", nums_raw) if 1 <= int(x) <= 39]
        if len(nums) == 5:
            draws.append({"p": period, "n": sorted(nums)})

    if draws:
        print(f"✅ pilio 備援找到 {len(draws)} 筆新資料（期號由日期推算，請留意停開日）")
    return sorted(draws, key=lambda x: x["p"], reverse=True)


def fetch_draws(from_period: int) -> list:
    try:
        return fetch_draws_api(from_period)
    except Exception as e:
        print(f"⚠️ 官方 API 失敗（{e}），改用 pilio 備援")
    try:
        return fetch_draws_pilio(from_period)
    except Exception as e:
        print(f"❌ 抓取失敗：{e}")
        return []


# ── 計算各號碼沉寂期數 ────────────────────────────────────────
def calc_absent(records: list) -> dict:
    ab = {}
    for n in range(1, 40):
        count = 0
        for r in records:
            if n in r["n"]:
                break
            count += 1
        ab[n] = count
    return ab


# ── 預測邏輯（JS G1–G8 + G7 的 Python 移植版）────────────────
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

def ensure_consec(nums: list, cand: list, score_fn, annual: dict) -> list:
    if annual['consecRate'] < 50:
        return nums
    nums_set = set(nums)
    if any(n + 1 in nums_set for n in nums):
        return nums
    cand_set = set(cand)
    by_score = sorted(nums, key=score_fn)
    for to_out in by_score:
        others = [n for n in nums if n != to_out]
        adj = set()
        for n in others:
            for nb in [n - 1, n + 1]:
                if 1 <= nb <= 39 and nb not in nums_set and nb in cand_set:
                    adj.add(nb)
        if adj:
            best = max(adj, key=score_fn)
            return sorted(others + [best])
    return nums

def _build_dual(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    s3max  = max((ann_score(n, annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    def dual_fn(n):
        return (ann_score(n, annual) / s3max) * 60 + (mom_fn(n) / mom_max) * 40
    return dual_fn, mom_fn

def gen_g1(cand: list, annual: dict) -> list:
    return sorted(sorted(cand, key=lambda n: ann_score(n, annual), reverse=True)[:5])

def gen_g3(cand: list, records: list, annual: dict) -> list:
    dual_fn, _ = _build_dual(cand, records, annual)
    by_z = {}
    for zn in [1, 2, 3, 4]:
        by_z[zn] = sorted([n for n in cand if z_zone(n) == zn], key=dual_fn, reverse=True)
    pool = by_z[1][:2] + by_z[2][:2] + by_z[3][:2]
    if len(pool) < 5:
        seen = set(pool)
        for n in by_z[4]:
            if n not in seen:
                pool.append(n)
                seen.add(n)
    pool.sort(key=dual_fn, reverse=True)
    nums = sorted(pool[:5])
    return ensure_consec(nums, cand, dual_fn, annual)

def gen_g5(cand: list, records: list, annual: dict) -> list:
    dual_fn, _ = _build_dual(cand, records, annual)
    hot_tails = [t for t, b in annual['tailBias'].items() if b >= 8]
    effective_hot = hot_tails if hot_tails else [1, 5, 6, 8]
    hot_pool  = sorted([n for n in cand if n % 10 in effective_hot], key=dual_fn, reverse=True)
    cold_pool = sorted([n for n in cand if n % 10 not in effective_hot], key=dual_fn, reverse=True)
    hot_picks = hot_pool[:min(4, len(hot_pool))]
    hot_set   = set(hot_picks)
    rest = [n for n in cold_pool if n not in hot_set][:5 - len(hot_picks)]
    return sorted((hot_picks + rest)[:5])

def gen_g6(cand: list, records: list, annual: dict) -> list:
    _, mom_fn = _build_dual(cand, records, annual)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    hot_num = annual['hotNum']
    must  = [hot_num] if hot_num in cand else []
    pool  = [n for n in cand if n not in must]
    scored = sorted(pool, key=lambda n: ann_score(n, annual) * 0.6 + (mom_fn(n) / mom_max) * 100 * 0.4, reverse=True)
    return sorted(must + scored[:5 - len(must)])

def gen_g8(cand: list, records: list, annual: dict) -> list:
    rN = min(30, len(records))
    rf = [0] * 40
    for r in records[:rN]:
        for n in r['n']:
            rf[n] += 1
    ann_per = annual['periods']
    def mom_fn(n):
        e = annual['freq'][n] / ann_per
        return 0 if e < 0.001 else (rf[n] / rN) / e
    s3max   = max((ann_score(n, annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n)            for n in cand), default=0.01)
    def dual_fn(n):
        return (ann_score(n, annual) / s3max) * 60 + (mom_fn(n) / mom_max) * 40
    top5raw = sorted(cand, key=dual_fn, reverse=True)[:5]
    if len(top5raw) < 5:
        return None
    return ensure_consec(sorted(top5raw), cand, dual_fn, annual)

def build_return_dist(records: list) -> dict:
    """全體號碼回歸間隔分佈（records 新到舊）。間隔0=下期就回歸"""
    dist, last_seen = {}, {}
    for i, r in enumerate(reversed(records)):
        for n in r['n']:
            if n in last_seen:
                gap = i - last_seen[n] - 1
                dist[gap] = dist.get(gap, 0) + 1
            last_seen[n] = i
    return dist

def gen_g9(records: list, annual: dict) -> list:
    """G9 回歸熱區：沉寂期數落在歷史回歸排名前3間隔的號碼，dual 分數取前5"""
    dist = build_return_dist(records)
    top3 = [g for g, _ in sorted(dist.items(), key=lambda x: -x[1])[:3]]
    ab = calc_absent(records)
    pool = [n for n in range(1, 40) if ab[n] in top3] or list(range(1, 40))
    dual_fn, _ = _build_dual(pool, records, annual)
    return sorted(sorted(pool, key=dual_fn, reverse=True)[:5])

def lcg_picks(seed: int, num_max: int, k: int) -> list:
    """Lehmer LCG 選號，與網頁 JS 版 lcgPicks 完全一致（G0 隨機對照組用）"""
    x = seed % 2147483646 + 1
    picks = set()
    while len(picks) < k:
        x = (x * 48271) % 2147483647
        picks.add(1 + x % num_max)
    return sorted(picks)

def gen_all_predictions(records: list, st_mg: dict) -> dict:
    annual = build_annual(records)
    if not annual:
        return {}
    ab   = calc_absent(records)
    cand = [n for n in range(1, 40) if ab[n] < st_mg.get(n, 999)] or list(range(1, 40))

    # G2/G4/G7 已於 2026-07-02 依 100 期滾動回測移除（均中低於隨機期望 0.641）
    strategies = {
        'G1': gen_g1(cand, annual),
        'G3': gen_g3(cand, records, annual),
        'G5': gen_g5(cand, records, annual),
        'G6': gen_g6(cand, records, annual),
    }
    g8 = gen_g8(cand, records, annual)
    if g8:
        strategies['G8'] = g8
    strategies['G9'] = gen_g9(records, annual)
    # G0 隨機對照組：以最新期號為種子，作為所有策略的空白對照
    strategies['G0'] = lcg_picks(records[0]['p'], 39, 5)
    return strategies


def build_log_entries(new_sorted: list, base_pending, base_picklog: list,
                      all_records: list, st_mg: dict) -> list:
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
        print(f"→ {tag} 第{d['p']}期：" + ', '.join(f"{k}:{v}" for k, v in hits.items()))
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


# ── 通用：替換 JS 常數值（能處理巢狀括號與字串）─────────────────
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
            if c == '\\':
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c in '{[':
                depth += 1
            elif c in '}]':
                depth -= 1
            elif c == ';' and depth == 0:
                break
        pos += 1
    # Skip rest of original line (removes old inline comments)
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
    picklog = _extract_js_value(html, 'BASE_PICKLOG') or []
    pending = _extract_js_value(html, 'BASE_PENDING')
    return picklog, pending

def write_pick_state(html: str, picklog: list, pending) -> str:
    pl_val = json.dumps(picklog, ensure_ascii=False, separators=(',', ':'))
    html = replace_js_const(html, 'BASE_PICKLOG', pl_val)
    if pending is None:
        html = replace_js_const(html, 'BASE_PENDING', 'null',
                                 '// {strategies:{G1:[...],...}, forPeriod:N, ts:N}')
    else:
        pd_val = json.dumps(pending, ensure_ascii=False, separators=(',', ':'))
        html = replace_js_const(html, 'BASE_PENDING', pd_val)
    return html


# ── 更新 data_539.js ───────────────────────────────────────────
def update_html(new_draws: list, dry_run: bool = False):
    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)

    actually_new = sorted(
        [d for d in new_draws if d["p"] > current_latest],
        key=lambda x: x["p"], reverse=True
    )

    if not actually_new:
        print(f"✅ 已是最新（第 {current_latest} 期），無需更新")
        return

    print("新增：" + "、".join(
        f"{d['p']}期({','.join(str(n).zfill(2) for n in d['n'])})"
        for d in actually_new
    ))

    # ── 讀取目前 pick 狀態 ──────────────────────────────────────
    st_mg = read_base_st(html)
    base_picklog, base_pending = read_pick_state(html)

    # ── 解析現有 BASE_REC ───────────────────────────────────────
    rec_match = re.search(r"(const BASE_REC = \[)(.*?)(\n\];?)", html, re.DOTALL)
    if not rec_match:
        print("❌ 無法解析 BASE_REC")
        return

    existing_js = rec_match.group(2)
    cleaned = existing_js.strip().rstrip(",").strip()
    existing_json = "[" + re.sub(r"(\b[a-z]\w*\b):", r'"\1":', cleaned) + "]"
    try:
        existing = json.loads(existing_json)
    except json.JSONDecodeError as e:
        print(f"❌ BASE_REC 解析失敗：{e}")
        return

    all_records = actually_new + existing
    total  = len(all_records)
    oldest = all_records[-1]["p"]
    newest = all_records[0]["p"]

    # ── 計算命中（第1期用 BASE_PENDING，其後各期補結算）─────────
    new_log_entries = build_log_entries(
        sorted(actually_new, key=lambda x: x['p']),
        base_pending, base_picklog, all_records, st_mg)

    # ── 重建 BASE_REC（5 筆一行）────────────────────────────────
    rec_lines = []
    for i in range(0, len(all_records), 5):
        chunk  = all_records[i:i+5]
        parts  = [f"{{p:{r['p']},n:[{','.join(str(n) for n in r['n'])}]}}" for r in chunk]
        suffix = "," if i + 5 < len(all_records) else ""
        rec_lines.append("  " + ",".join(parts) + suffix)
    new_base_rec = "const BASE_REC = [\n" + "\n".join(rec_lines) + "\n];"
    html = html[:rec_match.start()] + new_base_rec + html[rec_match.end():]

    # ── 更新 ab 值 ──────────────────────────────────────────────
    ab = calc_absent(all_records)
    for n in range(1, 40):
        html = re.sub(
            rf'(\b{n}:{{[^}}]*?\bab:)\d+',
            rf'\g<1>{ab[n]}',
            html
        )

    # ── 更新頂部注釋 ─────────────────────────────────────────────
    today = date.today().strftime("%Y-%m-%d")
    html = re.sub(
        r"// ── BASE DATA（.*?）──",
        f"// ── BASE DATA（{oldest}–{newest}，共{total}期，對應遺漏統計表 {today}）──",
        html,
    )

    # ── 產生新預測 ───────────────────────────────────────────────
    new_strategies = gen_all_predictions(all_records, st_mg)
    new_pending = {
        'strategies': new_strategies,
        'ts': int(time.time() * 1000),
    }

    # ── 更新 pick 狀態 ───────────────────────────────────────────
    updated_picklog = new_log_entries + base_picklog
    html = write_pick_state(html, updated_picklog, new_pending)

    if new_strategies:
        preview = {k: v for k, v in new_strategies.items()}
        print(f"→ 已產生下期預測：" + ' | '.join(
            f"{k}:[{','.join(f'{n:02d}' for n in v)}]"
            for k, v in preview.items()
        ))

    if dry_run:
        print(f"\n[Dry Run] 將更新至第 {newest} 期，共 {total} 期，不寫入")
        return

    DATA_FILE.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → 第 {newest} 期，共 {total} 期（{today}）")
    print("→ 沉寂期數 ab 已重新計算")

    # ── Git commit + push ──────────────────────────────────────
    repo = DATA_FILE.parent
    new_periods = ", ".join(
        f"{d['p']}期({'，'.join(f'{n:02d}' for n in d['n'])})"
        for d in actually_new
    )
    msg = f"新增 {new_periods}"
    try:
        subprocess.run(["git", "add", "data_539.js"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=repo, check=True, capture_output=True)
        print(f"→ 已推上 GitHub（約1分鐘後手機頁面生效）")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git 推送失敗，請手動 push（{e}）")


# ── 主程式 ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="自動抓取今彩539最新開獎")
    parser.add_argument("--dry", action="store_true", help="只顯示，不寫入")
    args = parser.parse_args()

    html = DATA_FILE.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)
    latest_date = period_to_date(current_latest)
    print(f"目前最新：第 {current_latest} 期（{latest_date}）")
    print("抓取中...")

    draws = fetch_draws(current_latest)
    if not draws:
        print("✅ 無新資料（今日可能尚未開獎，或已是最新）")
        gap_days = (date.today() - latest_date).days
        if gap_days >= 2:
            msg = f"今彩539更新可能失敗！停在第{current_latest}期（{gap_days}天前），請手動檢查。"
            subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "⚠️ 彩券更新警告" sound name "Basso"'], capture_output=True)
            print(f"⚠️ 資料已 {gap_days} 天未更新，已發送 macOS 通知")
        return

    update_html(draws, dry_run=args.dry)


if __name__ == "__main__":
    main()
