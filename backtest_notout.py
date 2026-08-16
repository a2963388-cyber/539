#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_notout — 「N 不出」方案回測（2026-08-16 鈞洋提問）
==================================================================
問題：選 10 個號碼賭「全部不出」，用 fpx 平坦度邏輯挑，是否優於隨機挑？

🔴 口徑（鈞洋 2026-08-16 指示）：
    **不出牌判定要把特別號算進去** —— 特碼開出也算「這個號碼出了」。
    故「全不出」＝ 10 碼都不在【主 6 碼 ＋ 特別號】共 7 碼之中。
    ※ 這與**兌獎**口徑不同：兌獎特碼不計，維持主 6 碼（鈞洋同日確認）。

三種挑法（同期同資料，可直接比較）：
    A  fpx-主6      現行產線邏輯：dist/gaps 只吃主 6 碼，theory = 6/49
    B  fpx-含特碼   dist/gaps 吃 7 碼（主6＋特），theory = 7/49
    C  隨機         每期隨機挑 10 碼（決定性種子，可複驗）

理論基準：P(隨機 10 碼全不出) = C(39,7)/C(49,7) = 17.906%

用法：python3 backtest_notout.py [N]     # N 預設 10
"""

import json
import math
import os
import random
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

import backtest_stats as bs  # noqa: E402  借用 binom_test
from pick_engine import GAMES, ATRISK_MIN  # noqa: E402

WARMUP = 500
POOL = 49
MAIN, WITH_E = 6, 7


def load():
    return json.load(open(os.path.join(HOME, "backtest_data_m6.json"),
                         encoding="utf-8"))


def nums_of(rec, mode):
    """該期算作「開出」的號碼。mode=6 只主號；mode=7 含特別號。"""
    return rec["n"] + ([rec["e"]] if mode == WITH_E else [])


def build_dist_gaps(records, mode):
    """回歸間隔分佈與當前沉寂深度。records 新→舊。

    與 pick_engine.build_return_dist / current_gaps 同構，差別只在
    「開出號碼」是否含特別號（由 mode 控制）。
    """
    dist, gaps = {}, {n: len(records) for n in range(1, POOL + 1)}
    sets = [set(nums_of(r, mode)) for r in records]
    for i in range(len(records) - 1, -1, -1):
        for n in sets[i]:
            for j in range(i - 1, -1, -1):
                if n in sets[j]:
                    g = i - j - 1
                    dist[g] = dist.get(g, 0) + 1
                    break
    for n in range(1, POOL + 1):
        for i, s in enumerate(sets):
            if n in s:
                gaps[n] = i
                break
    return dist, gaps


def pick_flat(dist, gaps, mode, k):
    """fpx 邏輯延伸：按 h 由低到高收柱子，湊滿 k 顆後取前 k。

    h(g) = dist[g] / atRisk(g)，與平坦度卡同式；atRisk < ATRISK_MIN 視為中性。
    同 h 取深度淺者（決定性）。柱內號碼由小到大。
    """
    theory = mode / POOL
    below = []
    for g in range(0, (max(dist) + 1) if dist else 0):
        at_risk = sum(c for kk, c in dist.items() if kk >= g)
        if at_risk < ATRISK_MIN:
            break
        h = dist.get(g, 0) / at_risk
        if h < theory:
            below.append((h, g, sorted(n for n, gg in gaps.items() if gg == g)))
    below.sort(key=lambda t: (t[0], t[1]))
    out = []
    for h, g, ns in below:
        for n in ns:
            if len(out) < k:
                out.append(n)
        if len(out) >= k:
            break
    return out


def main(argv):
    k = int(argv[0]) if argv and argv[0].isdigit() else 10
    recs = load()
    n = len(recs)
    targets = sorted([i for i in range(0, n - WARMUP - 1)], reverse=True)

    theory_p = math.comb(POOL - k, WITH_E) / math.comb(POOL, WITH_E)
    print(f"「{k} 不出」回測｜六合彩 {len(targets)} 期"
          f"（warmup {WARMUP}）\n"
          f"判定口徑：全不出 ＝ {k} 碼都不在【主6＋特碼】共 7 碼中\n"
          f"理論機率（隨機挑 {k} 碼）＝ C({POOL-k},7)/C({POOL},7) "
          f"= {theory_p*100:.3f}%\n", flush=True)

    stat = {t: {"win": 0, "n": 0, "short": 0} for t in ("A", "B", "C")}
    rnd = random.Random(20260816)
    for idx, i in enumerate(targets):
        hist, tgt = recs[i + 1:], recs[i]
        out7 = set(nums_of(tgt, WITH_E))          # 判定一律含特碼

        d6, g6 = build_dist_gaps(hist, MAIN)
        d7, g7 = build_dist_gaps(hist, WITH_E)
        picks = {"A": pick_flat(d6, g6, MAIN, k),
                 "B": pick_flat(d7, g7, WITH_E, k),
                 "C": rnd.sample(range(1, POOL + 1), k)}
        for t, p in picks.items():
            if len(p) < k:
                stat[t]["short"] += 1        # 湊不滿 k 顆，不計入
                continue
            stat[t]["n"] += 1
            if not (set(p) & out7):
                stat[t]["win"] += 1
        if (idx + 1) % 500 == 0:
            print(f"  …{idx+1}/{len(targets)}", flush=True)

    print()
    names = {"A": "fpx-主6（現行產線邏輯）", "B": "fpx-含特碼", "C": "隨機對照"}
    print(f"  {'挑法':<22}{'可評估期':>8}{'全不出':>8}{'實際機率':>10}"
          f"{'vs 理論':>10}{'p 值':>9}")
    print("  " + "-" * 70)
    for t in ("A", "B", "C"):
        s = stat[t]
        if s["n"] == 0:
            print(f"  {names[t]:<22}{'—':>8}  湊不滿 {k} 顆，無法評估")
            continue
        r = s["win"] / s["n"]
        bt = bs.binom_test(s["win"], s["n"], theory_p)
        print(f"  {names[t]:<20}{s['n']:>8}{s['win']:>8}{r*100:>9.2f}%"
              f"{(r/theory_p-1)*100:>+9.1f}%{bt['p']:>9.4f}")
        if s["short"]:
            print(f"    ⚠️ 另有 {s['short']} 期湊不滿 {k} 顆，已排除")

    print()
    print("  保本賠率門檻（鈞洋 2026-08-16 確認：其莊家報的是**含本金**賠率，")
    print("  即中了拿回 R 元含本金在內，故保本條件 R = 1/P，不是 1/P−1）：")
    print(f"    {'挑法':<24}{'含本金 R':>10}{'（淨賠率 R−1）':>14}")
    for t in ("A", "B", "C"):
        s = stat[t]
        if s["n"]:
            r = s["win"] / s["n"]
            if r:
                print(f"    {names[t]:<22}{1/r:>10.3f}{1/r-1:>14.3f}")
    print(f"    {'理論值':<22}{1/theory_p:>10.3f}{1/theory_p-1:>14.3f}")

    # breakEven*：Gross ＝含本金（鈞洋的莊家用這個報價）、Net ＝淨賠率
    out = {"k": k, "nPeriods": len(targets), "theoryP": theory_p,
           "theoryOddsGross": 1 / theory_p,
           "theoryOddsNet": 1 / theory_p - 1, "lines": {}}
    for t in ("A", "B", "C"):
        s = stat[t]
        if not s["n"]:
            continue
        r = s["win"] / s["n"]
        out["lines"][t] = {"name": names[t], "n": s["n"], "win": s["win"],
                           "rate": r, "short": s["short"],
                           "vsTheory": r / theory_p - 1,
                           "p": bs.binom_test(s["win"], s["n"], theory_p)["p"],
                           "breakEvenGross": 1 / r if r else None,
                           "breakEvenNet": 1 / r - 1 if r else None}
    # 效力：本樣本能偵測多大的相對效果（2 SD）
    nA = stat["A"]["n"]
    sd = math.sqrt(nA * theory_p * (1 - theory_p))
    out["detectable"] = 2 * sd / (nA * theory_p)
    print(f"\n  ⚠️ 效力：本樣本僅能偵測 ±{out['detectable']*100:.1f}% 的相對效果。"
          f"\n     p>0.05 ＝「排除了大於此幅度的優勢」，不是「證明完全沒有優勢」。")
    with open(os.path.join(HOME, "backtest_notout_results.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print("\n→ 已寫入 backtest_notout_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
