#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pick_engine — 期號種子可重現選號引擎（sfg-v2）＋ fpx-v2 不出牌排除區
=================================================

事前註冊：sfg-v1 2026-08-09、sfg-v2/fpx-v2 2026-08-12（鈞洋拍板）。本檔即規格本身，
任何人可依下述規則獨立重實作並得到逐位元相同的結果。

目標
----
每彩種每期產生 4 組 × 3 碼（組名 A/B/C/D，共 12 碼互不重複），
取代舊制 8-10 個策略 × 8 碼。

誠實揭露（不可刪除）
--------------------
選號不改變中獎機率。本引擎提供的是：
1. 可重現性 —— 期號當種子，事後不可能挑好看的說是預測；
2. 反熱門結構 —— 避開人類超簽的組合形態（生日區、等差、同尾），
   在「分彩池」玩法中可望降低撞號、提高中獎時的條件賠付；
   在「固定賠率」玩法中僅具紀律價值；
3. 紀律 —— 每期固定 4 組，控制成本。

規格（sfg-v2；與 v1 的差異＝候選池再排除 fpx-v2 不出牌區＋高號預算）
--------------
彩種常數：
    game   POOL_MAX  SALT  號域（zone = n // 10）
    539    39        1     0..3（1-9 / 10-19 / 20-29 / 30-39）
    f5     39        2     0..3
    m6     49        3     0..4（…40-49）

PRNG（Lehmer LCG，與本系統既有 G0 家族與網頁 lcgPicks 同款，跨語言一致）：
    s0     = (last_period * 1000003 + SALT) mod 2147483646 + 1
    x(0)   = s0
    x(k+1) = x(k) * 48271 mod 2147483647
    取號    n = 1 + x mod POOL_MAX
    全程整數運算；禁用時間、OS 熵源 —— 純函數，同輸入必同輸出。

抽取程序：
    候選池 P = {1..POOL_MAX} ∖ set(last_draw) ∖ excluded（fpx-v2 排除區）
    池 < MIN_POOL 依 (h高→低,深度淺→深,小號) 回補並記 relaxed:"pool"
    高號區門檻 hi 初始 32；若 |{hi..POOL_MAX} ∩ P| < 4 則 hi 每次減 2，
    直到湊滿 4 個高號候選，實際 hi 記入輸出（539/F5 上期全高號之退化保護）。

    依序產生 A、B、C、D；每組自同一條 LCG 數列連續取號，
    跳過「不在 P」「已被前面組用掉」「本組已有」的號碼；
    湊滿 3 碼（升冪 a<b<c）後檢查組規則：
        R1 高號保底：c ≥ hi
        R2 無等差：  ¬(b−a == c−b)（任意公差，含連號）
        R3 無同尾：  ¬(a%10 == b%10 == c%10)
        R4 跨號域：  三碼不可全落同一 zone
    違規 → 本組 3 碼放棄（不佔用），繼續同一條數列重抽；單組上限 300 次。

    四組完成後全域檢查：
        G1 12 碼互不重複、與上期無交集（由構造保證）
        G2 號域全覆蓋：每個 zone 至少 1 碼（539/F5 四區、m6 五區）
        G2 違規 → 僅重抽 D 組（上限 300 次），且要求 D 含所有缺失 zone 的號碼。

    Fallback 階梯（整輪重跑、數列自 s0 重啟；每放寬一級記入 relaxed）：
        第 1 級 relaxed=["cover"]        放寬 G2 號域覆蓋
        第 2 級 relaxed=["cover","zone"] 再放寬 R4 組內跨域
        永不放寬：12 碼不重複、避上期、R1（有 hi 降階）、R2、R3
        最終兜底 relaxed+=["lex"]：對 P 升冪、以字典序回溯枚舉取最小合法解。

兌獎口徑（由 build_log_entries 沿用執行）：
    539 / F5 對開出 5 碼；六合對「主 6 碼」，特別號（e 欄）不計。

輸出（BASE_PENDING v2 之核心，excluded/ts 由呼叫端補）：
    {"v":2, "algo":"sfg-v2", "seed":<last_period>, "forPeriod":<last_period+1>,
     "hi":<實際門檻>, "relaxed":[...],
     "strategies":{"A":[a,b,c], "B":[...], "C":[...], "D":[...]}}
    ※ forPeriod 僅供顯示；跨年改號（如六合 26/xxx→27/001）時以實際開獎為準。

驗算（給親友）：
    python3 pick_engine.py 539            # 讀公開 data 檔重算排除區＋四組
    python3 pick_engine.py 539 115192 "5,11,24,31,32" --excluded "8,15,..."
    python3 pick_engine.py --selftest
"""

from itertools import combinations

ALGO = "sfg-v2"   # v1（2026-08-09）：避上期；v2（2026-08-12）：再避 fpx-v1 不出牌排除區
MOD = 2147483647
MULT = 48271

GAMES = {
    "539": {"pool_max": 39, "salt": 1, "zones": (0, 1, 2, 3), "draw": 5},
    "f5":  {"pool_max": 39, "salt": 2, "zones": (0, 1, 2, 3), "draw": 5},
    "m6":  {"pool_max": 49, "salt": 3, "zones": (0, 1, 2, 3, 4), "draw": 6},
}

MIN_POOL = 16          # 候選池下限：12 碼＋過濾規則的活動空間
ATRISK_MIN = 20        # 平坦度深度樣本門檻（與頁面平坦度卡同值）
MIN_EXCL = 5           # fpx-v2：由最低柱往上收號碼的目標顆數（鈞洋 2026-08-12 拍板「湊滿 5 顆」）

GROUP_RETRY_LIMIT = 300


def derive_seed(last_period, salt):
    """s0 = (last_period * 1000003 + salt) mod 2147483646 + 1"""
    return (last_period * 1000003 + salt) % 2147483646 + 1


class Lehmer:
    """與 lcg_picks / 網頁 lcgPicks 同款數列。"""

    def __init__(self, s0):
        self.x = s0

    def next_num(self, pool_max):
        self.x = (self.x * MULT) % MOD
        return 1 + self.x % pool_max


def zone_of(n):
    return n // 10


def group_ok(trio, hi, relax_zone):
    a, b, c = trio
    if c < hi:                                   # R1 高號保底
        return False
    if b - a == c - b:                           # R2 無等差
        return False
    if a % 10 == b % 10 == c % 10:               # R3 無同尾
        return False
    if not relax_zone and zone_of(a) == zone_of(b) == zone_of(c):  # R4 跨號域
        return False
    return True


def _draw_group(rng, pool, used, pool_max, hi, relax_zone, require_zones=None,
                max_high=3):
    """自數列連續取號湊一組；違規放棄重抽（同一條數列），上限 GROUP_RETRY_LIMIT。

    max_high＝本組最多可佔用的高號（≥hi）數。高號預算（sfg-v2 補強，2026-08-12）：
    排除區會壓縮高號供給，若前面的組貪婪吃掉多顆高號，後面的組會 R1 無解
    而整階梯崩落到字典序兜底（實測：高號恰 4 顆時組1 佔 2 顆 → 組3 無高號可用）。
    """
    for _ in range(GROUP_RETRY_LIMIT):
        trio = []
        # 單組取號也設護欄，避免池過小時空轉
        for _pull in range(5000):
            n = rng.next_num(pool_max)
            if n not in pool or n in used or n in trio:
                continue
            trio.append(n)
            if len(trio) == 3:
                break
        if len(trio) < 3:
            return None
        trio.sort()
        if sum(1 for n in trio if n >= hi) > max_high:
            continue
        if not group_ok(trio, hi, relax_zone):
            continue
        if require_zones and not require_zones.issubset({zone_of(n) for n in trio}):
            continue
        return trio
    return None


def _attempt(game_cfg, s0, pool, hi, relax_cover, relax_zone):
    """跑一整輪抽取；失敗回 None。數列自 s0 重啟保證各級 fallback 可重現。"""
    rng = Lehmer(s0)
    pool_max = game_cfg["pool_max"]
    used = set()
    groups = []
    for gi in range(4):
        # 高號預算：本組佔用數 ≤ 剩餘高號 −（之後還有幾組，各需至少 1 顆）
        highs_left = sum(1 for n in pool if n >= hi and n not in used)
        max_high = max(1, highs_left - (3 - gi))
        trio = _draw_group(rng, pool, used, pool_max, hi, relax_zone,
                           max_high=max_high)
        if trio is None:
            return None
        groups.append(trio)
        used.update(trio)

    if not relax_cover:
        zones_needed = set(game_cfg["zones"])
        covered_all = {zone_of(n) for g in groups for n in g}
        if zones_needed - covered_all:
            # 重抽 D 組補覆蓋。缺失號域必須「相對 A+B+C」計算——
            # 若拿含舊 D 的覆蓋算，舊 D 原本罩住的號域會在重抽後漏掉
            # （selftest 於 f5 期 11789、m6 五期實際抓到此 bug）。
            covered_abc = {zone_of(n) for g in groups[:3] for n in g}
            missing = zones_needed - covered_abc
            if len(missing) > 3:
                return None  # 一組 3 碼不可能補齊，交給 fallback 階梯
            used.difference_update(groups[3])
            trio = _draw_group(rng, pool, used, pool_max, hi, relax_zone,
                               require_zones=missing)
            if trio is None:
                return None
            groups[3] = trio
            used.update(trio)
    return groups


def _lex_fallback(pool, hi, pool_max):
    """字典序回溯：取最小合法 4×3（永不放寬的規則全數保留）。"""
    ordered = sorted(pool)

    def pick(groups, remaining):
        if len(groups) == 4:
            return groups
        for trio in combinations(remaining, 3):
            if group_ok(list(trio), hi, relax_zone=True):
                res = pick(groups + [list(trio)],
                           [n for n in remaining if n not in trio])
                if res:
                    return res
        return None

    return pick([], ordered)


# ──────────────────── fpx-v2 不出牌排除區（2026-08-12 事前註冊）────────────────────
#
# 規則（鈞洋 2026-08-12 拍板；同日的 fpx-v1「低於理論值全排」是對其原意的誤解，
# v1 存續期間零筆結算即被本版取代，無需分段）：
#   對平坦度檢驗圖上「低於理論值」的深度，依 h(g) 由低到高（同 h 取深度小者）
#   逐根收集其上的號碼，**直到累計 ≥ MIN_EXCL(5) 顆為止**——即「距離基準最低的
#   那幾根柱子」上的號碼進不出牌區。空柱（該深度目前無號碼）照樣消耗名次。
#   h(g) = dist[g] / atRisk(g)，與平坦度卡完全同一條算式；
#   atRisk < ATRISK_MIN 的深度樣本太薄，視為中性、不給排除資格。
#   低於理論值的柱子全收仍不足 MIN_EXCL 時，有多少排多少（不硬湊）。
#
# 誠實揭露（不可刪）：本站平坦度卡的結論正是「這些偏離是抽樣噪音」——本規則是
# 可重現的縮池慣例，不是預測訊號；out-of-sample 追蹤（excludedHits）就是它的裁決台，
# 預期長期與隨機基準無異。
#
# sfg-v2（同日註冊）：選號候選池在「避上期」外，再排除本區號碼。
# 池低於 MIN_POOL 時依 (h 高→低、深度淺→深、號碼小→大) 回補並記 relaxed:"pool"。

def build_return_dist(records):
    """回歸間隔分佈（與頁面 buildReturnDist 同邏輯；records 新→舊）。"""
    dist = {}
    for i in range(len(records) - 1, -1, -1):
        for n in records[i]["n"]:
            for j in range(i - 1, -1, -1):
                if n in records[j]["n"]:
                    gap = i - j - 1
                    dist[gap] = dist.get(gap, 0) + 1
                    break
    return dist


def current_gaps(records, pool_max):
    """每號目前沉寂深度：最新一期含 n → 0；從未出現 → len(records)。"""
    gaps = {}
    for n in range(1, pool_max + 1):
        gaps[n] = len(records)
        for i, r in enumerate(records):
            if n in r["n"]:
                gaps[n] = i
                break
    return gaps


def flatness_exclude(game, records):
    """fpx-v2：回傳 (excluded 升冪, excl_depths 升冪, readmit_order)。純函數。

    由最低柱往上收號碼直到 ≥ MIN_EXCL 顆；同 h 取深度小者（決定性）。
    excl_depths 為實際消耗的柱子（含空柱），供頁面平坦度圖 🚫 標記。
    """
    cfg = GAMES[game]
    theory = cfg["draw"] / cfg["pool_max"]
    dist = build_return_dist(records)
    gaps = current_gaps(records, cfg["pool_max"])
    h_of = {}
    below = []  # (h, g, nums)
    for g in range(0, (max(dist) + 1) if dist else 0):
        at_risk = sum(c for k, c in dist.items() if k >= g)
        if at_risk < ATRISK_MIN:
            break  # 更深的深度樣本更薄，一律中性
        h = dist.get(g, 0) / at_risk
        h_of[g] = h
        if h < theory:
            below.append((h, g, sorted(n for n, gg in gaps.items() if gg == g)))
    below.sort(key=lambda t: (t[0], t[1]))
    excluded, excl_depths = [], []
    for h, g, nums in below:
        excl_depths.append(g)
        excluded.extend(nums)
        if len(excluded) >= MIN_EXCL:
            break
    excluded.sort()
    excl_depths.sort()
    # 回補順序：h 最接近理論值者先回（h 高→低）、深度淺→深、小號優先
    readmit = sorted(excluded, key=lambda n: (-h_of.get(gaps[n], theory), gaps[n], n))
    return excluded, excl_depths, readmit


def gen_four_groups(game, last_period, last_draw, excluded=(), readmit_order=()):
    """主入口。純函數：同輸入必得同結果。

    sfg-v2（2026-08-12）：候選池＝全池 ∖ 上期 ∖ excluded（fpx-v1 不出牌排除區）。
    池 < MIN_POOL 時依 readmit_order 回補並記 relaxed:"pool"。
    回傳的 excluded 為**有效**排除區（原排除 ∖ 已回補），選號保證與其不相交。
    """
    cfg = GAMES[game]
    pool_max = cfg["pool_max"]
    pool = set(range(1, pool_max + 1)) - set(last_draw) - set(excluded)

    pool_relaxed = False
    eff_excluded = [n for n in excluded if n not in last_draw]
    for n in readmit_order:
        if len(pool) >= MIN_POOL:
            break
        if n in eff_excluded:
            pool.add(n)
            eff_excluded.remove(n)
            pool_relaxed = True

    hi = 32
    while len([n for n in pool if n >= hi]) < 4 and hi > 2:
        hi -= 2

    s0 = derive_seed(last_period, cfg["salt"])

    ladder = [([], False, False),
              (["cover"], True, False),
              (["cover", "zone"], True, True)]
    groups, relaxed = None, None
    for tags, rc, rz in ladder:
        groups = _attempt(cfg, s0, pool, hi, rc, rz)
        if groups is not None:
            relaxed = list(tags)
            break
    if groups is None:
        groups = _lex_fallback(pool, hi, pool_max)
        relaxed = ["cover", "zone", "lex"]
        if groups is None:  # 數學上不應發生；發生即資料異常
            raise RuntimeError(f"pick_engine: {game} 期 {last_period} 無合法解")

    if pool_relaxed:
        relaxed = relaxed + ["pool"]
    return {
        "v": 2,
        "algo": ALGO,
        "seed": last_period,
        "forPeriod": last_period + 1,
        "hi": hi,
        "relaxed": relaxed,
        "strategies": {k: g for k, g in zip("ABCD", groups)},
        "excluded": sorted(eff_excluded),
    }


def gen_pending_core(game, records):
    """一站式：fpx-v1 排除 ＋ sfg-v2 四組。fetch 與 CLI 的共同入口。

    records 新→舊（同 BASE_REC）。回傳 pending 核心（呼叫端補 ts）。
    """
    if not records:
        return {}
    excl, depths, readmit = flatness_exclude(game, records)
    core = gen_four_groups(game, records[0]["p"], records[0]["n"],
                           excluded=excl, readmit_order=readmit)
    core["exclAlgo"] = "fpx-v2"
    core["exclDepths"] = depths
    return core


# ──────────────────────────── 驗證與 CLI ────────────────────────────

def _read_records(game):
    """從 data_*.js 讀 BASE_REC（新→舊）。selftest 專用。"""
    import os
    import re
    fn = {"539": "data_539.js", "f5": "data_f5.js", "m6": "data_m6.js"}[game]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fn)
    txt = open(path, encoding="utf-8").read()
    seg = re.search(r"BASE_REC\s*=\s*\[(.*?)\];", txt, re.S).group(1)
    out = []
    for m in re.finditer(r"\{p:(\d+)(?:,draw:\"[^\"]*\")?(?:,dt:\"[^\"]*\")?,n:\[([\d,]+)\]", seg):
        out.append({"p": int(m.group(1)), "n": [int(x) for x in m.group(2).split(",")]})
    return out


def _verify_output(game, last_draw, res):
    """輸出必須滿足未放寬的所有規則；違者回傳錯誤訊息。"""
    cfg = GAMES[game]
    gs = list(res["strategies"].values())
    flat = [n for g in gs for n in g]
    errs = []
    if len(set(flat)) != 12:
        errs.append("12碼有重複")
    if set(flat) & set(last_draw):
        errs.append("含上期號碼")
    for k, g in res["strategies"].items():
        a, b, c = g
        if not (a < b < c):
            errs.append(f"{k} 未升冪")
        if c < res["hi"]:
            errs.append(f"{k} 違反 R1")
        if b - a == c - b:
            errs.append(f"{k} 違反 R2")
        if a % 10 == b % 10 == c % 10:
            errs.append(f"{k} 違反 R3")
        if "zone" not in res["relaxed"] and zone_of(a) == zone_of(b) == zone_of(c):
            errs.append(f"{k} 違反 R4")
    if "cover" not in res["relaxed"]:
        if set(cfg["zones"]) - {zone_of(n) for n in flat}:
            errs.append("違反 G2 覆蓋")
    # sfg-v2：選號必須與有效排除區不相交（回補過的號碼已不在 excluded 內）
    hit_excl = set(flat) & set(res.get("excluded", []))
    if hit_excl:
        errs.append(f"選號含排除區號碼 {sorted(hit_excl)}")
    return errs


def selftest():
    """三彩種全歷史回放：確定性 ×3、規則全過（含排除區不相交）、fallback 統計。"""
    ok = True
    for game in ("539", "f5", "m6"):
        recs = _read_records(game)
        if len(recs) < 2:
            print(f"[{game}] 讀不到足夠歷史，跳過")
            ok = False
            continue
        fallback_n = pool_relax_n = lex_n = 0
        excl_sizes = []
        for i in range(len(recs)):
            hist = recs[i:]
            if len(hist) < 40:
                break  # 與 build_log_entries 的 backfill 門檻一致
            res1 = gen_pending_core(game, hist)
            res2 = gen_pending_core(game, hist)
            if res1 != res2:
                print(f"[{game}] 期 {hist[0]['p']} 確定性失敗！")
                ok = False
            errs = _verify_output(game, hist[0]["n"], res1)
            if errs:
                print(f"[{game}] 期 {hist[0]['p']} 規則違規: {errs}")
                ok = False
            excl_sizes.append(len(res1["excluded"]))
            if res1["relaxed"]:
                fallback_n += 1
            if "pool" in res1["relaxed"]:
                pool_relax_n += 1
            if "lex" in res1["relaxed"]:
                lex_n += 1
        n = len(excl_sizes)
        print(f"[{game}] {n} 期回放完成｜排除區大小 min/中位/max = "
              f"{min(excl_sizes)}/{sorted(excl_sizes)[n//2]}/{max(excl_sizes)}"
              f"｜fallback {fallback_n}（pool 回補 {pool_relax_n}、lex {lex_n}）")
    print("SELFTEST", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


def _print_core(game, res):
    cfg = GAMES[game]
    s0 = derive_seed(res["seed"], cfg["salt"])
    print(f"seed 導出: ({res['seed']} × 1000003 + {cfg['salt']}) mod 2147483646 + 1 = {s0}")
    print(f"hi={res['hi']}  relaxed={res['relaxed']}  exclAlgo={res.get('exclAlgo', '—')}")
    print(f"  EXCLDEPTHS: {res.get('exclDepths', [])}")
    print(f"  EXCL: {res.get('excluded', [])}")
    for k, g in res["strategies"].items():
        print(f"  {k}: {g}")


def main(argv):
    if len(argv) >= 2 and argv[1] == "--selftest":
        return selftest()

    # 自動模式：pick_engine.py <game> —— 讀本地 data_*.js 重算排除區＋四組
    # （BASE_REC 為公開資料，親友可下載同一份檔案完整驗算）
    if len(argv) == 2 and argv[1] in GAMES:
        game = argv[1]
        recs = _read_records(game)
        res = gen_pending_core(game, recs)
        _print_core(game, res)
        errs = _verify_output(game, recs[0]["n"], res)
        print("規則自檢:", "全過 ✅" if not errs else errs)
        return 0

    # 手動模式：pick_engine.py <game> <上期期號> "<上期號碼>" [--excluded "n,n,..."]
    if len(argv) in (4, 6):
        game, last_period = argv[1], int(argv[2])
        last_draw = [int(x) for x in argv[3].replace(" ", "").split(",")]
        excl = []
        if len(argv) == 6 and argv[4] == "--excluded":
            excl = [int(x) for x in argv[5].replace(" ", "").split(",") if x]
        res = gen_four_groups(game, last_period, last_draw, excluded=excl,
                              readmit_order=sorted(excl))
        _print_core(game, res)
        errs = _verify_output(game, last_draw, res)
        print("規則自檢:", "全過 ✅" if not errs else errs)
        if not excl:
            print("（未給 --excluded：此為無排除區的裸算，與正式發布可能不同）")
        return 0

    print(__doc__)
    print("用法: pick_engine.py <539|f5|m6>                      # 讀 data 檔完整重算（驗算用）")
    print("      pick_engine.py <game> <上期期號> \"<上期號碼>\" [--excluded \"n,...\"]")
    print("      pick_engine.py --selftest")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
