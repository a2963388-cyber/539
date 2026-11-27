#!/usr/bin/env python3
"""一次性：替 data_539.js 的 BASE_REC 補上開獎日期 dt（2026-11-27 鈞洋要求「每一期要有日期，不要只有期號」）。

來源＝台灣彩券官方 API 的 lotteryDate（與 539_fetch.py 主源相同），不靠期號推日期（停開日會推錯）。
任何一期查不到日期就整個中止、不寫入。可重跑：已有 dt 的會被官方值覆蓋並比對。
用法：python3 backfill_539_dates.py [--dry-run]
"""
import json, re, sys, os, requests
from datetime import date

API_URL = "https://api.taiwanlottery.com/TLCAPIWEB/Lottery/Daily539Result"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_539.js")
dry = "--dry-run" in sys.argv

html = open(PATH, encoding="utf-8").read()
m = re.search(r"(const BASE_REC = \[)(.*?)(\n\];?)", html, re.DOTALL)
cleaned = m.group(2).strip().rstrip(",").strip()
recs = json.loads("[" + re.sub(r"(\b[a-z]\w*\b):", r'"\1":', cleaned) + "]")
need = {r["p"] for r in recs}
years = sorted({p // 1000 for p in need})

dates, nums_official = {}, {}
for roc in years:
    y = roc + 1911
    for mo in range(1, 13):
        if date(y, mo, 1) > date.today():
            break
        url = f"{API_URL}?period&month={y}-{mo:02d}&pageNum=1&pageSize=50"
        items = (requests.get(url, headers=HEADERS, timeout=20).json().get("content") or {}).get("daily539Res") or []
        for it in items:
            p = (it["period"] // 1000000) * 1000 + it["period"] % 1000
            dates[p] = it["lotteryDate"][:10]
            nums_official[p] = sorted(it["drawNumberSize"])

missing = sorted(need - set(dates))
if missing:
    print(f"❌ 官方 API 查不到 {len(missing)} 期的日期：{missing[:10]}…，中止不寫入")
    sys.exit(1)
bad = [r["p"] for r in recs if sorted(r["n"]) != nums_official[r["p"]]]
if bad:
    print(f"❌ 有 {len(bad)} 期號碼與官方不符：{bad[:10]}，中止不寫入")
    sys.exit(1)

for r in recs:
    r["dt"] = dates[r["p"]]
lines = []
for i in range(0, len(recs), 5):
    chunk = recs[i:i + 5]
    parts = [f'{{p:{r["p"]},dt:"{r["dt"]}",n:[{",".join(str(n) for n in r["n"])}]}}' for r in chunk]
    lines.append("  " + ",".join(parts) + ("," if i + 5 < len(recs) else ""))
new = "const BASE_REC = [\n" + "\n".join(lines) + "\n];"
print(f"✅ {len(recs)} 期全部對到官方日期與號碼｜最新 {recs[0]['p']}={recs[0]['dt']}｜最舊 {recs[-1]['p']}={recs[-1]['dt']}")
if dry:
    print("[dry-run] 不寫入"); sys.exit(0)
open(PATH, "w", encoding="utf-8").write(html[:m.start()] + new + html[m.end():])
print("已寫入", PATH)
