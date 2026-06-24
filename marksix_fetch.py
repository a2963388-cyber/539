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

INDEX_HTML = Path(__file__).parent / "marksix.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}
BASE_URL = "https://en.lottolyzer.com/history/hong-kong/mark-six/page/{}/per-page/50/summary-view"


def draw_str_to_p(draw_str: str) -> int:
    """'26/067' → 26067"""
    parts = draw_str.split('/')
    return int(parts[0]) * 1000 + int(parts[1])


def read_current_latest(html: str) -> int:
    m = re.search(r"const BASE_REC = \[\s*\{p:(\d+)", html)
    return int(m.group(1)) if m else 0


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

def ensure_consec(nums, cand, score_fn, annual):
    if annual['consecRate'] < 50: return nums
    nums_set = set(nums)
    if any(n+1 in nums_set for n in nums): return nums
    cand_set = set(cand)
    for to_out in sorted(nums, key=score_fn):
        others = [n for n in nums if n != to_out]
        adj = {nb for n in others for nb in [n-1,n+1]
               if 1<=nb<=49 and nb not in nums_set and nb in cand_set}
        if adj:
            return sorted(others + [max(adj, key=score_fn)])
    return nums

def _build_dual(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    s3max   = max((ann_score(n, annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    def dual_fn(n):
        return (ann_score(n, annual)/s3max)*60 + (mom_fn(n)/mom_max)*40
    return dual_fn, mom_fn

def gen_g1(cand, annual):
    return sorted(sorted(cand, key=lambda n: ann_score(n, annual), reverse=True)[:6])

def gen_g2(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    return sorted(sorted(cand, key=lambda n: mom_fn(n), reverse=True)[:6])

def gen_g3(cand, records, annual):
    dual_fn, _ = _build_dual(cand, records, annual)
    by_z = {zn: sorted([n for n in cand if z_zone(n)==zn], key=dual_fn, reverse=True) for zn in [1,2,3,4]}
    pool = by_z[1][:2] + by_z[2][:2] + by_z[3][:2] + by_z[4][:2]
    pool.sort(key=dual_fn, reverse=True)
    return ensure_consec(sorted(pool[:6]), cand, dual_fn, annual)

def gen_g4(cand, records, annual):
    _, _, mom_fn = build_mom(records, annual)
    cold_thresh = int(annual['periods'] * 6/49 * 0.9)
    picks = sorted([n for n in cand if annual['freq'][n]<=cold_thresh and mom_fn(n)>=1.1], key=mom_fn, reverse=True)
    if len(picks) < 6:
        picks += sorted([n for n in cand if mom_fn(n)>=1.0 and n not in picks], key=mom_fn, reverse=True)
    if len(picks) < 6:
        picks = sorted(cand, key=mom_fn, reverse=True)
    return sorted(picks[:6])

def gen_g5(cand, records, annual):
    dual_fn, _ = _build_dual(cand, records, annual)
    hot_tails = [t for t,b in annual['tailBias'].items() if b>=8]
    eff_hot = hot_tails if hot_tails else [1,5,6,8]
    hot_pool  = sorted([n for n in cand if n%10 in eff_hot], key=dual_fn, reverse=True)
    cold_pool = sorted([n for n in cand if n%10 not in eff_hot], key=dual_fn, reverse=True)
    hot_picks = hot_pool[:min(5, len(hot_pool))]
    rest = [n for n in cold_pool if n not in set(hot_picks)][:6-len(hot_picks)]
    return sorted((hot_picks+rest)[:6])

def gen_g6(cand, records, annual):
    _, mom_fn = _build_dual(cand, records, annual)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    must  = [annual['hotNum']] if annual['hotNum'] in cand else []
    pool  = [n for n in cand if n not in must]
    scored = sorted(pool, key=lambda n: ann_score(n,annual)*0.6+(mom_fn(n)/mom_max)*100*0.4, reverse=True)
    return sorted(must + scored[:6-len(must)])

def gen_g8(cand, records, annual):
    rN = min(30, len(records))
    rf = [0]*50
    for r in records[:rN]:
        for n in r['n']: rf[n]+=1
    ann_per = annual['periods']
    def mom_fn(n):
        e = annual['freq'][n]/ann_per
        return 0 if e<0.001 else (rf[n]/rN)/e
    s3max   = max((ann_score(n,annual) for n in cand), default=0.01)
    mom_max = max((mom_fn(n) for n in cand), default=0.01)
    def dual_fn(n): return (ann_score(n,annual)/s3max)*60+(mom_fn(n)/mom_max)*40
    top6 = sorted(cand, key=dual_fn, reverse=True)[:6]
    if len(top6)<6: return None
    return ensure_consec(sorted(top6), cand, dual_fn, annual)

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
    return sorted(scored[:6])

def gen_all_predictions(records, st_mg):
    annual = build_annual(records)
    if not annual: return {}
    ab   = calc_absent(records)
    cand = [n for n in range(1,50) if ab[n]<st_mg.get(n,999)] or list(range(1,50))
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
    if g8: strategies['G8'] = g8
    return strategies


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
    html = INDEX_HTML.read_text(encoding="utf-8")
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

    # ── 命中計算 ───────────────────────────────────────────────
    new_log_entries = []
    if base_pending and base_pending.get('strategies'):
        oldest_new = sorted(actually_new, key=lambda x: x['p'])[0]
        logged = {e.get('period') for e in base_picklog}
        if oldest_new['p'] not in logged:
            hits = {gname: len(set(gnums) & set(oldest_new['n']))
                    for gname, gnums in base_pending['strategies'].items()}
            new_log_entries.append({
                'period':     oldest_new['p'],
                'strategies': base_pending['strategies'],
                'result':     sorted(oldest_new['n']),
                'hits':       hits,
                'ts':         base_pending.get('ts', 0),
            })
            print(f"→ 命中紀錄 {oldest_new['draw']}：" +
                  ', '.join(f"{k}:{v}" for k,v in hits.items()))

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

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → {newest_draw}（{newest_dt}），共 {total} 期（{today}）")

    # ── Git commit + push ─────────────────────────────────────
    repo = INDEX_HTML.parent
    new_info = "、".join(
        f"{d['draw']}({d['dt']})[{','.join(f'{n:02d}' for n in d['n'])},特{d['e']:02d}]"
        for d in actually_new)
    try:
        subprocess.run(["git", "add", "marksix.html"], cwd=repo, check=True)
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

    html = INDEX_HTML.read_text(encoding="utf-8")
    current_latest = read_current_latest(html)
    print(f"目前最新：{current_latest}（{current_latest//1000:02d}/{current_latest%1000:03d}）")
    print("抓取中...")

    draws = fetch_draws(current_latest)
    if not draws:
        print("✅ 無新資料（今日可能尚未開獎，或已是最新）")
        return

    update_html(draws, dry_run=args.dry)


if __name__ == "__main__":
    main()
