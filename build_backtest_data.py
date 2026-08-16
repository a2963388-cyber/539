#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_backtest_data — 回測資料整備（P0-1）
================================================
把 history_*.json（全歷史快照）與 data_*.js 的 BASE_REC（近期產線資料）
合併成統一格式，供 backtest.py 使用。**唯讀來源，不動任何產線檔案。**

統一格式（新→舊，與 BASE_REC 同序）：
    [{"p": <int 期號>, "n": [<開出主號 升冪>], "dt": "<YYYY-MM-DD 或 None>",
      "e": <六合彩特別號，其餘彩種無此欄>}, ...]

期號規則（三彩種一致，皆單調遞增，可直接當 seed）：
    539  官方 p           96001 ~ 115172（民國年*1000 + 序）
    f5   lottolyzer draw  5169 ~ 11939（流水號）
    m6   draw_str_to_p    "26/077" → 26077（yy*1000 + 序）
         ※ 實測 history_m6 全歷史為 2008-01-03 ~ 2026-07-16，年份前綴 08~26，
           不跨世紀，故 yy*1000+nnn 單調遞增可安全排序。

🔴 六合彩**雙口徑**（2026-08-16 鈞洋澄清）—— 故 `e` 欄位必須完整保留：
    [兌獎] 主 6 碼，特碼**不計**（與產線 build_log_entries 一致，維持不動）
    [出現] 主 6 ＋ 特碼 = 7 碼 —— 判斷號碼到底有沒有開出，供**不出牌／排除區**判定
    ※ 舊版只取 n 而丟棄 e，導致「N 不出」與排除區命中率無法正確計算。

資料完整性檢查（任一項失敗即非零退出，不產生輸出檔）：
    C1 兩來源對同一期號的開出號碼必須完全一致
    C2 期號不得重複
    C3 每期號碼數 == GAMES[game]["draw"]，且全部落在 1..pool_max
    C4 報告期號缺口（僅警示，不阻斷 —— 539 週日不開、六合每週三期，本就不連續）

用法：
    python3 build_backtest_data.py            # 三彩種全做
    python3 build_backtest_data.py 539 m6     # 只做指定彩種
"""

import json
import os
import re
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

from pick_engine import GAMES  # noqa: E402  彩種常數的唯一真相來源

HISTORY_FILE = {"539": "history_539.json",
                "f5": "history_f5.json",
                "m6": "history_m6.json"}
DATA_FILE = {"539": "data_539.js", "f5": "data_f5.js", "m6": "data_m6.js"}
OUT_FILE = {"539": "backtest_data_539.json",
            "f5": "backtest_data_f5.json",
            "m6": "backtest_data_m6.json"}


def draw_str_to_p(draw_str):
    """'26/067' → 26067。與 marksix_fetch.py:47 同一份邏輯（不可自行改寫）。"""
    parts = draw_str.split('/')
    return int(parts[0]) * 1000 + int(parts[1])


def load_history(game):
    """讀 history_*.json → {p: {"p","n","dt"}}。m6 需期號轉換。"""
    path = os.path.join(HOME, HISTORY_FILE[game])
    if not os.path.exists(path):
        print(f"  ⚠️ 找不到 {HISTORY_FILE[game]}，略過此來源")
        return {}
    rows = json.load(open(path, encoding="utf-8"))
    out = {}
    for r in rows:
        p = draw_str_to_p(r["draw"]) if game == "m6" else int(r["p"])
        rec = {"p": p, "n": sorted(r["n"]), "dt": r.get("dt")}
        if game == "m6":
            rec["e"] = r.get("e")          # 特別號：兌獎要算，不可丟
        out[p] = rec
    return out


def load_base_rec(game):
    """讀 data_*.js 的 BASE_REC → {p: {...}}。正則沿用 pick_engine._read_records。"""
    path = os.path.join(HOME, DATA_FILE[game])
    txt = open(path, encoding="utf-8").read()
    seg = re.search(r"BASE_REC\s*=\s*\[(.*?)\];", txt, re.S).group(1)
    out = {}
    for m in re.finditer(
            r"\{p:(\d+)(?:,draw:\"[^\"]*\")?(?:,dt:\"([^\"]*)\")?,n:\[([\d,]+)\]"
            r"(?:,e:(\d+))?", seg):
        p = int(m.group(1))
        rec = {"p": p,
               "n": sorted(int(x) for x in m.group(3).split(",")),
               "dt": m.group(2)}
        if game == "m6":
            rec["e"] = int(m.group(4)) if m.group(4) else None
        out[p] = rec
    return out


def merge(game, hist, base):
    """合併兩來源。C1：重疊期號的主號**與特別號**都必須一致，不一致即資料損毀，中止。"""
    conflicts = []
    merged = dict(hist)
    for p, row in base.items():
        old = merged.get(p)
        if old:
            if old["n"] != row["n"]:
                conflicts.append((p, old["n"], row["n"]))
            # 特別號同樣要對帳；任一邊缺值不算衝突，由下方 fallback 補
            if (game == "m6" and old.get("e") and row.get("e")
                    and old["e"] != row["e"]):
                conflicts.append((p, f"e={old['e']}", f"e={row['e']}"))
        # BASE_REC 是產線權威資料，重疊時以它為準；缺的欄位回頭向 history 取
        new = dict(row)
        if not new.get("dt") and old:
            new["dt"] = old.get("dt")
        if game == "m6" and not new.get("e") and old:
            new["e"] = old.get("e")
        merged[p] = new
    return merged, conflicts


def check(game, rows):
    """C2/C3 硬檢查 + C4 缺口警示。回傳 errors, gaps。"""
    cfg = GAMES[game]
    errors = []
    ps = [r["p"] for r in rows]
    if len(ps) != len(set(ps)):
        errors.append("C2 期號重複")
    for r in rows:
        if len(r["n"]) != cfg["draw"]:
            errors.append(f"C3 期 {r['p']} 號碼數 {len(r['n'])} != {cfg['draw']}")
        if len(set(r["n"])) != len(r["n"]):
            errors.append(f"C3 期 {r['p']} 有重複號碼")
        for n in r["n"]:
            if not (1 <= n <= cfg["pool_max"]):
                errors.append(f"C3 期 {r['p']} 號碼 {n} 超出 1..{cfg['pool_max']}")
        # C5（六合專屬）：特別號必須存在、在號域內、且不與主號重複
        if game == "m6":
            e = r.get("e")
            if not e:
                errors.append(f"C5 期 {r['p']} 缺特別號")
            elif not (1 <= e <= cfg["pool_max"]):
                errors.append(f"C5 期 {r['p']} 特別號 {e} 超出號域")
            elif e in r["n"]:
                errors.append(f"C5 期 {r['p']} 特別號 {e} 與主號重複")
    # C4：期號缺口（新→舊，故往下遞減）。跨年會有大跳號，只報同年內的缺口
    gaps = []
    for a, b in zip(ps, ps[1:]):
        if a // 1000 == b // 1000 and a - b > 1:   # 同年（f5 為同千位，僅粗略）
            gaps.append((b, a, a - b - 1))
    return errors, gaps


def build(game):
    print(f"\n== {game} ==")
    hist = load_history(game)
    base = load_base_rec(game)
    print(f"  history {len(hist)} 期｜BASE_REC {len(base)} 期"
          f"｜重疊 {len(set(hist) & set(base))} 期")

    merged, conflicts = merge(game, hist, base)
    if conflicts:
        print(f"  ❌ C1 兩來源號碼不一致 {len(conflicts)} 期（前 5 筆）：")
        for p, a, b in conflicts[:5]:
            print(f"     期 {p}: history={a}  BASE_REC={b}")
        return None

    rows = sorted(merged.values(), key=lambda r: -r["p"])
    errors, gaps = check(game, rows)
    if errors:
        print(f"  ❌ 完整性檢查失敗 {len(errors)} 項（前 5 項）：")
        for e in errors[:5]:
            print("     " + e)
        return None

    total_gap = sum(g[2] for g in gaps)
    print(f"  ✅ {len(rows)} 期  p {rows[-1]['p']} ~ {rows[0]['p']}"
          f"｜C1/C2/C3 全過｜同年缺口 {len(gaps)} 處共 {total_gap} 期")
    if gaps[:3]:
        print("     缺口樣本：" + ", ".join(f"{b}→{a}(缺{n})" for b, a, n in gaps[:3]))

    out = os.path.join(HOME, OUT_FILE[game])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  → 已寫入 {OUT_FILE[game]}")
    return rows


def main(argv):
    games = [g for g in argv[1:] if g in GAMES] or list(GAMES)
    ok = True
    for g in games:
        if build(g) is None:
            ok = False
    print("\nBUILD", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
