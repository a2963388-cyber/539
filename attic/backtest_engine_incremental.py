#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_engine — 增量式歷史推進（P0-2）
==============================================
全歷史回測的效能瓶頸在 pick_engine.build_return_dist / current_gaps：
兩者皆為 O(L)，而回測需對每一期重算 → O(L²)。539 有 5942 期，
三彩種 × 四條對照線根本跑不完。

本模組把兩者改成**由舊往新逐期推進的 O(1) 增量更新**，總複雜度降為 O(L)。

🔴 這等同於重寫規格的一部分，因此設有不可跳過的閘門：
   `python3 backtest_engine.py --parity` 對三彩種各抽 300 期，
   比對增量版與 pick_engine 現行實作的
   (excluded, excl_depths, readmit_order) 三元組**逐位元相同**。
   對拍不過即不得用於回測（退回慢版並縮小樣本）。

── 增量推導（records 新→舊，index 0 為最新）─────────────────────
原版 build_return_dist：對 records[i] 的每個號碼 n，往「更新」方向
（j = i-1 … 0）找下一次出現，gap = i - j - 1，dist[gap] += 1。

換成由舊往新加入新期 r 的視角：
  設 n ∈ r，且 n 在加入前的沉寂深度為 gaps[n]（= n 最近出現的 index）。
  加入後 r 成為 index 0、原本的 index g 變成 g+1，
  故該次回歸的 gap = (g+1) - 0 - 1 = g = 加入前的 gaps[n]。
  ⇒ dist[gaps_before[n]] += 1，且**僅當 n 先前出現過**（原版靠 break 保證）。

current_gaps：加入 r 後，n ∈ r → 0，否則 +1。
  「從未出現」原版給 len(records)；增量版自 0 起累加恰為已加入期數，數值一致，
  但是否計入 dist 必須另用 seen 集合判斷，不可用數值反推。
"""

import json
import os
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

import pick_engine as pe  # noqa: E402
from pick_engine import GAMES, ATRISK_MIN, EXCL_BARS  # noqa: E402

DATA_FILE = {"539": "backtest_data_539.json",
             "f5": "backtest_data_f5.json",
             "m6": "backtest_data_m6.json"}


def load(game):
    """讀 build_backtest_data.py 產出的統一資料（新→舊）。"""
    path = os.path.join(HOME, DATA_FILE[game])
    if not os.path.exists(path):
        raise SystemExit(f"缺 {DATA_FILE[game]}，請先跑 build_backtest_data.py")
    return json.load(open(path, encoding="utf-8"))


class HistoryState:
    """由舊往新推進的回歸間隔狀態。push() 後即代表「已含這期」的歷史。"""

    def __init__(self, pool_max):
        self.pool_max = pool_max
        self.dist = {}
        self.gaps = {n: 0 for n in range(1, pool_max + 1)}
        self.seen = set()
        self.n_records = 0

    def push(self, nums):
        nums = set(nums)
        for n in nums:
            if n in self.seen:                      # 僅先前出現過才產生回歸樣本
                g = self.gaps[n]
                self.dist[g] = self.dist.get(g, 0) + 1
        for n in range(1, self.pool_max + 1):
            self.gaps[n] = 0 if n in nums else self.gaps[n] + 1
        self.seen |= nums
        self.n_records += 1

    def snapshot(self):
        return dict(self.dist), dict(self.gaps)


def flatness_exclude_fast(game, dist, gaps):
    """fpx-v3 排除區，直接吃 (dist, gaps)。

    ⚠️ 本函式是 pick_engine.flatness_exclude 後半段的複製品（前半段的
    dist/gaps 計算已由 HistoryState 增量取代）。兩者必須永遠等價 ——
    這由 --parity 閘門每次執行時強制驗證，不靠人工同步。
    """
    cfg = GAMES[game]
    theory = cfg["draw"] / cfg["pool_max"]
    h_of = {}
    below = []
    for g in range(0, (max(dist) + 1) if dist else 0):
        at_risk = sum(c for k, c in dist.items() if k >= g)
        if at_risk < ATRISK_MIN:
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


def walk(game, warmup=500):
    """由舊往新推進，逐期 yield 一個可供「預測下一期」的狀態。

    yield (hist_head, target, dist, gaps)
        hist_head — 當時最新的一期（= seed 來源，對應 pick_engine 的 records[0]）
        target    — 緊接著要預測的那一期（含實際開獎號碼，用於兌獎）
    warmup 期之前只餵資料不產出（平坦度需 at_risk ≥ ATRISK_MIN，樣本太薄無意義）。
    """
    records = load(game)                     # 新→舊
    cfg = GAMES[game]
    st = HistoryState(cfg["pool_max"])
    oldest_first = list(reversed(records))   # 舊→新
    for i, rec in enumerate(oldest_first):
        st.push(rec["n"])
        if i + 1 <= warmup:
            continue
        if i + 1 >= len(oldest_first):
            break                            # 最後一期之後沒有 target 可兌
        target = oldest_first[i + 1]
        dist, gaps = st.snapshot()
        yield rec, target, dist, gaps


# ─────────────────────────── 對拍閘門 ───────────────────────────

def parity(game, samples=300, warmup=500):
    """比對增量版與 pick_engine 現行實作，要求三元組逐位元相同。

    取樣策略：等距抽 `samples` 期（決定性，不用亂數 —— 回測本身也須可重現）。
    """
    records = load(game)
    n = len(records)
    # 可比對的 target index 範圍：hist 至少 warmup 期 → records[k+1:] 長度 ≥ warmup
    valid = [k for k in range(0, n - warmup)]
    if not valid:
        print(f"[{game}] 樣本不足以對拍")
        return False
    step = max(1, len(valid) // samples)
    picks = set(valid[::step][:samples])

    st = HistoryState(GAMES[game]["pool_max"])
    oldest_first = list(reversed(records))
    ok = True
    checked = 0
    for i, rec in enumerate(oldest_first):
        st.push(rec["n"])
        k = n - 1 - i          # rec 在「新→舊」序中的 index
        if k - 1 not in picks:  # 預測的是 records[k-1]，用 hist = records[k:]
            continue
        hist = records[k:]
        dist, gaps = st.snapshot()
        fast = flatness_exclude_fast(game, dist, gaps)
        slow = pe.flatness_exclude(game, hist)
        checked += 1
        if fast != slow:
            ok = False
            print(f"[{game}] ❌ 期 {rec['p']} 不一致")
            print(f"    fast excluded={fast[0]}\n    slow excluded={slow[0]}")
            print(f"    fast depths={fast[1]}  slow depths={slow[1]}")
            if checked > 3:
                break
    print(f"[{game}] 對拍 {checked} 期：{'一致 ✅' if ok else '不一致 ❌'}")
    return ok


def main(argv):
    if "--parity" in argv:
        allok = True
        for g in ("539", "f5", "m6"):
            if not parity(g):
                allok = False
        print("PARITY", "PASS ✅" if allok else "FAIL ❌")
        return 0 if allok else 1
    print(__doc__)
    print("用法: backtest_engine.py --parity")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
