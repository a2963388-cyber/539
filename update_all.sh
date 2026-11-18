#!/bin/bash
# 開機後與排程時段自動抓取最新彩券開獎（com.lottery.update）
# 2026-11-18：加時間戳。F5 來源 lottolyzer 公布時間不固定（11/18 到 11:00 都還沒有 11/17 那期），
#             沒有時間戳就查不出「是排程沒跑還是來源還沒更新」。
sleep 10  # 等網路就緒
echo "════ $(date '+%F %H:%M:%S') update_all 開始 ════"
/usr/bin/python3 /Users/dujunyang/539/539_fetch.py
/usr/bin/python3 /Users/dujunyang/539/fantasy5_fetch.py
/usr/bin/python3 /Users/dujunyang/539/marksix_fetch.py
echo "════ $(date '+%F %H:%M:%S') update_all 結束 ════"
