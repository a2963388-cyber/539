#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_diagnostics — 對顯著結果的追查（REGISTRY §5 預先承諾的動作）
========================================================================
主檢定跑出兩個顯著結果，依 REGISTRY §5「顯著正向 → 先假設程式有 bug」條款，
本檔把追查過程固化成可複驗腳本，不留在一次性指令裡。

D1 安慰劑排除區（針對 T2 顯著）
    S3 與 B2 的候選池不同 ⇒ PRNG 路徑不同 ⇒ 選出的是兩組完全不同的號碼。
    差異可能只是「換一組隨機號碼」的假象。對照：用**同樣大小但隨機挑選**的
    排除區重跑，看真實值是否落在安慰劑分佈之外。

D2 換 salt（決定性檢驗）
    若排除區有真實因果效果，換任何 PRNG 路徑都該同方向。
    對同一份真實 fpx-v3 排除區，換 20 個 salt 重跑，看均差分佈是否以 0 為中心。

D3 T4 高低號拆解（針對 T4 顯著）
    假設：G3 高號保底（hi=32、MIN_HIGH_TOTAL=3）在 pool=39 時僅 8 個高號可分擔，
    造成 32-39 被系統性超選。對照組 B1（無規則）應完全均勻。

用法：python3 backtest_diagnostics.py
"""

import json
import math
import os
import random
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

import pick_engine as pe  # noqa: E402
import backtest as bt  # noqa: E402

RESULTS = os.path.join(HOME, "backtest_v3_results.json")
OUT = os.path.join(HOME, "backtest_v3_diagnostics.json")
N_PLACEBO = 30
N_SALT = 20


def exclusion_cases(game):
    """重算每期的 fpx-v3 排除區（與 salt 無關，故只需算一次）。"""
    recs = bt.load(game)
    n = len(recs)
    targets = sorted([k for k in range(0, n - bt.WARMUP - 1)], reverse=True)
    cases = []
    for k in targets:
        hist, tgt = recs[k + 1:], recs[k]
        dist = pe.build_return_dist(hist)
        gaps = pe.current_gaps(hist, pe.GAMES[game]["pool_max"])
        ex, dep, rd = bt.select_exclude(game, dist, gaps, pe.ATRISK_MIN)
        if ex:
            # draw 必須用**兌獎口徑**（六合含特別號），否則與主回測的均差對不上
            cases.append({"seed": hist[0]["p"], "last": hist[0]["n"],
                          "draw": bt.winning_nums(game, tgt), "ex": ex, "rd": rd})
    return cases, len(targets)


def _total(game, seed, last, draw, ex, rd):
    res = pe.gen_four_groups(game, seed, last, excluded=ex, readmit_order=rd)
    ds = set(draw)
    return sum(len(set(g) & ds) for g in res["strategies"].values())


def d1_placebo(game, cases, n_all, real_mean):
    """隨機排除區安慰劑分佈。"""
    cfg = pe.GAMES[game]
    means = []
    for rep in range(N_PLACEBO):
        rnd = random.Random(1000 + rep)
        tot = 0
        for c in cases:
            fake = sorted(rnd.sample(range(1, cfg["pool_max"] + 1), len(c["ex"])))
            base = _total(game, c["seed"], c["last"], c["draw"], [], [])
            tot += _total(game, c["seed"], c["last"], c["draw"], fake, fake) - base
        means.append(tot / n_all)
    mu = sum(means) / len(means)
    sd = math.sqrt(sum((x - mu) ** 2 for x in means) / (len(means) - 1))
    return {"n": N_PLACEBO, "mean": mu, "sd": sd,
            "min": min(means), "max": max(means),
            "realMean": real_mean,
            "z": (real_mean - mu) / sd if sd else None,
            "nGE": sum(1 for x in means if x >= real_mean)}


def d2_salt(game, cases, n_all):
    """換 20 個 salt，用同一份真實排除區。"""
    orig = pe.GAMES[game]["salt"]
    out = {}
    for salt in range(1, N_SALT + 1):
        pe.GAMES[game]["salt"] = salt
        tot = 0
        for c in cases:
            tot += (_total(game, c["seed"], c["last"], c["draw"], c["ex"], c["rd"])
                    - _total(game, c["seed"], c["last"], c["draw"], [], []))
        out[salt] = tot / n_all
    pe.GAMES[game]["salt"] = orig
    vals = sorted(out.values())
    mu = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - mu) ** 2 for x in vals) / (len(vals) - 1))
    real = out[orig]
    return {"bySalt": out, "prodSalt": orig, "prodValue": real,
            "mean": mu, "sd": sd, "min": vals[0], "max": vals[-1],
            "rank": sorted(vals, reverse=True).index(real) + 1, "n": N_SALT,
            "z": (real - mu) / sd if sd else None}


def d3_high_low(game, stats):
    """T4 高低號拆解。"""
    a = stats["games"][game]
    pool = a["pool"]
    out = {}
    for tag in ("S3", "S4", "B1"):
        c = a[f"T4_{tag}"]["counts"]
        exp = a[f"T4_{tag}"]["exp"]
        lo = c[:31]
        hi = c[31:pool]
        out[tag] = {"chi2": a[f"T4_{tag}"]["stat"], "p": a[f"T4_{tag}"]["p"],
                    "nHigh": len(hi),
                    "lowAvg": sum(lo) / len(lo), "highAvg": sum(hi) / len(hi),
                    "lowPct": sum(lo) / len(lo) / exp * 100,
                    "highPct": sum(hi) / len(hi) / exp * 100,
                    "minNum": c.index(min(c)) + 1, "minCnt": min(c),
                    "maxNum": c.index(max(c)) + 1, "maxCnt": max(c),
                    "ratio": max(c) / min(c)}
    return out


def main(argv=()):
    """argv 可指定彩種（如 `backtest_diagnostics.py m6`）；預設三彩種全跑。

    指定單一彩種時**不覆寫輸出檔**，避免把另兩種的結果洗掉。
    """
    data = json.load(open(RESULTS, encoding="utf-8"))
    stats = json.load(open(os.path.join(HOME, "backtest_v3_stats.json"),
                           encoding="utf-8"))
    picked = [g for g in argv if g in ("539", "f5", "m6")]
    out = {}
    for game in (picked or ["539", "f5", "m6"]):
        print(f"== {game} ==", flush=True)
        rows = data["games"][game]
        real = sum(r["lines"]["S3"]["total"] - r["lines"]["B2"]["total"]
                   for r in rows) / len(rows)
        print("  算排除區…", flush=True)
        cases, n_all = exclusion_cases(game)
        print(f"  非空 {len(cases)}/{n_all} 期｜真實均差 {real:+.5f}", flush=True)
        print("  D1 安慰劑…", flush=True)
        d1 = d1_placebo(game, cases, n_all, real)
        print(f"     安慰劑 {d1['mean']:+.5f}±{d1['sd']:.5f}  真實 z={d1['z']:+.2f}"
              f"  ({d1['nGE']}/{d1['n']} 次 ≥ 真實)", flush=True)
        print("  D2 換 salt…", flush=True)
        d2 = d2_salt(game, cases, n_all)
        print(f"     20 salt 分佈 {d2['mean']:+.5f}±{d2['sd']:.5f}"
              f"｜產線 salt={d2['prodSalt']} 值 {d2['prodValue']:+.5f}"
              f" 排名第 {d2['rank']}/{d2['n']}", flush=True)
        # 🔴 內建一致性閘門：D2 中「產線 salt」那一格是用真實排除區重算的，
        # 必須逐位元等於主回測算出的均差。兩者對不上＝某一邊的兌獎口徑或
        # 資料來源漏改（2026-08-16 六合特別號更正時，diagnostics 就漏改過一次）。
        if abs(d2["prodValue"] - real) > 1e-9:
            raise SystemExit(
                f"🚨 [{game}] 一致性閘門失敗：主回測均差 {real:+.6f} "
                f"≠ D2 salt={d2['prodSalt']} 重算值 {d2['prodValue']:+.6f}。"
                f"\n   兩邊的兌獎口徑或資料不同步，結果不可採信。")
        print("  一致性閘門 ✅（D2 產線 salt 值 == 主回測均差）", flush=True)

        out[game] = {"realMeanDiff": real, "nCases": len(cases), "nAll": n_all,
                     "D1_placebo": d1, "D2_salt": d2,
                     "D3_highLow": d3_high_low(game, stats)}

    if picked:
        print(f"\n（只跑 {'/'.join(picked)}，不覆寫 {os.path.basename(OUT)}）")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"\n→ 已寫入 {os.path.basename(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
