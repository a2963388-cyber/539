# attic — 舊制凍結區（2026-08-09 減法重構）

10 策略 × 8 碼制已退役，以下檔案凍結保留供審計，**不再維護、不在產線路徑**：

- `meta.html` — 跨系統 meta-analysis。只適用 10 策略時代的 PICKLOG 格式，
  遇 v2（4組×3碼）條目其正則會產出錯誤結論，勿再開啟使用。
- `backtest_all.py` / `backtest_v2.py` — 舊策略離線回測，import 已刪除的
  gen_g* 與 PICK_N，無法執行。
- `marksix_fetch.py.bak-20260805` — 六合彩換源（lottolyzer→cpzhan）前的備份。
- `backtest_report_v2.html` / `backtest_v2_results.json` — 2026-07-16 舊制回測產出
  （G1/G3/G5/G6… 10 策略）。留在根目錄會與 v3 回測混淆，2026-08-16 移入。

## 2026-08-16 追加

- `backtest_engine_incremental.py` — v3 回測初期為「把 O(L²) 降成 O(L)」寫的增量式
  dist/gaps 推進。**後來證實前提是錯的**：`build_return_dist` 的內層迴圈平均 8 次即
  `break`（號碼平均 8 期回歸一次），單次全歷史僅 10–16ms，原版直接跑全量只要 2 分鐘，
  增量化毫無必要。
  🔴 **更重要的教訓**：此檔的 `--parity` 對拍閘門**自己是失效的** —— 故意把 dist 動一格，
  它仍回報「一致 ✅」（破壞太小不改變柱子排序）。**沒有先用 negative control 驗證過
  「抓不抓得到已知錯誤」的閘門，等於沒有閘門。** 現行 `../backtest.py --parity` 已改為
  兩段式：先確認破壞會被抓到，才承認「一致」有意義。

新制規格見 `../pick_engine.py`；v3 回測見 `../BACKTEST_REGISTRY.md`；
歷史 PICKLOG 原樣保留在各 data_*.js。
