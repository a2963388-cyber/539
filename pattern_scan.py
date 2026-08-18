#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pattern_scan — 開獎號碼屬性掃描（描述性統計）
==================================================
鈞洋 2026-08-17 提問：「不管賠率，以開獎號碼的屬性，短期內有什麼規律？」

🔴 這份報告回答的是「**一組號碼長什麼樣才算典型**」（描述性），
   **不是**「下期會開什麼」（預測性）。兩者差別是本專案反覆驗證過的：
   號碼層級的預測訊號一律不存在（見 hazard_test.py 及本機另一支實證腳本，
   27 次檢定 Holm 校正後全滅）。

**事前註冊的八項**（寫死後才跑，跑完全部報告，不挑好看的呈現）：
   P1 奇偶比        P2 大小比（以號池中位數切）
   P3 和值          P4 連號（含相鄰號碼對）
   P5 同尾（兩碼尾數相同）  P6 跨度（最大−最小）
   P7 區間分佈（十位數分組） P8 重號（與上期重複幾碼）

每項同時給「今年」與「全歷史」，並附理論值。
理論一律以超幾何／組合列舉精算，不用近似。

多重比較：8 項 × 3 系統 = 24 次檢定，Holm-Bonferroni 校正。

用法：python3 pattern_scan.py [--year 2026] [--html]
"""

import json
import os
import sys
from collections import Counter
from itertools import combinations
from math import comb, sqrt, erf

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import backtest_stats as bs  # noqa: E402

GAMES = {
    "539": {"file": "backtest_data_539.json", "pool": 39, "draw": 5,
            "name": "今彩539", "year": lambda r, y: r["p"] >= (y - 1911) * 1000 + 1},
    "f5":  {"file": "backtest_data_f5.json", "pool": 39, "draw": 5,
            "name": "Fantasy 5", "year": lambda r, y: (r.get("dt") or "") >= f"{y}-01-01"},
    "m6":  {"file": "backtest_data_m6.json", "pool": 49, "draw": 6,
            "name": "香港六合彩", "year": lambda r, y: r["p"] >= (y - 2000) * 1000 + 1},
}


def norm_p(z):
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def load(game, year=None):
    rows = json.load(open(os.path.join(HOME, GAMES[game]["file"]), encoding="utf-8"))
    if year:
        rows = [r for r in rows if GAMES[game]["year"](r, year)]
    return sorted(rows, key=lambda r: r["p"])


# ── 屬性抽取（單期）────────────────────────────────────────────
def f_odd(nums, pool):       return sum(1 for n in nums if n % 2 == 1)
def f_big(nums, pool):       return sum(1 for n in nums if n > pool // 2)
def f_sum(nums, pool):       return sum(nums)
def f_conseq(nums, pool):    return sum(1 for a, b in zip(sorted(nums), sorted(nums)[1:]) if b - a == 1)
def f_sametail(nums, pool):  return sum(1 for a, b in combinations(sorted(nums), 2) if a % 10 == b % 10)
def f_span(nums, pool):      return max(nums) - min(nums)
def f_zones(nums, pool):     return len({n // 10 for n in nums})

FEATS = [("P1", "奇數個數", f_odd), ("P2", "大號個數", f_big),
         ("P3", "和值", f_sum), ("P4", "連號對數", f_conseq),
         ("P5", "同尾對數", f_sametail), ("P6", "跨度", f_span),
         ("P7", "涵蓋號域數", f_zones)]


def exact_dist(pool, draw, fn):
    """對全部 C(pool,draw) 組合精算該屬性的理論分佈。"""
    d = Counter()
    for c in combinations(range(1, pool + 1), draw):
        d[fn(c, pool)] += 1
    tot = comb(pool, draw)
    return {k: v / tot for k, v in d.items()}


def repeat_stats(rows, use_e=False):
    """P8 重號：與上期重複幾碼。"""
    out = []
    prev = None
    for r in rows:
        s = set(r["n"])
        if use_e and r.get("e"):
            s.add(r["e"])
        if prev is not None:
            out.append(len(s & prev))
        prev = s
    return out


def analyse(game, year):
    cfg = GAMES[game]
    pool, draw = cfg["pool"], cfg["draw"]
    allrows, yrrows = load(game), load(game, year)
    res = {"name": cfg["name"], "pool": pool, "draw": draw,
           "nYear": len(yrrows), "nAll": len(allrows), "items": []}

    for code, label, fn in FEATS:
        th = exact_dist(pool, draw, fn)
        exp_mean = sum(k * v for k, v in th.items())
        item = {"code": code, "label": label, "theoryMean": exp_mean, "dist": []}
        for tag, rows in (("今年", yrrows), ("全歷史", allrows)):
            vals = [fn(r["n"], pool) for r in rows]
            n = len(vals)
            mean = sum(vals) / n
            # 卡方適合度（合併期望值 < 5 的格）
            cnt = Counter(vals)
            keys = sorted(th)
            obs, exp = [], []
            acc_o = acc_e = 0.0
            for k in keys:
                acc_o += cnt.get(k, 0)
                acc_e += th[k] * n
                if acc_e >= 5:
                    obs.append(acc_o); exp.append(acc_e); acc_o = acc_e = 0.0
            if acc_e > 0 and obs:
                obs[-1] += acc_o; exp[-1] += acc_e
            r = bs.chi2_gof(obs, exp) if len(obs) > 1 else {"stat": 0, "df": 0, "p": 1.0}
            item["dist"].append({"tag": tag, "n": n, "mean": mean,
                                 "chi": r, "counts": dict(cnt)})
        res["items"].append(item)

    # P8 重號
    p0 = draw / pool
    exp_rep = draw * p0
    item = {"code": "P8", "label": "與上期重複碼數", "theoryMean": exp_rep, "dist": []}
    for tag, rows in (("今年", yrrows), ("全歷史", allrows)):
        vals = repeat_stats(rows)
        n = len(vals)
        mean = sum(vals) / n
        th = {k: comb(draw, k) * comb(pool - draw, draw - k) / comb(pool, draw)
              for k in range(0, draw + 1)}
        cnt = Counter(vals)
        obs, exp = [], []
        acc_o = acc_e = 0.0
        for k in sorted(th):
            acc_o += cnt.get(k, 0); acc_e += th[k] * n
            if acc_e >= 5:
                obs.append(acc_o); exp.append(acc_e); acc_o = acc_e = 0.0
        if acc_e > 0 and obs:
            obs[-1] += acc_o; exp[-1] += acc_e
        r = bs.chi2_gof(obs, exp) if len(obs) > 1 else {"stat": 0, "df": 0, "p": 1.0}
        item["dist"].append({"tag": tag, "n": n, "mean": mean, "chi": r,
                             "counts": dict(cnt)})
    res["items"].append(item)
    return res


def main(argv):
    year = 2026
    if "--year" in argv:
        year = int(argv[argv.index("--year") + 1])
    results = {g: analyse(g, year) for g in ("539", "f5", "m6")}

    tests = []
    for g, r in results.items():
        for it in r["items"]:
            for d in it["dist"]:
                if d["tag"] == "今年":
                    tests.append((f"{g}:{it['code']}", d["chi"]["p"]))
    adj, m = bs.holm(tests)

    for g in ("539", "f5", "m6"):
        r = results[g]
        print(f"\n{'='*78}")
        print(f"■ {r['name']}　{year} 年 {r['nYear']} 期（全歷史 {r['nAll']} 期對照）")
        print(f"{'='*78}")
        print(f"  {'項目':<16}{'今年均值':>9}{'全歷史':>9}{'理論值':>9}"
              f"{'今年χ²p':>10}{'校正後':>9}  結論")
        for it in r["items"]:
            y, a = it["dist"][0], it["dist"][1]
            k = f"{g}:{it['code']}"
            pa, rej = adj[k]
            verdict = "🔴 偏離" if rej else "符合理論"
            print(f"  {it['code']} {it['label']:<12}{y['mean']:>9.2f}{a['mean']:>9.2f}"
                  f"{it['theoryMean']:>9.2f}{y['chi']['p']:>10.4f}"
                  f"{(pa if pa is not None else 1):>9.4f}  {verdict}")
    n_sig = sum(1 for k, _ in tests if adj[k][1])
    print(f"\n{'='*78}")
    print(f"Holm-Bonferroni：{m} 次檢定（8 項 × 3 系統），校正後顯著 {n_sig} 項")
    print(f"{'='*78}")
    return results, adj


if __name__ == "__main__":
    main(sys.argv)
