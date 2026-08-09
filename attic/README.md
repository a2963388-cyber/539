# attic — 舊制凍結區（2026-08-09 減法重構）

10 策略 × 8 碼制已退役，以下檔案凍結保留供審計，**不再維護、不在產線路徑**：

- `meta.html` — 跨系統 meta-analysis。只適用 10 策略時代的 PICKLOG 格式，
  遇 v2（4組×3碼）條目其正則會產出錯誤結論，勿再開啟使用。
- `backtest_all.py` / `backtest_v2.py` — 舊策略離線回測，import 已刪除的
  gen_g* 與 PICK_N，無法執行。
- `marksix_fetch.py.bak-20260805` — 六合彩換源（lottolyzer→cpzhan）前的備份。

新制規格見 `../pick_engine.py`；歷史 PICKLOG 原樣保留在各 data_*.js。
