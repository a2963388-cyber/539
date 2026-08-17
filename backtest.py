#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest — sfg-v3 / fpx-v3 全歷史回測（依 BACKTEST_REGISTRY.md 執行）
=========================================================================
規格、判準、預先承諾的行動全部寫在 `BACKTEST_REGISTRY.md`，**跑之前已固定**。
本程式只負責產生數據，不做結論；統計檢定與報告在 backtest_stats.py。

五條對照線（見 REGISTRY §2）：
    S3  sfg-v3 ＋ fpx-v3（現行制度）
    S4  sfg-v3 ＋ fpx-v4（at_risk 相對門檻，見 REGISTRY §3）
    B2  sfg-v3，excluded = ∅
    B1  同種子同數列、**關閉全部過濾規則**（S−B1 ＝ 規則淨效果）
    B0  理論基準，解析計算不需模擬

歷史窗口：每期使用「該期之前的全部可用歷史」（累積窗），
          同時記錄窗長供事後分段分析。warmup = 500 期。

用法：
    python3 backtest.py --parity          # 對拍閘門（含 negative control，必須先過）
    python3 backtest.py --smoke           # 各彩種最近 300 期試跑
    python3 backtest.py                   # 全量，寫 backtest_v3_results.json
"""

import json
import os
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

import pick_engine as pe  # noqa: E402
from pick_engine import GAMES, ATRISK_MIN, EXCL_BARS  # noqa: E402

WARMUP = 500
V4_FRAC = 0.05          # fpx-v4：at_risk 門檻 = max(ATRISK_MIN, V4_FRAC × dist 總樣本)

# 🔴 六合彩有**兩個不同口徑**，絕不可混用（2026-08-16 鈞洋澄清）：
#
#   [兌獎] 特別號**不計**，只對主 6 碼 —— 與產線 build_log_entries 一致，維持不動。
#          用於 T1/T2/T5 的命中數與三碼全中。
#   [出現] 特別號**要計**，主 6 碼 ＋ 特碼共 7 碼 —— 判斷「這個號碼到底有沒有開出」，
#          用於排除區的命中判定（excludedHits）。
#
# ⚠️ 2026-08-16 稍早曾誤把兌獎也改成 7 碼，已更正回 6 碼。
SCORE_DRAW = {"539": 5, "f5": 5, "m6": 6}      # 兌獎口徑
APPEAR_DRAW = {"539": 5, "f5": 5, "m6": 7}     # 「有沒有出現」口徑
DATA_FILE = {"539": "backtest_data_539.json",
             "f5": "backtest_data_f5.json",
             "m6": "backtest_data_m6.json"}
OUT = "backtest_v3_results.json"


def load(game):
    path = os.path.join(HOME, DATA_FILE[game])
    if not os.path.exists(path):
        raise SystemExit(f"缺 {DATA_FILE[game]}，請先跑 build_backtest_data.py")
    return json.load(open(path, encoding="utf-8"))


# ───────────────── 排除區：把門檻參數化（v3 / v4 共用一份實作）─────────────────

def select_exclude(game, dist, gaps, atrisk_min):
    """pick_engine.flatness_exclude 的後半段，唯一差異是 at_risk 門檻可調。

    ⚠️ 這是複製品。與 pick_engine 本尊的等價性由 --parity 每次強制驗證，
       且該閘門本身通過 negative control（故意破壞必須被抓到）才算數。
    """
    cfg = GAMES[game]
    theory = cfg["draw"] / cfg["pool_max"]
    h_of = {}
    below = []
    for g in range(0, (max(dist) + 1) if dist else 0):
        at_risk = sum(c for k, c in dist.items() if k >= g)
        if at_risk < atrisk_min:
            break
        h = dist.get(g, 0) / at_risk
        h_of[g] = h
        if h < theory:
            below.append((h, g, sorted(n for n, gg in gaps.items() if gg == g)))
    below.sort(key=lambda t: (t[0], t[1]))
    excluded, excl_depths = [], []
    for h, g, nums in below[:EXCL_BARS]:
        excl_depths.append(g)
        excluded.extend(nums)
    excluded.sort()
    excl_depths.sort()
    readmit = sorted(excluded, key=lambda n: (-h_of.get(gaps[n], theory), gaps[n], n))
    return excluded, excl_depths, readmit


def v4_threshold(dist):
    """fpx-v4 門檻：max(ATRISK_MIN, V4_FRAC × 總樣本)。"""
    return max(ATRISK_MIN, V4_FRAC * sum(dist.values()))


# ───────────────── B1：關閉全部過濾規則的裸抽 ─────────────────

def bare_groups(game, last_period):
    """同種子、同 Lehmer 數列，連續取 12 個不重複號，依序切成 A/B/C/D。

    不套用 R2/R3/R4/G2/G3、不扣排除區 —— 這正是「規則淨效果」的對照。
    """
    cfg = GAMES[game]
    rng = pe.Lehmer(pe.derive_seed(last_period, cfg["salt"]))
    nums = []
    for _ in range(20000):
        n = rng.next_num(cfg["pool_max"])
        if n not in nums:
            nums.append(n)
            if len(nums) == 12:
                break
    return {k: sorted(nums[i * 3:i * 3 + 3]) for i, k in enumerate("ABCD")}


def winning_nums(game, rec):
    """**兌獎**用的開出號碼。六合＝主 6 碼，特別號不計（與產線一致）。"""
    return rec["n"]


def appeared_nums(game, rec):
    """**「有沒有出現」**用的號碼。六合＝主 6 碼 ＋ 特別號，供排除區命中判定。"""
    if game == "m6":
        e = rec.get("e")
        if not e:
            raise ValueError(f"m6 期 {rec['p']} 缺特別號，出現口徑無法成立")
        return sorted(rec["n"] + [e])
    return rec["n"]


def score(groups, draw):
    """兌獎。draw 須為 winning_nums() 的輸出（六合已含特別號）。"""
    ds = set(draw)
    return {k: len(set(g) & ds) for k, g in groups.items()}


# ───────────────── 對拍閘門（含 negative control）─────────────────

def parity(game, samples=200, sabotage=None):
    """比對 select_exclude(v3 門檻) 與 pick_engine.flatness_exclude 是否逐位元相同。

    sabotage: 測試用，故意破壞的函式，用來確認閘門真的抓得到錯。
    """
    recs = load(game)
    n = len(recs)
    valid = [k for k in range(1, n - WARMUP)]
    if not valid:
        print(f"[{game}] 樣本不足")
        return False
    step = max(1, len(valid) // samples)
    picks = valid[::step][:samples]
    ok, checked = True, 0
    for k in picks:
        hist = recs[k:]
        dist = pe.build_return_dist(hist)
        gaps = pe.current_gaps(hist, GAMES[game]["pool_max"])
        if sabotage:
            dist, gaps = sabotage(dist, gaps)
        fast = select_exclude(game, dist, gaps, ATRISK_MIN)
        slow = pe.flatness_exclude(game, hist)
        checked += 1
        if fast != slow:
            ok = False
            if checked <= 2 and not sabotage:
                print(f"[{game}] ❌ 期 {recs[k]['p']} 不一致")
                print(f"    本檔 excluded={fast[0]} depths={fast[1]}")
                print(f"    本尊 excluded={slow[0]} depths={slow[1]}")
    if not sabotage:
        print(f"[{game}] 對拍 {checked} 期：{'一致 ✅' if ok else '不一致 ❌'}")
    return ok


def parity_gate():
    """完整閘門：先確認閘門會抓錯（negative control），再確認本尊一致。"""
    print("── Step 1：negative control（故意破壞，閘門必須 FAIL）──")
    def sab(dist, gaps):
        d = dict(dist)
        for g in list(d)[:6]:          # 明確破壞：前 6 個深度樣本砍半
            d[g] = max(1, d[g] // 2)
        return d, gaps
    caught = True
    for g in ("539", "f5", "m6"):
        detected = not parity(g, samples=60, sabotage=sab)
        print(f"  [{g}] 破壞後被抓到：{'是 ✅' if detected else '否 🚨'}")
        if not detected:
            caught = False
    if not caught:
        print("🚨 閘門本身失效（抓不到已知錯誤），不得採信後續結果")
        return False

    print("\n── Step 2：與 pick_engine 本尊對拍 ──")
    allok = all(parity(g) for g in ("539", "f5", "m6"))
    print("\nPARITY", "PASS ✅" if allok else "FAIL ❌")
    return allok


# ───────────────────────────── 回測主體 ─────────────────────────────

def run_game(game, limit=None, progress_every=500):
    """回傳該彩種的逐期結果。limit 給 smoke test 用（只跑最近 N 期）。"""
    cfg = GAMES[game]
    recs = load(game)                       # 新→舊
    n = len(recs)
    # target index k（新→舊），hist = recs[k+1:]，需 len(hist) >= WARMUP
    targets = [k for k in range(0, n - WARMUP - 1)]
    targets.sort()                           # k 小 = 新
    if limit:
        targets = targets[:limit]
    targets.sort(reverse=True)               # 由舊往新跑，進度好讀

    rows = []
    t0 = time.time()
    for idx, k in enumerate(targets):
        target = recs[k]
        hist = recs[k + 1:]
        seed = hist[0]["p"]
        dist = pe.build_return_dist(hist)
        gaps = pe.current_gaps(hist, cfg["pool_max"])

        ex3, dep3, rd3 = select_exclude(game, dist, gaps, ATRISK_MIN)
        ex4, dep4, rd4 = select_exclude(game, dist, gaps, v4_threshold(dist))

        lines = {}
        for tag, ex, rd in (("S3", ex3, rd3), ("S4", ex4, rd4), ("B2", [], [])):
            res = pe.gen_four_groups(game, seed, hist[0]["n"],
                                     excluded=ex, readmit_order=rd)
            lines[tag] = {"g": res["strategies"], "hi": res["hi"],
                          "relaxed": res["relaxed"], "excl": res["excluded"]}
        lines["B1"] = {"g": bare_groups(game, seed), "hi": None,
                       "relaxed": [], "excl": []}

        win = winning_nums(game, target)       # 兌獎：六合＝主 6 碼
        appeared = appeared_nums(game, target)  # 出現：六合＝主 6 ＋ 特碼
        row = {"p": target["p"], "seed": seed, "histLen": len(hist),
               "draw": win, "appeared": appeared, "lines": {}}
        for tag, ln in lines.items():
            hits = score(ln["g"], win)
            row["lines"][tag] = {
                "groups": ln["g"],
                "hits": hits,
                "total": sum(hits.values()),
                "relaxed": ln["relaxed"],
                "nExcl": len(ln["excl"]),
                # 排除區「命中」＝該號有出現，故用**出現口徑**（六合含特碼），
                # 不是兌獎口徑：這裡問的是「號碼到底有沒有開出」。
                "exclHits": len(set(ln["excl"]) & set(appeared)),
            }
        rows.append(row)

        if progress_every and (idx + 1) % progress_every == 0:
            el = time.time() - t0
            print(f"  [{game}] {idx+1}/{len(targets)} 期  {el:.0f}s"
                  f"  (剩約 {el/(idx+1)*(len(targets)-idx-1):.0f}s)", flush=True)

    print(f"  [{game}] 完成 {len(rows)} 期，耗時 {time.time()-t0:.0f}s", flush=True)
    return rows


def main(argv):
    if "--parity" in argv:
        return 0 if parity_gate() else 1

    smoke = "--smoke" in argv
    limit = 300 if smoke else None

    print(f"== 回測開始（{'smoke 300 期' if smoke else '全量'}）==")
    print("依 BACKTEST_REGISTRY.md 執行；warmup =", WARMUP)
    if not smoke:
        print("\n[閘門] 先跑對拍，不過就不跑回測")
        if not parity_gate():
            return 1
    print()

    out = {"meta": {"warmup": WARMUP, "v4Frac": V4_FRAC,
                    "algo": pe.ALGO, "exclBars": EXCL_BARS,
                    "atRiskMin": ATRISK_MIN, "smoke": smoke},
           "games": {}}
    for g in ("539", "f5", "m6"):
        print(f"== {g} ==")
        out["games"][g] = run_game(g, limit=limit)

    if not smoke:
        path = os.path.join(HOME, OUT)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        print(f"\n→ 已寫入 {OUT}")
    else:
        # smoke 只印摘要，不落檔
        for g, rows in out["games"].items():
            print(f"\n[{g}] {len(rows)} 期摘要")
            for tag in ("S3", "S4", "B2", "B1"):
                tot = sum(r["lines"][tag]["total"] for r in rows)
                ne = sum(r["lines"][tag]["nExcl"] for r in rows)
                eh = sum(r["lines"][tag]["exclHits"] for r in rows)
                print(f"  {tag}: 總命中 {tot:>5} 碼"
                      f"（{tot/len(rows):.3f}/期）｜排除區 {ne} 顆中 {eh} 顆開出")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
