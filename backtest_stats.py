#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_stats — 依 BACKTEST_REGISTRY.md §4 執行檢定並產生報告
===================================================================
本機無 scipy／numpy，故所有統計量自行實作（純標準庫）：
  常態 CDF        math.erf
  卡方 CDF        regularized incomplete gamma（Numerical Recipes 級數／連分數）
  Wilcoxon 配對   常態近似 ＋ tie correction（n 數千，近似完全適用）
  二項            常態近似 ＋ 連續性校正，另附 Wilson 95% CI

判準與預先承諾的行動已寫死在 REGISTRY，本檔不得新增檢定或更改判準。

用法：python3 backtest_stats.py [--json]
"""

import json
import math
import os
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
from pick_engine import GAMES  # noqa: E402
from backtest import SCORE_DRAW, APPEAR_DRAW  # noqa: E402
# SCORE_DRAW ＝兌獎口徑（六合 6，特碼不計）→ T1/T2/T5
# APPEAR_DRAW＝出現口徑（六合 7，含特碼）→ T3 排除區命中率

RESULTS = os.path.join(HOME, "backtest_v3_results.json")
ALPHA = 0.05
GAME_NAME = {"539": "今彩539", "f5": "Fantasy 5", "m6": "六合彩"}


# ─────────────────────────── 分佈函式 ───────────────────────────

def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_sided_z_p(z):
    return 2.0 * (1.0 - norm_cdf(abs(z)))


def _gser(a, x):
    """regularized lower incomplete gamma P(a,x)，級數展開（x < a+1）。"""
    ap, s, d = a, 1.0 / a, 1.0 / a
    for _ in range(1000):
        ap += 1
        d *= x / ap
        s += d
        if abs(d) < abs(s) * 1e-14:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a, x):
    """regularized upper incomplete gamma Q(a,x)，連分數（x >= a+1）。"""
    tiny = 1e-300
    b, c, d = x + 1.0 - a, 1.0 / tiny, 1.0 / (x + 1.0 - a)
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x, df):
    """卡方分佈上尾機率 P(X > x)。"""
    if x <= 0:
        return 1.0
    a, xx = df / 2.0, x / 2.0
    return 1.0 - _gser(a, xx) if xx < a + 1.0 else _gcf(a, xx)


# ─────────────────────────── 檢定 ───────────────────────────

def wilcoxon_paired(xs, ys):
    """配對 Wilcoxon 符號秩（常態近似 ＋ tie correction）。

    回傳 dict：n_used（去掉 d=0 後的樣本）、z、p、meanDiff。
    """
    ds = [x - y for x, y in zip(xs, ys)]
    nz = [d for d in ds if d != 0]
    n = len(nz)
    mean_diff = sum(ds) / len(ds) if ds else 0.0
    if n < 10:
        return {"n": n, "z": None, "p": None, "meanDiff": mean_diff}
    order = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0.0] * n
    i = 0
    tie_groups = []
    while i < n:
        j = i
        while j + 1 < n and abs(nz[order[j + 1]]) == abs(nz[order[i]]):
            j += 1
        avg = (i + j + 2) / 2.0            # 平均秩（1-based）
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        tie_groups.append(j - i + 1)
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, nz) if d > 0)
    e_w = n * (n + 1) / 4.0
    var = n * (n + 1) * (2 * n + 1) / 24.0 - sum(t ** 3 - t for t in tie_groups) / 48.0
    if var <= 0:
        return {"n": n, "z": None, "p": None, "meanDiff": mean_diff}
    z = (w_plus - e_w) / math.sqrt(var)
    return {"n": n, "z": z, "p": two_sided_z_p(z), "meanDiff": mean_diff}


def binom_test(x, n, p0):
    """合併二項檢定（常態近似＋連續性校正）＋ Wilson 95% CI。"""
    if n == 0:
        return {"x": 0, "n": 0, "rate": None, "p": None, "ci": None, "p0": p0}
    rate = x / n
    sd = math.sqrt(n * p0 * (1 - p0))
    if sd == 0:
        return {"x": x, "n": n, "rate": rate, "p": None, "ci": None, "p0": p0}
    diff = abs(x - n * p0)
    z = max(0.0, diff - 0.5) / sd          # 連續性校正
    zc = 1.959963985
    den = 1 + zc ** 2 / n
    cen = (rate + zc ** 2 / (2 * n)) / den
    hw = zc * math.sqrt(rate * (1 - rate) / n + zc ** 2 / (4 * n ** 2)) / den
    return {"x": x, "n": n, "rate": rate, "p": two_sided_z_p(z),
            "ci": (cen - hw, cen + hw), "p0": p0}


def chi2_gof(obs, exp):
    """卡方適合度。回傳 stat、df、p。"""
    stat = sum((o - e) ** 2 / e for o, e in zip(obs, exp) if e > 0)
    df = len(obs) - 1
    return {"stat": stat, "df": df, "p": chi2_sf(stat, df)}


def holm(tests):
    """Holm-Bonferroni。tests: [(key, p)]，回傳 {key: (p_adj, reject)}。"""
    valid = [(k, p) for k, p in tests if p is not None]
    m = len(valid)
    valid.sort(key=lambda t: t[1])
    out, prev = {}, 0.0
    for i, (k, p) in enumerate(valid):
        adj = min(1.0, max(prev, (m - i) * p))
        prev = adj
        out[k] = (adj, adj < ALPHA)
    for k, p in tests:
        if p is None:
            out[k] = (None, False)
    return out, m


# ─────────────────────────── 分析 ───────────────────────────

def hypergeom_group(pool_max, draw, k):
    """一組 3 碼中恰有 k 碼開出的機率。draw 須為**兌獎口徑**的開出碼數。"""
    return (math.comb(draw, k) * math.comb(pool_max - draw, 3 - k)
            / math.comb(pool_max, 3))


def analyse(game, rows):
    cfg = GAMES[game]
    # 🔴 一律用兌獎口徑的 draw（六合＝7，含特別號），不是 GAMES[game]["draw"]（＝6，
    # 那是排除區／平坦度的參數）。2026-08-16 更正前誤用後者，六合結論全部低估。
    pool_max, draw = cfg["pool_max"], SCORE_DRAW[game]
    p0 = draw / pool_max
    n_periods = len(rows)
    res = {"game": game, "nPeriods": n_periods, "pool": pool_max, "draw": draw,
           "p0": p0, "histLen": {"min": min(r["histLen"] for r in rows),
                                 "max": max(r["histLen"] for r in rows)}}

    totals = {tag: [r["lines"][tag]["total"] for r in rows]
              for tag in ("S3", "S4", "B2", "B1")}
    res["totals"] = {t: {"sum": sum(v), "perPeriod": sum(v) / n_periods}
                     for t, v in totals.items()}
    res["theory"] = {"perPeriod": 12 * p0, "sum": 12 * p0 * n_periods}

    # T1 / T2
    res["T1_S3_vs_B1"] = wilcoxon_paired(totals["S3"], totals["B1"])
    res["T1_S4_vs_B1"] = wilcoxon_paired(totals["S4"], totals["B1"])
    res["T2_S3_vs_B2"] = wilcoxon_paired(totals["S3"], totals["B2"])
    res["T2_S4_vs_B2"] = wilcoxon_paired(totals["S4"], totals["B2"])

    # T3 排除區：合併二項（REGISTRY 明令不得逐期取平均）
    # 🔴 null 值用**出現口徑**（六合 7/49，含特碼）—— 不出牌問的是「有沒有開出」，
    #    不是「兌不兌得到獎」。與 T1/T2/T5 的 p0（兌獎口徑）刻意不同。
    p0_appear = APPEAR_DRAW[game] / pool_max
    res["p0Appear"] = p0_appear
    for tag in ("S3", "S4"):
        nx = sum(r["lines"][tag]["nExcl"] for r in rows)
        hx = sum(r["lines"][tag]["exclHits"] for r in rows)
        zero = sum(1 for r in rows if r["lines"][tag]["nExcl"] == 0)
        res[f"T3_{tag}"] = binom_test(hx, nx, p0_appear)
        res[f"T3_{tag}"]["zeroRate"] = zero / n_periods
        res[f"T3_{tag}"]["avgSize"] = nx / n_periods

    # T4 號碼入選均勻度
    for tag in ("S3", "S4", "B1"):
        cnt = {n: 0 for n in range(1, pool_max + 1)}
        for r in rows:
            for g in r["lines"][tag]["groups"].values():
                for n in g:
                    cnt[n] += 1
        exp = n_periods * 12 / pool_max
        res[f"T4_{tag}"] = chi2_gof([cnt[n] for n in range(1, pool_max + 1)],
                                    [exp] * pool_max)
        res[f"T4_{tag}"]["counts"] = [cnt[n] for n in range(1, pool_max + 1)]
        res[f"T4_{tag}"]["exp"] = exp

    # T5 每組命中數分佈（4 組 × 期數）
    for tag in ("S3", "S4", "B1"):
        obs = [0, 0, 0, 0]
        for r in rows:
            for h in r["lines"][tag]["hits"].values():
                obs[h] += 1
        tot = sum(obs)
        exp = [tot * hypergeom_group(pool_max, draw, k) for k in range(4)]
        res[f"T5_{tag}"] = chi2_gof(obs, exp)
        res[f"T5_{tag}"]["obs"] = obs
        res[f"T5_{tag}"]["expected"] = exp

    # 附帶事實：fallback 觸發率、三碼全中次數
    res["relaxedRate"] = {
        tag: sum(1 for r in rows if r["lines"][tag]["relaxed"]) / n_periods
        for tag in ("S3", "S4", "B2")}
    res["jackpot"] = {tag: sum(1 for r in rows
                               for h in r["lines"][tag]["hits"].values() if h == 3)
                      for tag in ("S3", "S4", "B2", "B1")}
    # 分段：短窗（histLen < 1000）vs 長窗，看漂移
    for tag in ("S3", "S4"):
        short = [r for r in rows if r["histLen"] < 1000]
        lng = [r for r in rows if r["histLen"] >= 1000]
        def agg(sub):
            if not sub:
                return None
            nx = sum(r["lines"][tag]["nExcl"] for r in sub)
            return {"n": len(sub), "avgSize": nx / len(sub),
                    "zeroRate": sum(1 for r in sub
                                    if r["lines"][tag]["nExcl"] == 0) / len(sub)}
        res[f"drift_{tag}"] = {"short": agg(short), "long": agg(lng)}
    return res


def main(argv):
    data = json.load(open(RESULTS, encoding="utf-8"))
    out = {"meta": data["meta"], "games": {}}
    tests = []
    for g in ("539", "f5", "m6"):
        a = analyse(g, data["games"][g])
        out["games"][g] = a
        for key in ("T1_S3_vs_B1", "T1_S4_vs_B1", "T2_S3_vs_B2", "T2_S4_vs_B2",
                    "T3_S3", "T3_S4", "T4_S3", "T4_S4", "T5_S3", "T5_S4"):
            tests.append((f"{g}:{key}", a[key].get("p")))
    adj, m = holm(tests)
    out["holm"] = {"nTests": m, "alpha": ALPHA,
                   "adjusted": {k: {"pAdj": v[0], "reject": v[1]}
                                for k, v in adj.items()}}
    path = os.path.join(HOME, "backtest_v3_stats.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
        return 0

    # ── 文字摘要 ──
    print(f"\n{'='*74}")
    print(f"回測結果｜Holm-Bonferroni 校正，共 {m} 次檢定，α={ALPHA}")
    print(f"{'='*74}")
    for g in ("539", "f5", "m6"):
        a = out["games"][g]
        print(f"\n■ {GAME_NAME[g]}（{a['nPeriods']} 期，歷史窗 "
              f"{a['histLen']['min']}~{a['histLen']['max']} 期）")
        print(f"  每期平均命中碼數（12 碼中）　理論 = {a['theory']['perPeriod']:.4f}")
        for t in ("S3", "S4", "B2", "B1"):
            v = a["totals"][t]
            d = (v["perPeriod"] / a["theory"]["perPeriod"] - 1) * 100
            print(f"    {t}: {v['perPeriod']:.4f}  ({d:+.2f}% vs 理論)"
                  f"　三碼全中 {a['jackpot'][t]} 次")
        print("  ── 檢定 ──")
        for key, label in (("T1_S3_vs_B1", "T1 S3 vs B1（規則淨效果）"),
                           ("T1_S4_vs_B1", "T1 S4 vs B1"),
                           ("T2_S3_vs_B2", "T2 S3 vs B2（fpx-v3 淨效果）"),
                           ("T2_S4_vs_B2", "T2 S4 vs B2（fpx-v4 淨效果）")):
            r = a[key]
            pa = adj[f"{g}:{key}"][0]
            mark = "🔴顯著" if adj[f"{g}:{key}"][1] else "不顯著"
            pv = f"{r['p']:.4f}" if r["p"] is not None else "—"
            paj = f"{pa:.4f}" if pa is not None else "—"
            print(f"    {label:<28} 均差={r['meanDiff']:+.4f} "
                  f"p={pv} p_adj={paj} {mark}")
        for tag in ("S3", "S4"):
            r = a[f"T3_{tag}"]
            k = f"{g}:T3_{tag}"
            mark = "🔴顯著" if adj[k][1] else "不顯著"
            if r["n"] == 0:
                print(f"    T3 排除區命中 {tag:<20} 排除區恆空，無法檢定")
                continue
            ci = f"[{r['ci'][0]*100:.2f}%,{r['ci'][1]*100:.2f}%]"
            pv = f"{r['p']:.4f}" if r["p"] is not None else "—"
            paj = f"{adj[k][0]:.4f}" if adj[k][0] is not None else "—"
            print(f"    T3 排除區 {tag:<8} {r['x']}/{r['n']}={r['rate']*100:.2f}% "
                  f"vs 理論 {r['p0']*100:.2f}% CI{ci} p={pv} p_adj={paj} {mark}"
                  f"｜均 {r['avgSize']:.2f} 顆/期、空 {r['zeroRate']*100:.1f}%")
        for tag in ("S3", "S4"):
            for T in ("T4", "T5"):
                r = a[f"{T}_{tag}"]
                k = f"{g}:{T}_{tag}"
                mark = "🔴顯著" if adj[k][1] else "不顯著"
                paj = f"{adj[k][0]:.4f}" if adj[k][0] is not None else "—"
                nm = "T4 號碼均勻度" if T == "T4" else "T5 命中數分佈"
                print(f"    {nm} {tag:<6} χ²={r['stat']:.1f} df={r['df']} "
                      f"p={r['p']:.4f} p_adj={paj} {mark}")
        d3, d4 = a["drift_S3"], a["drift_S4"]
        print("  ── 排除區漂移（短窗 <1000 期 vs 長窗 ≥1000 期）──")
        for tag, d in (("S3(v3)", d3), ("S4(v4)", d4)):
            s, l = d["short"], d["long"]
            if s and l:
                print(f"    {tag}: 短窗 {s['avgSize']:.2f} 顆/空{s['zeroRate']*100:.0f}%"
                      f"　→　長窗 {l['avgSize']:.2f} 顆/空{l['zeroRate']*100:.0f}%")
    print(f"\n→ 已寫入 backtest_v3_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
