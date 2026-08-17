#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coldest_notout_test — 「買最冷的 N 碼賭不出」直接實證
==========================================================
鈞洋 2026-08-17 提問：「沉寂越久的號碼開出機率確實很低，長期這樣買有沒有正期望？」

hazard_test.py 從機率結構回答（無記憶性）；本檔從**下注結果**直接回答：
    每期挑出當時沉寂最久的 N 個號碼，賭它們全部不出，統計長期勝率。

三種挑法（同期同資料，可直接比較）：
    COLD    當期沉寂最久的 N 碼（＝鈞洋的策略）
    HOT     當期最近才開過的 N 碼（反向對照）
    RANDOM  每期隨機挑 N 碼（決定性種子，可複驗）

若「越冷越不容易開」為真 ⇒ COLD 的勝率應**顯著高於** RANDOM 與理論值。
判定含特別號與否依彩種：539/F5 無特別號；六合用「出現」口徑（含特碼）。

用法：python3 coldest_notout_test.py [N ...]     # 預設 5 6 10
"""

import json
import os
import sys
import random
from math import comb, sqrt, erf

HOME = os.path.dirname(os.path.abspath(__file__))
GAMES = {"539": ("backtest_data_539.json", 39, 5, "今彩539", False),
         "f5": ("backtest_data_f5.json", 39, 5, "Fantasy 5", False),
         "m6": ("backtest_data_m6.json", 49, 6, "香港六合彩", True)}
WARMUP = 100


def norm_p(z):
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def run(game, N):
    fn, pool, draw, name, use_e = GAMES[game]
    rows = sorted(json.load(open(os.path.join(HOME, fn), encoding="utf-8")),
                  key=lambda r: r["p"])
    appeared = []
    for r in rows:
        s = set(r["n"])
        if use_e and r.get("e"):
            s.add(r["e"])
        appeared.append(s)
    eff_draw = draw + (1 if use_e else 0)
    theory = comb(pool - N, eff_draw) / comb(pool, eff_draw)

    gap = {n: 10 ** 6 for n in range(1, pool + 1)}   # 未出現過視為最冷
    rnd = random.Random(20260817)
    stat = {"COLD": 0, "HOT": 0, "RANDOM": 0}
    n_eval = 0
    for i, s in enumerate(appeared):
        if i >= WARMUP:
            order = sorted(range(1, pool + 1), key=lambda n: (-gap[n], n))
            cold = set(order[:N])
            hot = set(sorted(range(1, pool + 1), key=lambda n: (gap[n], n))[:N])
            rand = set(rnd.sample(range(1, pool + 1), N))
            for tag, pick in (("COLD", cold), ("HOT", hot), ("RANDOM", rand)):
                if not (pick & s):
                    stat[tag] += 1
            n_eval += 1
        for n in range(1, pool + 1):
            gap[n] = 0 if n in s else gap[n] + 1

    print(f"\n■ {name}　買最冷的 {N} 碼賭「全不出」　{n_eval} 期"
          f"　理論勝率 {theory*100:.3f}%")
    print(f"  {'挑法':<8}{'贏':>7}{'勝率':>10}{'vs理論':>10}{'Z':>8}{'p':>9}"
          f"{'保本賠率':>10}")
    for tag in ("COLD", "RANDOM", "HOT"):
        w = stat[tag]
        r = w / n_eval
        z = (r - theory) / sqrt(theory * (1 - theory) / n_eval)
        lbl = {"COLD": "最冷N碼", "RANDOM": "隨機", "HOT": "最熱N碼"}[tag]
        print(f"  {lbl:<8}{w:>7}{r*100:>9.2f}%{(r-theory)*100:>+9.2f}%"
              f"{z:>+8.2f}{norm_p(z):>9.4f}{1/r if r else 0:>10.3f}")
    # 效力：本樣本能偵測多大的相對優勢
    sd = sqrt(theory * (1 - theory) / n_eval)
    print(f"  ⚠️ 效力：本樣本僅能偵測 ±{2*sd/theory*100:.1f}% 的相對差異")
    return theory, stat, n_eval


def main(argv):
    Ns = [int(a) for a in argv if a.isdigit()] or [5, 6, 10]
    print("問題：每期挑「沉寂最久的 N 碼」賭全不出，長期是否優於隨機挑？")
    print("（若『越冷越不容易開』成立，COLD 應顯著高於 RANDOM 與理論值）")
    for N in Ns:
        print(f"\n{'='*74}\nN = {N}\n{'='*74}")
        for g in ("539", "f5", "m6"):
            run(g, N)
    print("\n※ 六合判定含特別號（『號碼有沒有開出』口徑）；539/F5 無特別號。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
