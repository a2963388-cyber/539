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

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import pick_engine  # 4×3 選號引擎（sfg-v1，2026-08-09）
GAME = 'f5'

DATA_FILE = Path(__file__).parent / "data_f5.js"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# 已知錨點：Draw 11916 = 2026-06-22（每天開獎，包含週日）
ANCHOR_DRAW = 11916
ANCHOR_DATE = date(2026, 6, 22)

BASE_URL = "https://en.lottolyzer.com/history/united-states/fantasy-5-california/page/{}/per-page/50/summary-view"



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

def unpop_score(n):
    """冷門度（0~100）：避開大眾熱門簽法——生日範圍(1~31)、月份(1~12)、
    幸運號(3,6,7,8,9,18,28,38)；尾4少人簽反而加分"""
    s = 40.0
    if n >= 32: s += 35
    if n > 12:  s += 15
    if n % 10 == 4: s += 10
    if n in (3, 6, 7, 8, 9, 18, 28, 38): s -= 25
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
    core = gen_pending(all_records)
    new_strategies = core.get('strategies', {})
    new_pending = {
        **core,           # sfg-v2 已含 excluded / exclDepths / exclAlgo
        'ts': int(time.time() * 1000),
    }

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
        # HOOK: 未來如需「開獎當晚即時本機通知中2+」，在此檢查
        #   max((e.get('hits') or {}).values() or [0]) >= 2 for e in new_log_entries
        #   後 osascript 通知；目前推播統一由隔日 10:13 lottery-daily 單一出口發（2026-08-09 拍板）
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
