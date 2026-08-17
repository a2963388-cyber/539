#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""return_gap_stats — 回歸間隔統計（今年）
==========================================
問題：每期開出的號碼，隔幾期後再次開出？依次數由多到少排序。

定義（口語版，與平坦度圖的 g 差 1，見下）：
    號碼在第 i 期開出、下次在第 j 期開出 ⇒ 記為「**{j-i} 期後回歸**」
    ・1 期後回歸 ＝ 連續兩期都開出
    ・pick_engine 平坦度圖的 g（沉寂深度）＝ 本表的「期後」− 1

右設限：今年最後幾期開出的號碼可能還沒回歸，這些**不計入分佈**，
        但會回報數量 —— 不處理它會系統性低估長間隔。

六合彩雙口徑（2026-08-16 鈞洋澄清）：
    主6   ＝只算主 6 碼（與產線平坦度圖一致）
    含特  ＝主 6 碼 ＋ 特別號（「號碼到底有沒有開出」的口徑）
    539 / F5 無特別號，兩者相同。

理論對照：單一號碼每期出現率 p = draw/pool，回歸間隔近似幾何分佈
          P(k 期後) = (1-p)^(k-1) × p
          （近似原因：每期恰開 d 個不重複號，嚴格說是超幾何而非獨立伯努利，
            但對單一號碼的邊際行為，幾何近似誤差極小）

用法：python3 return_gap_stats.py [--year 2026] [--html]
"""

import json
import os
import sys
from collections import Counter

HOME = os.path.dirname(os.path.abspath(__file__))
GAMES = {
    "539": {"file": "backtest_data_539.json", "pool": 39, "draw": 5,
            "name": "今彩539", "year_key": lambda r, y: r["p"] >= (y - 1911) * 1000 + 1},
    "f5":  {"file": "backtest_data_f5.json", "pool": 39, "draw": 5,
            "name": "Fantasy 5", "year_key": lambda r, y: (r.get("dt") or "") >= f"{y}-01-01"},
    "m6":  {"file": "backtest_data_m6.json", "pool": 49, "draw": 6,
            "name": "香港六合彩", "year_key": lambda r, y: r["p"] >= (y - 2000) * 1000 + 1},
}


def load(game, year):
    rows = json.load(open(os.path.join(HOME, GAMES[game]["file"]), encoding="utf-8"))
    sel = [r for r in rows if GAMES[game]["year_key"](r, year)]
    sel.sort(key=lambda r: r["p"])          # 舊 → 新
    return sel


def nums_of(r, with_special):
    if with_special and r.get("e"):
        return sorted(set(r["n"]) | {r["e"]})
    return r["n"]


def gap_stats(rows, with_special=False):
    """回傳 (Counter{期後: 次數}, 尚未回歸數, 總樣本數)。"""
    sets = [set(nums_of(r, with_special)) for r in rows]
    cnt, censored = Counter(), 0
    for i in range(len(sets)):
        for n in sets[i]:
            for j in range(i + 1, len(sets)):
                if n in sets[j]:
                    cnt[j - i] += 1
                    break
            else:
                censored += 1                # 到今年最後一期仍未回歸
    return cnt, censored, sum(cnt.values())


def theory(k, pool, draw):
    p = draw / pool
    return (1 - p) ** (k - 1) * p


def chi2_fit(cnt, total, pool, draw, kmax=20):
    """卡方適合度：實測分佈 vs 幾何理論。

    只取 k <= kmax（右設限主要影響長間隔區，納入會製造假的偏離），
    並把尾巴併成一格，確保每格期望值足夠大。
    """
    import backtest_stats as bs
    obs, exp, labels = [], [], []
    for k in range(1, kmax + 1):
        obs.append(cnt.get(k, 0))
        exp.append(theory(k, pool, draw) * total)
        labels.append(str(k))
    tail_obs = sum(c for k, c in cnt.items() if k > kmax)
    tail_exp = total - sum(exp)
    if tail_exp > 5:
        obs.append(tail_obs)
        exp.append(tail_exp)
        labels.append(f">{kmax}")
    r = bs.chi2_gof(obs, exp)
    return r, labels, obs, exp


def report(game, year, with_special=False):
    cfg = GAMES[game]
    rows = load(game, year)
    cnt, censored, total = gap_stats(rows, with_special)
    draw = cfg["draw"] + (1 if (with_special and game == "m6") else 0)
    tag = "含特別號" if with_special else ("主6碼" if game == "m6" else "")
    print(f"\n{'='*70}")
    print(f"■ {cfg['name']}{('（' + tag + '）') if tag else ''}"
          f"　{year} 年 {len(rows)} 期　樣本 {total} 筆"
          f"（另有 {censored} 個號碼到年底仍未回歸，未計入）")
    print(f"  單號每期出現率 p = {draw}/{cfg['pool']} = {draw/cfg['pool']*100:.2f}%"
          f"　平均回歸間隔理論值 {cfg['pool']/draw:.2f} 期")
    print(f"{'='*70}")
    print(f"  {'排名':>3} {'幾期後回歸':>10} {'次數':>6} {'佔比':>8} {'理論佔比':>9} {'差異':>8}")
    print("  " + "-" * 60)
    for rank, (k, c) in enumerate(sorted(cnt.items(), key=lambda x: (-x[1], x[0])), 1):
        obs = c / total
        th = theory(k, cfg["pool"], draw)
        print(f"  {rank:>3} {k:>8} 期 {c:>7} {obs*100:>7.2f}% {th*100:>8.2f}%"
              f" {(obs-th)*100:>+7.2f}%")
    vals = sorted(k for k, c in cnt.items() for _ in range(c))
    mean = sum(k * c for k, c in cnt.items()) / total
    print("  " + "-" * 60)
    print(f"  實測平均 {mean:.2f} 期　中位數 {vals[len(vals)//2]} 期　"
          f"最長 {max(cnt)} 期　理論平均 {cfg['pool']/draw:.2f} 期")
    print(f"  ⚠️ 實測平均必然偏低：{censored} 個尚未回歸的號碼都是長間隔，被排除了")
    r, *_ = chi2_fit(cnt, total, cfg["pool"], draw)
    verdict = "與理論無異 ✅" if r["p"] >= 0.05 else "🔴 顯著偏離理論"
    print(f"  卡方適合度（k≤20，避開設限區）：χ²={r['stat']:.1f} df={r['df']} "
          f"p={r['p']:.4f} → {verdict}")
    return cnt, total, censored, r


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1a1d21;--mut:#5c6570;--line:#e3e6ea;
--ok:#0a7d40;--bad:#c2262e;--warn:#9a6400;--accent:#2a5fd6;--code:#f0f2f5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#14171a;--card:#1c2024;--fg:#e6e9ec;--mut:#9aa4ae;--line:#2c3238;
--ok:#4ec27f;--bad:#ff6b6b;--warn:#e0a33a;--accent:#6f9cf5;--code:#22272c}}
:root[data-theme=dark]{--bg:#14171a;--card:#1c2024;--fg:#e6e9ec;--mut:#9aa4ae;
--line:#2c3238;--ok:#4ec27f;--bad:#ff6b6b;--warn:#e0a33a;--accent:#6f9cf5;--code:#22272c}
*{box-sizing:border-box}
body{margin:0;padding:20px 14px 60px;background:var(--bg);color:var(--fg);
font:15px/1.6 -apple-system,"PingFang TC",sans-serif}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:30px 0 8px;
padding-top:14px;border-top:1px solid var(--line)}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:13px 15px;margin:11px 0;font-size:13.5px}
.warnbox{background:rgba(224,163,58,.1);border-left:3px solid var(--warn);
padding:11px 14px;border-radius:0 7px 7px 0;margin:12px 0;font-size:13.5px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:460px}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600;font-size:12px}
.mono{font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
.pos{color:var(--ok)}.neg{color:var(--bad)}
.bar{display:inline-block;height:8px;background:var(--accent);opacity:.45;
border-radius:2px;vertical-align:middle}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600}
.t-ok{background:rgba(78,194,127,.16);color:var(--ok)}
.foot{color:var(--mut);font-size:12px;margin-top:32px;border-top:1px solid var(--line);padding-top:12px}
"""


def build_html(year, blocks):
    h = ['<div class="wrap">', f'<h1>回歸間隔統計 · {year} 年</h1>',
         '<div class="sub">每期開出的號碼，隔幾期後再次開出 · 依次數由多到少排序</div>']
    h.append('<div class="warnbox"><b>看這張表之前必須知道的兩件事</b><br>'
             '① <b>「1 期後」排最前面是理論必然，不是發現。</b> 回歸間隔服從幾何分佈 '
             'P(k)=(1−p)<sup>k−1</sup>×p，本來就<b>單調遞減</b> —— 越短的間隔次數越多是數學保證的。'
             '真正該看的是「實測佔比 vs 理論佔比」那兩欄有沒有系統性偏離。<br>'
             '② <b>實測平均必然低於理論平均。</b> 到年底還沒回歸的號碼（右設限）全是長間隔，'
             '被排除在分佈之外，所以平均被壓低。這是統計方法的必然，不是彩券的性質。</div>')
    for b in blocks:
        h.append(f'<h2>{b["title"]}</h2>')
        r = b["chi"]
        verdict = ('<span class="tag t-ok">與理論無異</span>' if r["p"] >= 0.05
                   else '<span class="tag" style="background:rgba(255,107,107,.16);color:var(--bad)">顯著偏離</span>')
        h.append(f'<div class="card">{year} 年 <b>{b["periods"]}</b> 期，樣本 <b>{b["total"]}</b> 筆'
                 f'（另有 {b["censored"]} 個號碼到年底仍未回歸，未計入）<br>'
                 f'單號每期出現率 {b["draw"]}/{b["pool"]} = {b["p"]*100:.2f}%'
                 f'　理論平均間隔 <b>{b["pool"]/b["draw"]:.2f}</b> 期'
                 f'　實測平均 {b["mean"]:.2f} 期　中位數 {b["median"]} 期　最長 {b["maxk"]} 期<br>'
                 f'卡方適合度（k≤20，避開設限區）：χ²={r["stat"]:.1f} df={r["df"]} '
                 f'p={r["p"]:.4f} → {verdict}</div>')
        h.append('<div class="scroll"><table><tr><th>排名</th><th>幾期後回歸</th>'
                 '<th>次數</th><th>佔比</th><th>理論佔比</th><th>差異</th><th></th></tr>')
        mx = b["rows"][0][1] if b["rows"] else 1
        for rank, (k, c, obs, th) in enumerate(b["rows"], 1):
            d = obs - th
            cls = "pos" if d > 0 else "neg"
            w = int(c / mx * 90)
            h.append(f'<tr><td>{rank}</td><td><b>{k}</b> 期</td>'
                     f'<td class="mono">{c}</td><td class="mono">{obs*100:.2f}%</td>'
                     f'<td class="mono" style="color:var(--mut)">{th*100:.2f}%</td>'
                     f'<td class="mono {cls}">{d*100:+.2f}%</td>'
                     f'<td><span class="bar" style="width:{w}px"></span></td></tr>')
        h.append('</table></div>')
    h.append('<div class="foot">「幾期後回歸」＝下次開出距離本期的期數；1 期後＝連續兩期都開。'
             '　平坦度圖的沉寂深度 g ＝ 本表期數 − 1。<br>'
             '六合彩兩種口徑：主6＝只算主 6 碼（與產線平坦度圖一致）；'
             '含特＝主 6 碼＋特別號（「號碼有沒有開出」的口徑）。<br>'
             '產生：<span class="mono">return_gap_stats.py</span>'
             '　誠實揭露：分佈符合理論不代表可預測；單列的高低是抽樣噪音，'
             '不足以推論「這個間隔比較容易出」。</div></div>')
    return ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>回歸間隔統計</title><style>{CSS}</style></head><body>'
            + "\n".join(h) + '</body></html>')


def collect(game, year, with_special=False):
    cfg = GAMES[game]
    rows = load(game, year)
    cnt, censored, total = gap_stats(rows, with_special)
    draw = cfg["draw"] + (1 if (with_special and game == "m6") else 0)
    ordered = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))
    vals = sorted(k for k, c in cnt.items() for _ in range(c))
    r, *_ = chi2_fit(cnt, total, cfg["pool"], draw)
    tag = "含特別號" if with_special else ("主6碼" if game == "m6" else "")
    return {"title": cfg["name"] + (f"（{tag}）" if tag else ""),
            "periods": len(rows), "total": total, "censored": censored,
            "pool": cfg["pool"], "draw": draw, "p": draw / cfg["pool"],
            "mean": sum(k * c for k, c in cnt.items()) / total,
            "median": vals[len(vals) // 2], "maxk": max(cnt), "chi": r,
            "rows": [(k, c, c / total, theory(k, cfg["pool"], draw))
                     for k, c in ordered]}


def main(argv):
    year = 2026
    if "--year" in argv:
        year = int(argv[argv.index("--year") + 1])
    if "--html" in argv:
        blocks = [collect("539", year), collect("f5", year),
                  collect("m6", year, False), collect("m6", year, True)]
        out = os.path.join(HOME, "return_gap_report.html")
        open(out, "w", encoding="utf-8").write(build_html(year, blocks))
        print(f"→ 已寫入 {os.path.basename(out)}")
        return 0
    for g in ("539", "f5"):
        report(g, year)
    report("m6", year, with_special=False)
    report("m6", year, with_special=True)
    print("\n※ 「幾期後回歸」＝ 下次開出距離本期的期數；1 期後＝連續兩期都開。")
    print("※ 平坦度圖的沉寂深度 g ＝ 本表期數 − 1。")
    print("※ 佔比與理論的差異屬抽樣噪音，樣本越小（尤其六合 89 期）波動越大；")
    print("  勿據單一列的高低推論「這個間隔比較容易出」。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
