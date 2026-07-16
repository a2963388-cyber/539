#!/usr/bin/env python3
"""回測 v2：長歷史滾動回測 + 蒙地卡羅 best-of-K 經驗零假設 + 走前式換馬模擬 + 539 真實下注 ROI
- 每期預測只用該期之前的歷史（out-of-sample），直接呼叫產線 fetch 模組
- 歷史來源：history_*.json（fetch_history.py 產出）；缺檔時退回 data_*.js 的 BASE_REC
- 結果寫入 backtest_v2_results.json 供報告頁使用
用法：python3 backtest_v2.py [--max-test 1500] [--mc 1000] [--systems 539,f5,m6]
"""
import argparse, importlib.util, json, math, random, re, time
from math import comb
from pathlib import Path

HOME = Path(__file__).parent
MIN_TRAIN = 100          # 至少 100 期訓練資料才開始測

# 539 固定獎金表（元）：中2/中3/中4/中5
PRIZE_539 = {2: 50, 3: 300, 4: 20000, 5: 8000000}
BET_PRICE = 50


def load_mod(fname):
    spec = importlib.util.spec_from_file_location(fname.replace('.py', ''), HOME / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_base_rec(html):
    m = re.search(r"const BASE_REC = \[(.*?)\n\];?", html, re.DOTALL)
    cleaned = m.group(1).strip().rstrip(',').strip()
    return json.loads('[' + re.sub(r'(\b[a-z]\w*\b):', r'"\1":', cleaned) + ']')


def load_history(hist_file, data_file):
    """優先 history_*.json；並用 BASE_REC 補最新（歷史檔可能落後幾期）。回傳新到舊。"""
    html = (HOME / data_file).read_text(encoding='utf-8')
    base = parse_base_rec(html)
    hp = HOME / hist_file
    if not hp.exists():
        print(f"  ⚠️ 無 {hist_file}，退回 BASE_REC（{len(base)} 期）")
        return base, html
    hist = json.loads(hp.read_text())
    for r in hist:
        if 'p' not in r:   # M6 歷史檔：draw "YY/NNN" → p
            yy, nnn = r['draw'].split('/')
            r['p'] = int(yy) * 1000 + int(nnn)
    seen = {}
    for r in hist + base:
        key = r.get('dt', r['p'])   # M6 用日期當 key（YY 跨世紀），其他用期號
        seen.setdefault(key, r)
    merged = list(seen.values())
    if 'dt' in merged[0]:
        merged.sort(key=lambda x: x['dt'], reverse=True)
    else:
        merged.sort(key=lambda x: -x['p'])
    return merged, html


def hyperg_pmf(pool, draw, pick):
    tot = comb(pool, pick)
    return [comb(draw, k) * comb(pool - draw, pick - k) / tot for k in range(draw + 1)]


def mc_best_of_k(n_periods, k_strats, pool, draw, pick, families, rng):
    """模擬 families 組「K 個隨機策略」家族，回傳每家族最佳平均命中的分佈（排序後）"""
    vals = list(range(draw + 1))
    w = hyperg_pmf(pool, draw, pick)
    best = []
    for _ in range(families):
        m = 0.0
        for _ in range(k_strats):
            s = sum(rng.choices(vals, weights=w, k=n_periods)) / n_periods
            if s > m:
                m = s
        best.append(m)
    best.sort()
    return best


def pctile_of(sorted_null, x):
    import bisect
    return bisect.bisect_left(sorted_null, x) / len(sorted_null) * 100


def roi_539(hits_seq):
    """8碼包牌 C(8,5)=56 注×50元，逐期結算。回傳總覽與累積淨值曲線（抽樣壓縮）"""
    cost_per = comb(8, 5) * BET_PRICE
    net, cum, curve = 0, [], []
    for h in hits_seq:
        pay = sum(comb(h, k) * comb(8 - h, 5 - k) * PRIZE_539[k] for k in (2, 3, 4, 5) if k <= h)
        net += pay - cost_per
        cum.append(net)
    peak, mdd = 0, 0
    for v in cum:
        peak = max(peak, v)
        mdd = min(mdd, v - peak)
    step = max(1, len(cum) // 200)
    curve = cum[::step]
    total_cost = cost_per * len(hits_seq)
    return {'periods': len(hits_seq), 'costPer': cost_per, 'totalCost': total_cost,
            'totalNet': net, 'roi': round(net / total_cost * 100, 2),
            'maxDrawdown': mdd, 'curve': curve, 'curveStep': step}


def run_system(label, script, data_file, hist_file, draw_n, pool, max_test, mc_n, rng):
    print(f"\n=== {label} ===", flush=True)
    mod = load_mod(script)
    records, html = load_history(hist_file, data_file)
    st_mg = mod.read_base_st(html)
    exp = mod.PICK_N * draw_n / pool
    total = len(records)
    testable = total - MIN_TRAIN
    n_test = min(testable, max_test) if max_test else testable
    print(f"  歷史 {total} 期，可測 {testable} 期，本次測最近 {n_test} 期", flush=True)

    # ── 滾動回測（i 新到舊；測試集取最近 n_test 期）────────────
    hits = {}
    t0 = time.time()
    for j, i in enumerate(range(n_test - 1, -1, -1)):      # 由舊到新
        strat = mod.gen_all_predictions(records[i + 1:], st_mg)
        actual = set(records[i]['n'])
        for g, nums in strat.items():
            hits.setdefault(g, []).append(len(set(nums) & actual))
        if (j + 1) % 300 == 0:
            print(f"  …{j+1}/{n_test}（{time.time()-t0:.0f}s）", flush=True)
    print(f"  回測完成（{time.time()-t0:.0f}s）", flush=True)

    stats = {}
    for g, v in hits.items():
        n = len(v)
        mean = sum(v) / n
        var = sum((x - mean) ** 2 for x in v) / (n - 1)
        se = math.sqrt(var / n)
        z = (mean - exp) / se if se else 0
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        stats[g] = {'n': n, 'mean': round(mean, 4), 'ci': round(1.96 * se, 4),
                    'p': round(p, 4), 'hit2': sum(1 for x in v if x >= 2),
                    'hit3': sum(1 for x in v if x >= 3), 'hit4': sum(1 for x in v if x >= 4),
                    'hit5': sum(1 for x in v if x >= 5)}

    # ── 蒙地卡羅 best-of-K 經驗零假設（K = 真策略數，不含 G0）──
    real = {g: s for g, s in stats.items() if g != 'G0'}
    K = len(real)
    best_g, best_s = max(real.items(), key=lambda kv: kv[1]['mean'])
    null_best = mc_best_of_k(n_test, K, pool, draw_n, mod.PICK_N, mc_n, rng)
    pct = pctile_of(null_best, best_s['mean'])
    mc = {'families': mc_n, 'K': K, 'bestReal': best_g, 'bestMean': best_s['mean'],
          'pctile': round(pct, 1), 'nullMedian': round(null_best[len(null_best)//2], 4),
          'null95': round(null_best[int(len(null_best)*0.95)], 4)}
    print(f"  MC：真策略最佳 {best_g} {best_s['mean']:.4f}，落在 best-of-{K} 零分佈第 {pct:.1f} 百分位"
          f"（零分佈中位 {mc['nullMedian']:.4f}／95分位 {mc['null95']:.4f}）", flush=True)

    # ── 走前式「換馬玩家」：每期押「當時累積均中最高」的真策略 ──
    WARM = min(30, max(1, n_test // 3))
    order = [g for g in hits if g != 'G0']
    sw_hits, sw_choices = [], {}
    for t in range(WARM, n_test):
        lead = max(order, key=lambda g: sum(hits[g][:t]) / t)
        sw_hits.append(hits[lead][t])
        sw_choices[lead] = sw_choices.get(lead, 0) + 1
    sw_mean = sum(sw_hits) / len(sw_hits)
    best_fixed = max(order, key=lambda g: sum(hits[g][WARM:]) / (n_test - WARM))
    switcher = {'n': len(sw_hits), 'mean': round(sw_mean, 4),
                'bestFixed': best_fixed,
                'bestFixedMean': round(sum(hits[best_fixed][WARM:]) / (n_test - WARM), 4),
                'g0Mean': round(sum(hits['G0'][WARM:]) / (n_test - WARM), 4),
                'choices': sw_choices}
    print(f"  換馬玩家 {sw_mean:.4f} vs 事後最佳單一 {switcher['bestFixedMean']:.4f} vs G0 {switcher['g0Mean']:.4f}", flush=True)

    out = {'label': label, 'exp': round(exp, 4), 'nTest': n_test, 'total': total,
           'minTrain': MIN_TRAIN, 'stats': stats, 'mc': mc, 'switcher': switcher}

    # ── 539 真實下注 ROI（固定獎金表才適用）─────────────────────
    if label == '539':
        out['roi'] = {g: roi_539(v) for g, v in hits.items()}
        for g in sorted(out['roi'], key=lambda g: -out['roi'][g]['roi']):
            r = out['roi'][g]
            print(f"  ROI {g}: {r['roi']:+.1f}%（投入 {r['totalCost']:,}，淨 {r['totalNet']:+,}）", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-test', type=int, default=1500)
    ap.add_argument('--mc', type=int, default=1000)
    ap.add_argument('--systems', default='539,f5,m6')
    args = ap.parse_args()
    rng = random.Random(20260716)   # 固定種子可重現

    conf = {
        '539': ('539',    '539_fetch.py',      'data_539.js', 'history_539.json', 5, 39),
        'f5':  ('F5',     'fantasy5_fetch.py', 'data_f5.js',  'history_f5.json',  5, 39),
        'm6':  ('六合彩', 'marksix_fetch.py',  'data_m6.js',  'history_m6.json',  6, 49),
    }
    results = {}
    for key in args.systems.split(','):
        label, script, df, hf, dn, pool = conf[key.strip()]
        results[key.strip()] = run_system(label, script, df, hf, dn, pool,
                                          args.max_test, args.mc, rng)
    (HOME / 'backtest_v2_results.json').write_text(
        json.dumps(results, ensure_ascii=False, separators=(',', ':')))
    print('\n✅ 結果已寫入 backtest_v2_results.json', flush=True)


if __name__ == '__main__':
    main()
