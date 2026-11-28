#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pick_engine — 期號種子可重現選號引擎（sfg-v6「三池＋逾期開出主號」）
=================================================

事前註冊：sfg-v1 2026-08-09、sfg-v2/fpx-v2 2026-08-12、
         sfg-v3/fpx-v3 2026-08-16、sfg-v4 2026-08-17、sfg-v5 2026-11-27、**sfg-v6 2026-11-28**（皆鈞洋拍板）。

═══ v6 變更紀錄（2026-11-28，鈞洋拍板；只往前生效）═══

  **主號＝上期「逾期開出」的號碼**：上期開出號中，開出前沉寂 ≥T（539/F5 7、六合 8，同三池逾期門檻）者。
  依開出前沉寂由大到小（同值號碼小者先）取前 4 顆，依序固定放進 A/B/C/D 組各一顆（每顆只用一次，12 碼仍不重複），
  各組其餘 2 碼照 v5 三池規則抽；其他組的隨機抽號不會抽到主號。上期沒有逾期開出號 ⇒ 與 v5 完全相同。
  主號必在連莊池內（上期開出），故選號仍為三池子集。

  誠實揭露（事前寫下、事後不改口）：逾期開出的號碼下一期再開的機率，全歷史實測
  539 13.11%／F5 12.93%／六合 12.13%，與所有開出號（12.92/12.81/12.31%）及理論值（12.82/12.82/12.24%）
  無顯著差異（z=+0.92/+0.37/−0.26，2026-11-28）。本規則是可重現的選號慣例，不改變中獎機率與期望值。

  生效：539 第 115289 期、六合 26/126、F5 第 12076 期起（F5 12075 已以 v5 發布，不抽換）。

═══ v5 變更紀錄（2026-11-27，鈞洋拍板；只往前生效，不回頭重算歷史）═══

  **候選池改為「三池」聯集**（其餘規則全部沿用 v4）：
    令 g(n)＝最新一期起連續未開出期數（最新一期含 n → 0；六合只計主 6 碼）
    連莊 lz   ＝{n | g(n)=0}
    隔一期 gap1＝{n | g(n)=1}
    逾期 od   ＝{n | g(n)≥T}，T＝ceil(pool_max/draw − 1)：539/F5＝7、六合＝8（理論平均間隔）
    候選池＝lz ∪ gap1 ∪ od（三類互斥）。池 < MIN_POOL 時依 (g 大→小, 號碼小→大) 自池外回補，
    記 relaxed:"pool" 並輸出 readmit。歷史 < MIN_HIST 期不產號。

  本條推翻 2026-08-18「sfg-v4 為終版」之裁決，鈞洋知情並決定。

  誠實揭露（事前寫下、事後不改口）：中獎機率與期望值和隨機無異。
    全歷史「每期開出 ≥2 顆逾期號」539 63.8%／F5 63.4%／六合 68.2%，
    純隨機 64.4%／64.4%／69.1%（2026-11-27 實測）。本規則是可重現的選池慣例，不是預測訊號。

  生效：539 第 115289 期、F5 第 12075 期、六合 26/126 起（之前已發布的 v4 號碼不抽換）。
  全歷史回放（Fable 2026-11-27）：池大小最小 18/17/22、從未低於 MIN_POOL；無違規、無 lex 兜底。

═══ v4 以前（歷史沿革）═══
本檔即規格本身，任何人可依下述規則獨立重實作並得到逐位元相同的結果。

═══ v4 變更紀錄（2026-08-17，鈞洋拍板；只往前生效，不回頭重算歷史）═══

  **廢除 fpx 不出牌排除區。候選池＝全池，不再扣除任何號碼。**

  理由（全部來自 2026-08-16 全歷史回測，見 BACKTEST_REGISTRY.md）：
    1. **它沒有預測價值**：T3 六個檢定全部不顯著。
       六合 v4 排除區命中率 14.32% vs 理論 14.29%（p=0.96）——
       排除區裡的號碼，開出機率與隨機挑的號碼**一模一樣**。
    2. **它已經在自己失效**：ATRISK_MIN=20 是絕對門檻，歷史越長越深的柱子
       越容易達標，而深度 40+ 的柱子上幾乎沒號碼 ⇒ 排除區趨向恆空。
       長窗（≥1000 期）為空的比例已達 539 93%／F5 97%／六合 87%，
       且 fetch 的 all_records 只增不減，此趨勢不可逆。
    3. **留著是負債**：一個沒有效果、又會隨時間無聲改變行為的隱性參數，
       違背本系統「可重現、事前註冊」的核心精神。
    4. **拿掉不影響命中率**：回測對照線 B2（無排除區）與 S3（有排除區）
       在三彩種皆無顯著差異（T2，Holm 校正後全部不顯著）。

  ⚠️ 這會**改變選號結果** —— 候選池變了，PRNG 路徑就跟著變。
     故列為 v4 而非 v3 的小修，且只往前生效：舊 PICKLOG 原樣保留供審計。

  ※ `flatness_exclude()` 函式**保留但已退役**，只供回測與歷史審計使用，
    產線路徑（gen_pending_core）不再呼叫它。

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

═══ v3 變更紀錄（2026-08-16，鈞洋拍板；只往前生效，不回頭重算歷史）═══
三項放寬，動機皆為結構性（非因近期未中）：

  [1] 移除「避上期」約束
      舊：候選池排除上期開出的號碼。
      新：不排除，上期號碼可再被選中。
      理由：上期號碼下期再出的機率與其他號碼**完全相同**（d/POOL_MAX），
            「避上期」從無機率依據，只是平白縮小候選池。
      ※ 全歷史實測連莊率（2026-08-16）：539 13.60% / F5 14.21% / 六合 12.62%，
        對應理論值 12.82% / 12.82% / 12.24%，三者 p=0.46 / 0.14 / 0.62，
        **均未達統計顯著**。故本次修改**不主張**連莊有預測價值，
        僅移除一條沒有根據的限制。

  [2] R1 高號保底：組內規則 → 全域規則
      舊：每組最大碼 c ≥ hi（四組各佔一顆高號，539/F5 僅 8 顆 ≥32，綁死）。
      新：四組合計至少 MIN_HIGH_TOTAL(3) 顆 ≥ hi；單組可完全沒有高號。
      理由：反熱門的意義在「12 碼整體不全擠在生日區 1-31」，
            逐組強制並無額外效果，卻大幅壓縮候選空間。

  [3] fpx-v3 不出牌排除區：湊滿顆數 → 固定柱數
      舊（v2）：距基準最低的柱子由低往高收號碼，直到累計 ≥ 5 顆。
      新（v3）：只取距基準最低的 EXCL_BARS(2) 根柱子，**上面有幾顆算幾顆**。
      理由：v2 為湊滿 5 顆常需消耗 4-5 根柱子，排除範圍超出「最偏離」的本意。
      ※ 全歷史回放（2026-08-16）：排除區平均大小 539 6.27→1.44、
        F5 5.61→1.76、六合 5.39→0.88 顆；且有 28.9% / 35.5% / 41.0%
        的期數排除區為 **0 顆**（最低兩根柱子上無號碼）。
        即本規則多數時候近乎不作用 —— 這是已知且接受的後果。

═══ 全歷史回測結果（2026-08-16，事前註冊見 BACKTEST_REGISTRY.md）═══
539 5441 期／F5 6301 期／六合 2086 期，五條對照線，Holm 校正 30 次檢定。
可偵測相對效果：539 ±2.04%、F5 ±1.90%、六合 ±3.39%（2 SD）。
**p > 0.05 的意思是「排除了大於上述幅度的效果」，不是「證明沒有差異」。**

  [T1] 過濾規則（R2/R3/R4/G2/G3）淨效果：**六個檢定全部不顯著**
       對照組 B1 ＝ 同種子同數列但關閉全部規則，故 S−B1 即規則的純效果。
       ⇒ 規則沒有扣分，sfg-v3 可安心續用。

  [T3] 排除區命中率：**六個檢定全部不顯著**（539 v3 12.36% vs 理論 12.82%，p=0.75；
       六合 v4 14.32% vs 理論 14.29%，p=0.96 —— 六合用**出現口徑** 7/49）
       ⇒ fpx 無預測價值，與本檔下方「預期長期與隨機基準無異」的事前宣告一致。

  [T4] 號碼入選均勻度：539/F5**極度顯著**（χ²≈1762/1996, df=38），六合正常（χ²=35）。
       診斷：**G3 的直接數學後果，不是缺陷**。539/F5 的 pool=39，≥32 只有 8 個號碼
       要供應「12 碼至少 3 顆高號」⇒ 32-39 入選率被推到均勻值的 **132%**、
       1-31 壓到 92%，最多/最少比 1.58×。六合 pool=49、≥32 有 18 顆，壓力分散故正常。
       對照組 B1 在三彩種都完全均勻（χ²=7.2/5.2/17.2, p=1.0000）⇒ PRNG 本身無偏。
       ※ 此偏斜正是 G3 的目的（偏離生日區 1-31 降撞號），且 T1 證明不影響命中率。
         記此數字是為了讓它成為「已知且刻意」，而不是「沒人算過」。

  [T2] 539 出現 p_adj=0.038 的顯著正向 → 依 §5 事前承諾「先假設是 bug」追查，
       判定為 **PRNG 路徑偶然**：同一份真實排除區換 20 個 salt，均差分佈以 0 為中心
       （+0.00046 ± 0.00264），產線 salt 在三彩種排名 1/11/11（隨機散佈）；
       且 539 與 F5 規則完全相同僅 salt 不同，F5 的 z 只有 −0.17。
       **沒有發現 bug，也沒有發現規律。** 複驗：backtest_diagnostics.py

  🔴 [已知待決] fpx-v3 隨歷史累積而失效：ATRISK_MIN=20 是**絕對**門檻，歷史越長
       越深的柱子越容易達標，而深度 40+ 的柱子上幾乎不會有號碼 ⇒ 排除區趨向恆空。
       實測長窗（≥1000 期）空的比例：539 93%／F5 97%／六合 87%。
       且 fetch 的 all_records 只增不減（539_fetch.py:409），此趨勢不可逆。
       ※ 上面 v3 註冊的 1.44/1.76/0.88 顆是用**平均窗長僅 119/147/181 期**的回放算的，
         產線實際窗口從未處在該狀態 —— 註冊數字從第一天起就低估了衰減。
       候選解 fpx-v4（門檻改 max(20, 5%×總樣本)）已回測驗證可使規模長短窗穩定，
       但 T3 顯示 v3/v4 皆無預測價值 ⇒ **修好的是穩定性，不是效果**。尚未拍板進產線。

規格（sfg-v4）
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
    ※ 種子仍取 last_period（上期期號），此點 v3 未變。

抽取程序：
    候選池 P = {1..POOL_MAX}
              ※ v3 起不再扣除 last_draw；**v4 起不再扣除排除區**（fpx 已廢除）
              ※ 回測可經 gen_four_groups(excluded=…) 傳入排除區模擬舊制，
                此時池 < MIN_POOL 會依 readmit_order 回補並記 relaxed:"pool"
    高號區門檻 hi 初始 32；若 |{hi..POOL_MAX} ∩ P| < MIN_HIGH_TOTAL(3)
    則 hi 每次減 2，直到湊滿 3 個高號候選，實際 hi 記入輸出。

    依序產生 A、B、C、D；每組自同一條 LCG 數列連續取號，
    跳過「不在 P」「已被前面組用掉」「本組已有」的號碼；
    湊滿 3 碼（升冪 a<b<c）後檢查組規則：
        R2 無等差：  ¬(b−a == c−b)（任意公差，含連號）
        R3 無同尾：  ¬(a%10 == b%10 == c%10)
        R4 跨號域：  三碼不可全落同一 zone
        （R1 已於 v3 改為全域規則 G3，不再逐組檢查）
    違規 → 本組 3 碼放棄（不佔用），繼續同一條數列重抽；單組上限 300 次。

    高號下限引導（保證 G3 成立的構造）：
        抽第 gi 組（0-based）時，令 have = 已用掉的高號數、
        still = max(0, MIN_HIGH_TOTAL − have)、after = 3 − gi（本組之後的組數），
        則本組最少高號數 min_high = max(0, still − 2 × after)。
        ※ 係數是 **2 不是 3**（每組承載上限記 2）：539/F5 的高號 32-39 全落在同一個
          zone 3，若讓最後一組扛滿 3 顆必然三碼同域而撞 R4 —— 實測 539 有 7 期因此
          掉進 relaxed，期 115066 更一路崩到 lex 兜底。記 2 使壓力提前一組分擔。
        故 C 組可能被要求 1 顆、D 組必被要求補足其餘缺口，G3 由構造保證。

    四組完成後全域檢查：
        G1 12 碼互不重複（由構造保證）
        G2 號域全覆蓋：每個 zone 至少 1 碼（539/F5 四區、m6 五區）
        G3 高號合計：|{n ∈ 12碼 : n ≥ hi}| ≥ MIN_HIGH_TOTAL（3）
        G2 違規 → 僅重抽 D 組（上限 300 次），且要求 D 含所有缺失 zone 的
                  號碼，並同時滿足其 min_high。

    Fallback 階梯（整輪重跑、數列自 s0 重啟；每放寬一級記入 relaxed）：
        第 1 級 relaxed=["cover"]        放寬 G2 號域覆蓋
        第 2 級 relaxed=["cover","zone"] 再放寬 R4 組內跨域
        永不放寬：12 碼不重複、G3 高號合計（有 hi 降階）、R2、R3
        最終兜底 relaxed+=["lex"]：對 P 升冪、以字典序回溯枚舉取最小合法解。

🔴 六合彩有**兩個不同口徑，絕不可混用**（2026-08-16 鈞洋澄清）：

  [兌獎] 特別號**不計**，只對主 6 碼。539 / F5 對開出 5 碼。
         → 本口徑**正確且維持不動**，build_log_entries 照舊。
         一組 3 碼全中 C(6,3)/C(49,3) ≈ 1/921。

  [出現] 特別號**要計**，主 6 碼 ＋ 特碼共 7 碼。
         → 用於判斷「這個號碼到底有沒有開出」（單碼出現率 7/49 = 14.29%，
           不是兌獎的 6/49 = 12.24%）。
         ※ v4 廢除排除區後，產線已無處使用此口徑；保留說明供回測與
           歷史 excludedHits 的解讀，兩者不可混用。

輸出（BASE_PENDING v4 之核心，ts 由呼叫端補）：
    {"v":4, "algo":"sfg-v4", "seed":<last_period>, "forPeriod":<last_period+1>,
     "hi":<實際門檻>, "minHigh":3, "relaxed":[...],
     "strategies":{"A":[a,b,c], "B":[...], "C":[...], "D":[...]}}
    ※ v4 起**不再有** excluded / exclAlgo / exclDepths 欄位（fpx 已廢除）。
      舊 v2/v3 的 PICKLOG 條目仍帶這些欄位，頁面分段統計照舊。
    ※ forPeriod 僅供顯示；跨年改號（如六合 26/xxx→27/001）時以實際開獎為準。

驗算（給親友）：
    python3 pick_engine.py 539            # 讀公開 data 檔重算本期四組（v6 三池＋主號）
    python3 pick_engine.py 539 --at 115288 # 以截至該期的歷史重算（重現已發布號碼用這個）
    python3 pick_engine.py 539 115192 "5,11,24,31,32"   # 手動試算：只有上期號碼、全池裸算，與正式發布不同
    python3 pick_engine.py --selftest
"""

from itertools import combinations

ALGO = "sfg-v6"   # v6(11-28)三池＋上期逾期開出號為主號；v5(11-27)三池：連莊∪隔一期∪逾期； v1(08-09)避上期；v2(08-12)加 fpx 排除區；v3(08-16)解除避上期+R1改全域；
                  # v4(08-17)廢除 fpx 排除區（回測證實無預測價值且正在自我失效）
ALGO_V = 6        # 寫進 BASE_PENDING 的 v 欄位；勿在別處寫死版號（見 verify_consistency.js 的坑）
MOD = 2147483647
MULT = 48271

GAMES = {
    "539": {"pool_max": 39, "salt": 1, "zones": (0, 1, 2, 3), "draw": 5},
    "f5":  {"pool_max": 39, "salt": 2, "zones": (0, 1, 2, 3), "draw": 5},
    "m6":  {"pool_max": 49, "salt": 3, "zones": (0, 1, 2, 3, 4), "draw": 6},
}

# sfg-v5 三池：逾期門檻＝ceil(pool_max/draw − 1)（理論平均間隔，事前註冊、不隨資料漂移）
OD_THRESHOLD = {"539": 7, "f5": 7, "m6": 8}
MAX_ANCHORS = 4        # sfg-v6：主號最多 4 顆（一組一顆）
MIN_HIST = 40          # 歷史不足不產號（與 build_log_entries 補結算門檻一致）
MIN_POOL = 16          # 候選池下限：12 碼＋過濾規則的活動空間
ATRISK_MIN = 20        # 平坦度深度樣本門檻（與頁面平坦度卡同值）
EXCL_BARS = 2          # fpx-v3：只取距基準最低的柱子根數，上面有幾顆算幾顆
                       #（鈞洋 2026-08-16 拍板，取代 v2 的「湊滿 5 顆」）
MIN_HIGH_TOTAL = 3     # sfg-v3 G3：四組合計最少高號（≥hi）顆數
                       #（鈞洋 2026-08-16 拍板，取代 v2 的「每組最大碼 ≥hi」）

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
    """組內規則。sfg-v3 起 R1 已移出（改為全域 G3），此處只驗 R2/R3/R4。

    hi 參數保留於簽章以維持呼叫端相容，本函式不再使用它。
    """
    a, b, c = trio
    if b - a == c - b:                           # R2 無等差
        return False
    if a % 10 == b % 10 == c % 10:               # R3 無同尾
        return False
    if not relax_zone and zone_of(a) == zone_of(b) == zone_of(c):  # R4 跨號域
        return False
    return True


def _draw_group(rng, pool, used, pool_max, hi, relax_zone, require_zones=None,
                min_high=0, fixed=None):
    """自數列連續取號湊一組；違規放棄重抽（同一條數列），上限 GROUP_RETRY_LIMIT。

    min_high＝本組**最少**須佔用的高號（≥hi）數（sfg-v3，2026-08-16）。
    v2 的 max_high 預算是為了「保證每組都湊得到高號」；v3 把 R1 改成全域
    合計 ≥MIN_HIGH_TOTAL 後，需求反轉為下限引導 —— 由呼叫端逐組遞推，
    使最後一組必被要求補足缺口，G3 遂由構造保證而非事後檢查。
    """
    for _ in range(GROUP_RETRY_LIMIT):
        trio = [fixed] if fixed is not None else []   # sfg-v6：主號固定在本組
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
        if sum(1 for n in trio if n >= hi) < min_high:
            continue
        if not group_ok(trio, hi, relax_zone):
            continue
        if require_zones and not require_zones.issubset({zone_of(n) for n in trio}):
            continue
        return trio
    return None


def _attempt(game_cfg, s0, pool, hi, relax_cover, relax_zone, anchors=()):
    """跑一整輪抽取；失敗回 None。數列自 s0 重啟保證各級 fallback 可重現。"""
    rng = Lehmer(s0)
    pool_max = game_cfg["pool_max"]
    used = set(anchors)        # 主號預先保留：隨機抽號不會抽到（由所屬組以 fixed 放入）
    groups = []
    for gi in range(4):
        # 高號下限引導（sfg-v3）：still = 還缺幾顆；after = 本組之後還有幾組。
        # 每組**承載上限記 2 而非 3**：539/F5 的高號 32-39 全落在 zone 3，
        # 若讓最後一組扛滿 3 顆，該組必然三碼同域而撞 R4 —— 實測 539 有 7 期
        # 因此掉進 relaxed，其中期 115066 更一路崩到 lex 兜底。記 2 可使
        # 壓力提前一組分擔，任一組最多只需 2 顆高號，不觸發 R4。
        placed = {n for g in groups for n in g}
        have = sum(1 for n in placed if n >= hi)
        still = max(0, MIN_HIGH_TOTAL - have)
        min_high = max(0, still - 2 * (3 - gi))
        trio = _draw_group(rng, pool, used, pool_max, hi, relax_zone,
                           min_high=min_high,
                           fixed=anchors[gi] if gi < len(anchors) else None)
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
            used.update(anchors)   # 主號保留不釋出
            # 重抽的 D 仍須扛起 G3 缺口，否則舊 D 的高號會隨重抽一起消失
            have_abc = sum(1 for g in groups[:3] for n in g if n >= hi)
            trio = _draw_group(rng, pool, used, pool_max, hi, relax_zone,
                               require_zones=missing,
                               min_high=max(0, MIN_HIGH_TOTAL - have_abc),
                               fixed=anchors[3] if len(anchors) > 3 else None)
            if trio is None:
                return None
            groups[3] = trio
            used.update(trio)

    # G3 由 min_high 構造保證；此處為防禦性複驗（構造若被改壞會在 selftest 現形）
    if sum(1 for g in groups for n in g if n >= hi) < MIN_HIGH_TOTAL:
        return None
    return groups


def _lex_fallback(pool, hi, pool_max, anchors=()):
    """字典序回溯：取最小合法 4×3（永不放寬的規則全數保留，含 G3 高號合計）。"""
    ordered = sorted(set(pool) - set(anchors))

    def pick(groups, remaining):
        if len(groups) == 4:
            highs = sum(1 for g in groups for n in g if n >= hi)
            return groups if highs >= MIN_HIGH_TOTAL else None
        # 剪枝：剩下的組就算全塞高號也補不到 MIN_HIGH_TOTAL，直接回頭。
        # 字典序從小號開始展開，沒有這道剪枝會把整棵低號子樹走完才發現無解。
        # sfg-v6：後面幾組的主號已保留（不在 remaining），高號要算進去、空位要扣掉，
        # 否則會把「靠後組主號才湊得到 G3」的分支錯剪（539 第 98073 期實例，2026-11-28 Fable 第四輪）。
        fut = anchors[len(groups):]
        have = sum(1 for g in groups for n in g if n >= hi) + sum(1 for a in fut if a >= hi)
        avail = sum(1 for n in remaining if n >= hi)
        cap = 3 * (4 - len(groups)) - len(fut)
        if have + min(avail, cap) < MIN_HIGH_TOTAL:
            return None
        gi = len(groups)
        cands = ((tuple(sorted((anchors[gi],) + pair)) for pair in combinations(remaining, 2))
                 if gi < len(anchors) else combinations(remaining, 3))
        for trio in cands:
            if group_ok(list(trio), hi, relax_zone=True):
                res = pick(groups + [list(trio)],
                           [n for n in remaining if n not in trio])
                if res:
                    return res
        return None

    return pick([], ordered)


# ═══════ fpx-v3 不出牌排除區 —— 🔴 2026-08-17 已廢除（sfg-v4），以下保留供審計 ═══════
#
# ⚠️ 產線路徑（gen_pending_core）**不再呼叫本區任何函式**。
#    保留原因：①歷史 PICKLOG 的 excluded/excludedHits 需要本規格才能解讀
#              ②backtest.py 與本機的私人分析腳本仍用它做對照組
#    廢除理由見本檔開頭「v4 變更紀錄」。**不要再把它接回產線。**
#
# 規則（鈞洋 2026-08-16 拍板，取代 v2）：
#   對平坦度檢驗圖上「低於理論值」的深度，依 h(g) 由低到高（同 h 取深度小者）
#   **只取最前面 EXCL_BARS(2) 根柱子**，其上有幾顆號碼就排幾顆——不再為湊顆數
#   繼續往上收。空柱（該深度目前無號碼）照樣消耗一個名次，故排除區可能為 0 顆。
#   h(g) = dist[g] / atRisk(g)，與平坦度卡完全同一條算式；
#   atRisk < ATRISK_MIN 的深度樣本太薄，視為中性、不給排除資格。
#
#   與 v2 的差異：v2 為湊滿 5 顆常需吃掉 4-5 根柱子，排除範圍超出「最偏離」本意。
#   v3 改為固定 2 根，實測排除區均值 539 6.27→1.44、F5 5.61→1.76、六合 5.39→0.88，
#   且 28.9%/35.5%/41.0% 的期數為 0 顆。**本規則多數時候近乎不作用，已知並接受。**
#
# 誠實揭露（不可刪）：本站平坦度卡的結論正是「這些偏離是抽樣噪音」——本規則是
# 可重現的縮池慣例，不是預測訊號；out-of-sample 追蹤（excludedHits）就是它的裁決台，
# 預期長期與隨機基準無異。
#
# sfg-v3（同日註冊）：選號候選池＝全池 ∖ 本區（v3 起**不再扣除上期號碼**）。
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


def three_pools(game, records):
    """sfg-v5：回傳 ({lz, gap1, od} 各自升冪, readmit_order)。純函數；records 新→舊。

    readmit_order＝池外號碼依 (g 大→小, 號碼小→大)，池 < MIN_POOL 時由 gen_four_groups 依序回補。
    """
    cfg = GAMES[game]
    gaps = current_gaps(records, cfg["pool_max"])
    T = OD_THRESHOLD[game]
    pools = {
        "lz":   sorted(n for n, g in gaps.items() if g == 0),
        "gap1": sorted(n for n, g in gaps.items() if g == 1),
        "od":   sorted(n for n, g in gaps.items() if g >= T),
    }
    inpool = set(pools["lz"]) | set(pools["gap1"]) | set(pools["od"])
    readmit_order = sorted((n for n in gaps if n not in inpool), key=lambda n: (-gaps[n], n))
    return pools, readmit_order


def overdue_anchors(game, records):
    """sfg-v6：上期開出號中「開出前沉寂 ≥T」者 → (主號 list, 對應開出前沉寂 list)。records 新→舊。"""
    if len(records) < 2:
        return [], []
    cfg = GAMES[game]
    prior = current_gaps(records[1:], cfg["pool_max"])
    T = OD_THRESHOLD[game]
    hits = sorted((n for n in records[0]["n"] if prior[n] >= T), key=lambda n: (-prior[n], n))[:MAX_ANCHORS]
    return hits, [prior[n] for n in hits]


def flatness_exclude(game, records):
    """fpx-v3：回傳 (excluded 升冪, excl_depths 升冪, readmit_order)。純函數。

    只取距基準最低的 EXCL_BARS(2) 根柱子，上面有幾顆算幾顆；同 h 取深度小者
    （決定性）。excl_depths 為實際消耗的柱子（含空柱），供頁面平坦度圖 🚫 標記。
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
    for h, g, nums in below[:EXCL_BARS]:      # fpx-v3：固定根數，不看顆數
        excl_depths.append(g)
        excluded.extend(nums)
    excluded.sort()
    excl_depths.sort()
    # 回補順序：h 最接近理論值者先回（h 高→低）、深度淺→深、小號優先
    readmit = sorted(excluded, key=lambda n: (-h_of.get(gaps[n], theory), gaps[n], n))
    return excluded, excl_depths, readmit


def gen_four_groups(game, last_period, last_draw, excluded=(), readmit_order=(),
                    pools=None, anchors=(), anchor_gaps=()):
    """主入口。純函數：同輸入必得同結果。

    sfg-v3（2026-08-16）：候選池＝全池 ∖ excluded（fpx-v3 不出牌排除區）。
    **v3 起不再扣除 last_draw** —— 上期號碼下期再出的機率與其他號碼相同，
    「避上期」無機率依據。last_draw 參數保留：仍供呼叫端與驗證比對之用。
    池 < MIN_POOL 時依 readmit_order 回補並記 relaxed:"pool"。
    回傳的 excluded 為**有效**排除區（原排除 ∖ 已回補），選號保證與其不相交。
    """
    cfg = GAMES[game]
    pool_max = cfg["pool_max"]
    if pools is not None:
        # sfg-v5：候選池＝三池聯集；池外號碼以 excluded 形式交給既有回補機制，但不對外輸出
        inpool = set(pools["lz"]) | set(pools["gap1"]) | set(pools["od"])
        excluded = sorted(set(range(1, pool_max + 1)) - inpool)
    pool = set(range(1, pool_max + 1)) - set(excluded)

    pool_relaxed = False
    eff_excluded = list(excluded)
    for n in readmit_order:
        if len(pool) >= MIN_POOL:
            break
        if n in eff_excluded:
            pool.add(n)
            eff_excluded.remove(n)
            pool_relaxed = True

    # hi 降階：只需湊得出 MIN_HIGH_TOTAL 顆高號候選（v2 是每組各一共 4 顆）
    hi = 32
    while len([n for n in pool if n >= hi]) < MIN_HIGH_TOTAL and hi > 2:
        hi -= 2

    s0 = derive_seed(last_period, cfg["salt"])

    ladder = [([], False, False),
              (["cover"], True, False),
              (["cover", "zone"], True, True)]
    groups, relaxed = None, None
    for tags, rc, rz in ladder:
        groups = _attempt(cfg, s0, pool, hi, rc, rz, anchors=tuple(anchors))
        if groups is not None:
            relaxed = list(tags)
            break
    if groups is None:
        groups = _lex_fallback(pool, hi, pool_max, anchors=tuple(anchors))
        relaxed = ["cover", "zone", "lex"]
        if groups is None:  # 數學上不應發生；發生即資料異常
            raise RuntimeError(f"pick_engine: {game} 期 {last_period} 無合法解")

    if pool_relaxed:
        relaxed = relaxed + ["pool"]
    out = {
        "v": ALGO_V,
        "algo": ALGO,
        "seed": last_period,
        "forPeriod": last_period + 1,
        "hi": hi,
        "minHigh": MIN_HIGH_TOTAL,
        "relaxed": relaxed,
        "strategies": {k: g for k, g in zip("ABCD", groups)},
    }
    # sfg-v4：排除區已廢除，產線恆為空 ⇒ 不輸出該欄位，頁面的排除區卡自動消失。
    # 回測仍可傳 excluded 進來模擬舊制，此時照常輸出以供比對。
    if ALGO_V >= 6 and pools is not None:
        out["anchors"] = list(anchors)            # sfg-v6 主號（可能為空陣列＝本期無逾期開出號）
        out["anchorGaps"] = list(anchor_gaps)
    if pools is not None:
        out["pools"] = {k: list(v) for k, v in pools.items()}
        readmitted = sorted(set(excluded) - set(eff_excluded))
        if readmitted:
            out["readmit"] = readmitted
    elif eff_excluded:
        out["excluded"] = sorted(eff_excluded)
    return out


def gen_pending_core(game, records):
    """一站式入口（fetch 與 CLI 共用）。**sfg-v4：候選池＝全池，無排除區。**

    records 新→舊（同 BASE_REC）。回傳 pending 核心（呼叫端補 ts）。

    v4（2026-08-17）起不再呼叫 flatness_exclude —— 回測證實排除區無預測價值
    （T3 六個檢定全不顯著）且正在自我失效（長窗 93~97% 期數為空）。
    詳見本檔開頭「v4 變更紀錄」與 BACKTEST_REGISTRY.md。
    """
    if not records or len(records) < MIN_HIST:
        return {}
    pools, readmit_order = three_pools(game, records)
    anchors, anchor_gaps = overdue_anchors(game, records)
    return gen_four_groups(game, records[0]["p"], records[0]["n"],
                           readmit_order=readmit_order, pools=pools,
                           anchors=anchors, anchor_gaps=anchor_gaps)


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


def _verify_output(game, last_draw, res, records=None):
    """輸出必須滿足未放寬的所有規則；違者回傳錯誤訊息。"""
    cfg = GAMES[game]
    gs = list(res["strategies"].values())
    flat = [n for g in gs for n in g]
    errs = []
    if len(set(flat)) != 12:
        errs.append("12碼有重複")
    # sfg-v3 起不再驗「含上期號碼」——避上期已解除，上期號碼可再被選中
    for k, g in res["strategies"].items():
        a, b, c = g
        if not (a < b < c):
            errs.append(f"{k} 未升冪")
        if b - a == c - b:
            errs.append(f"{k} 違反 R2")
        if a % 10 == b % 10 == c % 10:
            errs.append(f"{k} 違反 R3")
        if "zone" not in res["relaxed"] and zone_of(a) == zone_of(b) == zone_of(c):
            errs.append(f"{k} 違反 R4")
    # G3 高號合計（sfg-v3 取代逐組 R1）
    highs = sum(1 for n in flat if n >= res["hi"])
    if highs < res.get("minHigh", MIN_HIGH_TOTAL):
        errs.append(f"違反 G3 高號合計（{highs} < {res.get('minHigh', MIN_HIGH_TOTAL)}）")
    if "cover" not in res["relaxed"]:
        if set(cfg["zones"]) - {zone_of(n) for n in flat}:
            errs.append("違反 G2 覆蓋")
    # sfg-v3：選號必須與有效排除區不相交（回補過的號碼已不在 excluded 內）
    hit_excl = set(flat) & set(res.get("excluded", []))
    if hit_excl:
        errs.append(f"選號含排除區號碼 {sorted(hit_excl)}")
    # sfg-v5：三池檢查（版號一律下限判定）
    if res.get("v", 0) >= 5:
        P = res.get("pools")
        if not P or any(k not in P for k in ("lz", "gap1", "od")):
            errs.append("v5 缺 pools 欄位")
        else:
            a, b, c = set(P["lz"]), set(P["gap1"]), set(P["od"])
            if a & b or a & c or b & c:
                errs.append("三池不互斥")
            allowed = a | b | c | set(res.get("readmit", []))
            outside = set(flat) - allowed
            if outside:
                errs.append(f"選號不在三池內 {sorted(outside)}")
            if records is not None:
                exp, _ = three_pools(game, records)
                if exp != P:
                    errs.append("三池與 records 重算不一致")
        if "excluded" in res:
            errs.append("v5 不得輸出 excluded")
    # sfg-v6：主號必須依序在 A/B/C/D 各一顆；與 records 重算一致
    if res.get("v", 0) >= 6:
        A = res.get("anchors")
        if A is None:
            errs.append("v6 缺 anchors")
        else:
            gl = list(res["strategies"].values())
            for i, a in enumerate(A):
                if i >= 4 or a not in gl[i]:
                    errs.append(f"主號 {a} 不在第 {i+1} 組")
            if len(set(A)) != len(A):
                errs.append("主號重複")
            if records is not None:
                expA, expG = overdue_anchors(game, records)
                if expA != A or expG != res.get("anchorGaps"):
                    errs.append("主號與 records 重算不一致")
    return errs


def selftest():
    """三彩種全歷史回放：確定性 ×3、規則全過、fallback 統計。

    sfg-v4：排除區已廢除，故不再統計排除區大小；改為驗證產線輸出**確實不含**
    excluded/exclAlgo/exclDepths —— 若哪天有人把 fpx 接回產線，這裡會立刻擋下。
    """
    ok = True
    for game in ("539", "f5", "m6"):
        recs = _read_records(game)
        if len(recs) < 2:
            print(f"[{game}] 讀不到足夠歷史，跳過")
            ok = False
            continue
        fallback_n = pool_relax_n = lex_n = n = 0
        psizes = []
        anchor_n = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        for i in range(len(recs)):
            hist = recs[i:]
            if len(hist) < 40:
                break  # 與 build_log_entries 的 backfill 門檻一致
            res1 = gen_pending_core(game, hist)
            res2 = gen_pending_core(game, hist)
            if res1 != res2:
                print(f"[{game}] 期 {hist[0]['p']} 確定性失敗！")
                ok = False
            errs = _verify_output(game, hist[0]["n"], res1, records=hist)
            if errs:
                print(f"[{game}] 期 {hist[0]['p']} 規則違規: {errs}")
                ok = False
            # v4 閘門：產線輸出不得再帶排除區欄位
            stale = [k for k in ("excluded", "exclAlgo", "exclDepths") if k in res1]
            if stale:
                print(f"[{game}] 期 {hist[0]['p']} 🔴 v4 仍輸出排除區欄位 {stale}")
                ok = False
            if res1.get("v", 0) < ALGO_V:
                print(f"[{game}] 期 {hist[0]['p']} 版號 {res1.get('v')} != {ALGO_V}")
                ok = False
            n += 1
            P = res1.get("pools", {})
            psizes.append(len(P.get("lz", [])) + len(P.get("gap1", [])) + len(P.get("od", [])))
            anchor_n[len(res1.get("anchors", []))] += 1
            if res1["relaxed"]:
                fallback_n += 1
            if "pool" in res1["relaxed"]:
                pool_relax_n += 1
            if "lex" in res1["relaxed"]:
                lex_n += 1
        ps = f"池 min {min(psizes)}／avg {sum(psizes)/len(psizes):.1f}／max {max(psizes)}" if psizes else "池 —"
        print(f"[{game}] 主號顆數分佈 " + " ".join(f"{k}顆:{v}" for k, v in anchor_n.items()))
        print(f"[{game}] {n} 期回放完成｜{ALGO}（三池＋主號）｜{ps}"
              f"｜fallback {fallback_n}（pool 回補 {pool_relax_n}、lex {lex_n}）")
    # 回歸案例：曾經讓引擎當掉的歷史期（需 history_*.json；BASE_REC 只有近一年）
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for game, at in (("539", 98073),):   # 2026-11-28 Fable 第四輪：lex 剪枝漏算後組主號
        try:
            H = json.load(open(os.path.join(here, f"history_{game}.json"), encoding="utf-8"))
        except OSError:
            print(f"[{game}] 回歸案例 {at}：缺 history 檔，跳過"); continue
        recs = sorted(({"p": r["p"], "n": r["n"]} for r in H if r["p"] <= at), key=lambda r: -r["p"])[:3000]
        try:
            res = gen_pending_core(game, recs)
            errs = _verify_output(game, recs[0]["n"], res, records=recs)
            print(f"[{game}] 回歸案例 {at}：", "通過 ✅" if not errs else errs)
            ok = ok and not errs
        except RuntimeError as ex:
            print(f"[{game}] 回歸案例 {at}：🔴 {ex}"); ok = False
    print("SELFTEST", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


def _print_core(game, res):
    cfg = GAMES[game]
    s0 = derive_seed(res["seed"], cfg["salt"])
    print(f"seed 導出: ({res['seed']} × 1000003 + {cfg['salt']}) mod 2147483646 + 1 = {s0}")
    print(f"v={res.get('v')}  algo={res.get('algo')}  hi={res['hi']}  "
          f"relaxed={res['relaxed']}")
    # v4 起產線無排除區；僅在有值時才印（回測傳 excluded 進來時仍看得到）
    if "anchors" in res:
        print(f"ANCHORS {res['anchors']} gaps={res.get('anchorGaps', [])}")
    if res.get("pools"):
        P = res["pools"]
        print(f"POOLS lz={P['lz']} gap1={P['gap1']} od={P['od']}"
              + (f" readmit={res['readmit']}" if res.get("readmit") else ""))
    if res.get("excluded"):
        print(f"  EXCL: {res['excluded']}  depths={res.get('exclDepths', [])}"
              f"  ({res.get('exclAlgo', '—')})")
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
        errs = _verify_output(game, recs[0]["n"], res, records=recs)
        print("規則自檢:", "全過 ✅" if not errs else errs)
        return 0

    # 歷史驗算：pick_engine.py <game> --at <期號> —— 以 BASE_REC 截至該期（含）重算（v5 三池需要歷史）
    if len(argv) == 4 and argv[1] in GAMES and argv[2] == "--at":
        game, at = argv[1], int(argv[3])
        recs = [r for r in _read_records(game) if r["p"] <= at]
        if not recs or recs[0]["p"] != at:
            print(f"BASE_REC 找不到第 {at} 期"); return 2
        res = gen_pending_core(game, recs)
        if not res:
            print(f"歷史不足 {MIN_HIST} 期，不產號"); return 2
        _print_core(game, res)
        errs = _verify_output(game, recs[0]["n"], res, records=recs)
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
        # 手動模式沒有歷史、本來就沒有 pools/anchors：用 v4 口徑自檢，免得每次都印「v5 缺 pools／v6 缺 anchors」假錯誤
        errs = _verify_output(game, last_draw, {**res, "v": 4})
        print("規則自檢:", "全過 ✅" if not errs else errs)
        print("（手動模式只有上期號碼、沒有歷史，算不出 v5 三池：此為全池裸算，"
              "與正式發布不同；要重現正式號碼請用 --at <期號>）")
        return 0

    print(__doc__)
    print("用法: pick_engine.py <539|f5|m6>                      # 讀 data 檔完整重算（驗算用）")
    print("      pick_engine.py <game> --at <期號>                 # 以截至該期的歷史重算（v5）")
    print("      pick_engine.py <game> <上期期號> \"<上期號碼>\" [--excluded \"n,...\"]")
    print("      pick_engine.py --selftest")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
