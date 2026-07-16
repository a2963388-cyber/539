#!/usr/bin/env python3
"""抓三系統全歷史開獎 → history_539.json / history_f5.json / history_m6.json
只供回測使用，不動產線 data_*.js。539 走官方 API 按月回溯；F5/M6 走 lottolyzer 分頁。"""
import json, re, sys, time
from datetime import date, timedelta
from pathlib import Path

import requests

HOME = Path(__file__).parent
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
API_URL = 'https://api.taiwanlottery.com/TLCAPIWEB/Lottery/Daily539Result'


def official_to_period(op: int) -> int:
    return op // 1000000 * 1000 + op % 1000


def fetch_539_history():
    """按月回溯官方 API，連續 4 個空月即認定到頭（今彩539 2007-01 開辦）"""
    draws, empty_streak = {}, 0
    d = date.today().replace(day=1)
    months = 0
    while empty_streak < 4 and d.year >= 2006:
        url = f"{API_URL}?period&month={d.year}-{d.month:02d}&pageNum=1&pageSize=50"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            items = (r.json().get('content') or {}).get('daily539Res') or []
        except Exception as e:
            print(f"  ⚠️ {d.year}-{d.month:02d} 失敗：{e}", flush=True)
            items = None
        if items:
            empty_streak = 0
            for it in items:
                p = official_to_period(it['period'])
                nums = sorted(it['drawNumberSize'])
                if len(nums) == 5 and all(1 <= n <= 39 for n in nums):
                    draws[p] = {'p': p, 'n': nums}
        elif items is not None:
            empty_streak += 1
        months += 1
        if months % 24 == 0:
            print(f"  …已回溯 {months} 個月，累計 {len(draws)} 期（{d.year}-{d.month:02d}）", flush=True)
        d = (d - timedelta(days=1)).replace(day=1)
        time.sleep(0.25)
    out = sorted(draws.values(), key=lambda x: -x['p'])
    return out


def fetch_lottolyzer(base_url, pool_max, draw_len, is_m6):
    """逐頁抓到沒有資料為止"""
    results, page = {}, 1
    while page <= 500:
        url = base_url.format(page)
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  ⚠️ page {page} 失敗：{e}，重試一次", flush=True)
            time.sleep(3)
            try:
                r = requests.get(url, headers=HEADERS, timeout=25)
                r.raise_for_status()
            except requests.RequestException as e2:
                print(f"  ❌ page {page} 再失敗：{e2}，中止", flush=True)
                break
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL)
        got = 0
        for row in rows:
            tds = [re.sub(r'<[^>]+>', '', t).strip()
                   for t in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
            if len(tds) < 3 or not re.match(r'20\d\d-\d\d-\d\d|19\d\d-\d\d-\d\d', tds[1] if len(tds) > 1 else ''):
                continue
            if is_m6:
                if not re.match(r'\d\d/\d+', tds[0]):
                    continue
                key = tds[0]
                nums = [int(x) for x in tds[2].split(',') if x.strip().isdigit() and 1 <= int(x) <= pool_max]
                extra = int(tds[3]) if len(tds) > 3 and tds[3].strip().isdigit() else 0
                if len(nums) == draw_len:
                    results[key] = {'draw': key, 'dt': tds[1], 'n': sorted(nums), 'e': extra}
                    got += 1
            else:
                if not tds[0].isdigit():
                    continue
                key = int(tds[0])
                nums = [int(x) for x in tds[2].split(',') if x.strip().isdigit() and 1 <= int(x) <= pool_max]
                if len(nums) == draw_len:
                    results[key] = {'p': key, 'dt': tds[1], 'n': sorted(nums)}
                    got += 1
        if got == 0:
            break
        if page % 20 == 0:
            print(f"  …page {page}，累計 {len(results)} 期", flush=True)
        page += 1
        time.sleep(0.5)
    return list(results.values())


def main():
    which = set(sys.argv[1:]) or {'539', 'f5', 'm6'}

    if '539' in which:
        print('== 539 官方 API 回溯 ==', flush=True)
        h = fetch_539_history()
        (HOME / 'history_539.json').write_text(json.dumps(h, separators=(',', ':')))
        print(f"✅ 539：{len(h)} 期（{h[-1]['p']} ~ {h[0]['p']}）", flush=True)

    if 'f5' in which:
        print('== Fantasy 5 lottolyzer 全歷史 ==', flush=True)
        h = fetch_lottolyzer('https://en.lottolyzer.com/history/united-states/fantasy-5-california/page/{}/per-page/50/summary-view', 39, 5, False)
        h.sort(key=lambda x: -x['p'])
        (HOME / 'history_f5.json').write_text(json.dumps(h, separators=(',', ':')))
        print(f"✅ F5：{len(h)} 期（Draw {h[-1]['p']} ~ {h[0]['p']}）", flush=True)

    if 'm6' in which:
        print('== 六合彩 lottolyzer 全歷史 ==', flush=True)
        h = fetch_lottolyzer('https://en.lottolyzer.com/history/hong-kong/mark-six/page/{}/per-page/50/summary-view', 49, 6, True)
        h.sort(key=lambda x: x['dt'], reverse=True)   # YY/NNN 跨世紀不可比，用日期排序
        (HOME / 'history_m6.json').write_text(json.dumps(h, separators=(',', ':')))
        print(f"✅ M6：{len(h)} 期（{h[-1]['dt']} ~ {h[0]['dt']}）", flush=True)


if __name__ == '__main__':
    main()
