"""全歷史滾動回測：每期只用之前的資料產生預測（out-of-sample），
直接呼叫三個 fetch 模組的 gen_all_predictions，與產線邏輯 100% 一致"""
import importlib.util, json, math, re
from pathlib import Path

HOME = Path.home() / '539'
MIN_TRAIN = 30   # 至少 30 期訓練資料才開始測

def load_mod(fname):
    spec = importlib.util.spec_from_file_location(fname.replace('.py', ''), HOME / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def parse_rec(html):
    m = re.search(r"const BASE_REC = \[(.*?)\n\];?", html, re.DOTALL)
    cleaned = m.group(1).strip().rstrip(',').strip()
    return json.loads('[' + re.sub(r'(\b[a-z]\w*\b):', r'"\1":', cleaned) + ']')

def t_ci(vals, mu0):
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0
    ci = 1.96 * se
    z = (mean - mu0) / se if se > 0 else 0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return mean, ci, p

SYSTEMS = [
    ('539',    '539_fetch.py',      'data_539.js', 5, 39),
    ('F5',     'fantasy5_fetch.py', 'data_f5.js',  5, 39),
    ('六合彩', 'marksix_fetch.py',  'data_m6.js',  6, 49),
]

for label, script, datafile, draw_n, pool in SYSTEMS:
    mod = load_mod(script)
    html = (HOME / datafile).read_text(encoding='utf-8')
    records = parse_rec(html)          # 新到舊
    st_mg = mod.read_base_st(html)
    exp = mod.PICK_N * draw_n / pool
    hits = {}
    tested = 0
    for i in range(len(records) - MIN_TRAIN):
        train = records[i + 1:]        # 只用該期之前的歷史
        actual = set(records[i]['n'])
        strat = mod.gen_all_predictions(train, st_mg)
        if not strat:
            continue
        tested += 1
        for g, nums in strat.items():
            hits.setdefault(g, []).append(len(set(nums) & actual))
    print(f"\n=== {label}｜可測 {tested} 期（訓練≥{MIN_TRAIN}期）｜隨機期望 {exp:.3f} 中/期 ===")
    print(f"{'策略':<5}{'平均命中':>8}{'±95%CI':>8}{'p值':>7}{'中2+':>6}{'中3+':>6}{'中4+':>6}")
    rows = []
    for g, v in hits.items():
        mean, ci, p = t_ci(v, exp)
        rows.append((g, mean, ci, p, sum(1 for x in v if x >= 2),
                     sum(1 for x in v if x >= 3), sum(1 for x in v if x >= 4)))
    for g, mean, ci, p, h2, h3, h4 in sorted(rows, key=lambda r: -r[1]):
        mark = ' *' if p < 0.05 else ''
        print(f"{g:<6}{mean:>8.3f}{ci:>8.2f}{p:>7.3f}{h2:>6}{h3:>6}{h4:>6}{mark}")
