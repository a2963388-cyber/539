#!/usr/bin/env python3
"""
539_fetch.py — 自動抓取今彩539最新開獎，更新 index.html

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

INDEX_HTML = Path(__file__).parent / "index.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

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


# ── 抓取 pilio.idv.tw 開獎資料 ───────────────────────────────
def fetch_draws(from_period: int) -> list:
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ 抓取失敗：{e}")
        return []

    html = r.text
    pattern = r'date-cell[^>]*>(\d{2}/\d{2})<br>\d+(.*?number-cell.*?)([\d,\s&nbsp;]+)</td>'
    rows = re.findall(pattern, html, re.DOTALL)

    draws = []
    current_year = ANCHOR_DATE.year

    for date_str, _, nums_raw in rows:
        month, day = map(int, date_str.split("/"))
        d = date(current_year, month, day)
        period = date_to_period(d)
        if period <= from_period:
            continue
        nums = [int(x) for x in re.findall(r"\d{1,2}", nums_raw) if 1 <= int(x) <= 39]
        if len(nums) == 5:
            draws.append({"p": period, "n": sorted(nums)})

    if draws:
        print(f"✅ 找到 {len(draws)} 筆新資料")
    return sorted(draws, key=lambda x: x["p"], reverse=True)


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

def build_pair_stat(records: list) -> dict:
    pairs = {}
    for r in records:
        s = sorted(r['n'])
        for i in range(len(s) - 1):
            for j in range(i + 1, len(s)):
                k = f"{s[i]}-{s[j]}"
                pairs[k] = pairs.get(k, 0) + 1
    return pairs

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

def gen_g2(cand: list, records: list, annual: dict) -> list:
    _, _, mom_fn = build_mom(records, annual)
    return sorted(sorted(cand, key=lambda n: mom_fn(n), reverse=True)[:5])

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

def gen_g4(cand: list, records: list, annual: dict) -> list:
    _, _, mom_fn = build_mom(records, annual)
    cold_thresh = int(annual['periods'] * 5 / 39 * 0.9)
    picks = sorted(
        [n for n in cand if annual['freq'][n] <= cold_thresh and mom_fn(n) >= 1.1],
        key=mom_fn, reverse=True
    )
    if len(picks) < 5:
        extra = sorted(
            [n for n in cand if mom_fn(n) >= 1.0 and n not in picks],
            key=mom_fn, reverse=True
        )
        picks = picks + extra
    if len(picks) < 5:
        picks = sorted(cand, key=mom_fn, reverse=True)
    return sorted(picks[:5])

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

def predict_g7(records: list, st_mg: dict, annual: dict) -> list:
    ab    = calc_absent(records)
    cand  = [n for n in range(1, 40) if ab[n] < st_mg.get(n, 999)] or list(range(1, 40))
    s3max = max((ann_score(n, annual) for n in cand), default=0.01)
    rN = min(30, len(records))
    rf = [0] * 40
    for r in records[:rN]:
        for n in r['n']:
            rf[n] += 1
    ann_per = annual['periods']
    def s4fn(n):
        e = annual['freq'][n] / ann_per
        return 0 if e < 0.001 else (rf[n] / rN) / e
    s4max = max((s4fn(n) for n in cand), default=0.01)

    prelim = sorted(cand, key=lambda n: ann_score(n, annual)/s3max*60 + s4fn(n)/s4max*40, reverse=True)
    friend_pool = prelim[:15]
    pairs = build_pair_stat(records)
    def pair_score(n):
        s = 0
        for m in friend_pool:
            if m == n: continue
            k = '-'.join(str(x) for x in sorted([n, m]))
            s += pairs.get(k, 0)
        return s
    pair_max = max((pair_score(n) for n in cand), default=1) or 1

    scored = sorted(cand, key=lambda n: ann_score(n, annual)/s3max*55 + s4fn(n)/s4max*35 + pair_score(n)/pair_max*10, reverse=True)
    return sorted(scored[:5])

def gen_all_predictions(records: list, st_mg: dict) -> dict:
    annual = build_annual(records)
    if not annual:
        return {}
    ab   = calc_absent(records)
    cand = [n for n in range(1, 40) if ab[n] < st_mg.get(n, 999)] or list(range(1, 40))

    strategies = {
        'G1': gen_g1(cand, annual),
        'G2': gen_g2(cand, records, annual),
        'G3': gen_g3(cand, records, annual),
        'G4': gen_g4(cand, records, annual),
        'G5': gen_g5(cand, records, annual),
        'G6': gen_g6(cand, records, annual),
        'G7': predict_g7(records, st_mg, annual),
    }
    g8 = gen_g8(cand, records, annual)
    if g8:
        strategies['G8'] = g8
    return strategies


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


# ── 更新 index.html ───────────────────────────────────────────
def update_html(new_draws: list, dry_run: bool = False):
    html = INDEX_HTML.read_text(encoding="utf-8")
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

    # ── 計算命中（BASE_PENDING 對照最舊的新期）──────────────────
    new_log_entries = []
    if base_pending and base_pending.get('strategies'):
        oldest_new = sorted(actually_new, key=lambda x: x['p'])[0]
        logged_periods = {e.get('period') for e in base_picklog}
        if oldest_new['p'] not in logged_periods:
            hit_nums = {}
            hits = {}
            for gname, gnums in base_pending['strategies'].items():
                matched = sorted(set(gnums) & set(oldest_new['n']))
                hit_nums[gname] = matched
                hits[gname] = len(matched)
            new_log_entries.append({
                'period':     oldest_new['p'],
                'strategies': base_pending['strategies'],
                'result':     sorted(oldest_new['n']),
                'hits':       hits,
                'hitNums':    hit_nums,
                'ts':         base_pending.get('ts', 0),
            })
            hit_str = ', '.join(f"{k}:{v}" for k, v in hits.items())
            print(f"→ 命中紀錄 第{oldest_new['p']}期：{hit_str}")

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

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → 第 {newest} 期，共 {total} 期（{today}）")
    print("→ 沉寂期數 ab 已重新計算")

    # ── Git commit + push ──────────────────────────────────────
    repo = INDEX_HTML.parent
    new_periods = ", ".join(
        f"{d['p']}期({'，'.join(f'{n:02d}' for n in d['n'])})"
        for d in actually_new
    )
    msg = f"新增 {new_periods}"
    try:
        subprocess.run(["git", "add", "index.html"], cwd=repo, check=True)
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

    html = INDEX_HTML.read_text(encoding="utf-8")
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
