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
import argparse
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
    """今彩539 週一至週六開獎（星期日跳過）"""
    return d.weekday() != 6  # 6 = Sunday

def draw_days_between(start: date, end: date) -> int:
    """計算 start 到 end（含）之間的開獎日數（正數=向後，負數=向前）"""
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
    """給定開獎日期，推算期號"""
    diff = draw_days_between(ANCHOR_DATE, d)
    return ANCHOR_PERIOD + diff

def period_to_date(period: int) -> date:
    """給定期號，推算開獎日期"""
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
    """
    從 pilio.idv.tw 抓取今彩539開獎（依日期推算期號）
    回傳 [{p: int, n: [sorted 5 nums]}, ...] 最新在前
    """
    url = "https://www.pilio.idv.tw/lto539/list.asp"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ 抓取失敗：{e}")
        return []

    html = r.text
    # 格式：<td class="date-cell">06/19<br>26(五)</td>
    #        <td class="number-cell">01,&nbsp;05,&nbsp;...
    pattern = r'date-cell[^>]*>(\d{2}/\d{2})<br>\d+(.*?number-cell.*?)([\d,\s&nbsp;]+)</td>'
    rows = re.findall(pattern, html, re.DOTALL)

    draws = []
    current_year = ANCHOR_DATE.year

    for date_str, _, nums_raw in rows:
        month, day = map(int, date_str.split("/"))
        d = date(current_year, month, day)
        # 期號推算
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
    """records 最新在前；回傳 {1~39: 沉寂期數}"""
    ab = {}
    for n in range(1, 40):
        count = 0
        for r in records:
            if n in r["n"]:
                break
            count += 1
        ab[n] = count
    return ab


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

    print(f"新增：" + "、".join(
        f"{d['p']}期({','.join(str(n).zfill(2) for n in d['n'])})"
        for d in actually_new
    ))

    # 解析現有 BASE_REC
    rec_match = re.search(r"(const BASE_REC = \[)(.*?)(\n\];?)", html, re.DOTALL)
    if not rec_match:
        print("❌ 無法解析 BASE_REC")
        return

    existing_js = rec_match.group(2)
    # 移除尾部逗號（JS 合法但 JSON 不接受）
    cleaned = existing_js.strip().rstrip(",").strip()
    existing_json = "[" + re.sub(r"(\b[a-z]\w*\b):", r'"\1":', cleaned) + "]"
    try:
        existing = json.loads(existing_json)
    except json.JSONDecodeError as e:
        print(f"❌ BASE_REC 解析失敗：{e}")
        return

    all_records = actually_new + existing
    total = len(all_records)
    oldest = all_records[-1]["p"]
    newest = all_records[0]["p"]

    # 重建 BASE_REC（5 筆一行）
    rec_lines = []
    for i in range(0, len(all_records), 5):
        chunk = all_records[i : i + 5]
        parts = [f"{{p:{r['p']},n:[{','.join(str(n) for n in r['n'])}]}}" for r in chunk]
        suffix = "," if i + 5 < len(all_records) else ""
        rec_lines.append("  " + ",".join(parts) + suffix)
    new_base_rec = "const BASE_REC = [\n" + "\n".join(rec_lines) + "\n];"

    html = html[: rec_match.start()] + new_base_rec + html[rec_match.end() :]

    # 更新 ab 值 in BASE_ST（逐號替換）
    ab = calc_absent(all_records)
    for n in range(1, 40):
        html = re.sub(
            rf'(\b{n}:{{[^}}]*?\bab:)\d+',
            rf'\g<1>{ab[n]}',
            html
        )

    # 更新頂部注釋
    today = date.today().strftime("%Y-%m-%d")
    html = re.sub(
        r"// ── BASE DATA（.*?）──",
        f"// ── BASE DATA（{oldest}–{newest}，共{total}期，對應遺漏統計表 {today}）──",
        html,
    )

    if dry_run:
        print(f"\n[Dry Run] 將更新至第 {newest} 期，共 {total} 期，不寫入")
        return

    INDEX_HTML.write_text(html, encoding="utf-8")
    print(f"\n✅ 已更新 → 第 {newest} 期，共 {total} 期（{today}）")
    print("→ 沉寂期數 ab 已重新計算")
    print("→ 記得重新整理瀏覽器（Cmd+R）")


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
        return

    update_html(draws, dry_run=args.dry)


if __name__ == "__main__":
    main()
