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

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import pick_engine  # 4×3 選號引擎（sfg-v1，2026-08-09）
GAME = '539'

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
        # pageSize=50：API 預設每頁僅回 10 筆，停機多天時會漏抓月中期數
        url = f"{API_URL}?period&month={d.year}-{d.month:02d}&pageNum=1&pageSize=50"
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


def tail_chi2(annual: dict, pick: int, pool: int) -> float:
    """尾數分佈 vs 均勻的卡方統計量（df=9），由 tailBias 反推"""
    T = annual['periods']
    zero_cnt = 3 if pool == 39 else 4   # 尾0的號碼個數（39池:10,20,30；49池:+40）
    per_tail = 4 if pool == 39 else 5
    chi2 = 0.0
    for t, b in annual['tailBias'].items():
        exp = T * pick * (zero_cnt if int(t) == 0 else per_tail) / pool
        chi2 += exp * (b / 100.0) ** 2
    return chi2

def unpop_score(n: int) -> float:
    """冷門度（0~100）：避開大眾熱門簽法——生日範圍(1~31)、月份(1~12)、
    華人幸運號(3,6,8,9,18,28,38)與西方幸運7；尾4因忌諱少人簽反而加分"""
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
def update_html(new_draws: list, dry_run: bool = False,
                force_repick: bool = False):
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
        # HOOK: 未來如需「開獎當晚即時本機通知中2+」，在此檢查
        #   max((e.get('hits') or {}).values() or [0]) >= 2 for e in new_log_entries
        #   後 osascript 通知；目前推播統一由隔日 10:13 lottery-daily 單一出口發（2026-08-09 拍板）
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
    parser.add_argument("--force-repick", action="store_true",
                        help="演算法改版時，強制重算「尚未開獎」那期的預測"
                             "（預設保留已發布號碼，見改版閘門）")
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

    update_html(draws, dry_run=args.dry, force_repick=args.force_repick)


if __name__ == "__main__":
    main()
