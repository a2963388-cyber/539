#!/bin/bash
# 開機後自動抓取最新彩券開獎
sleep 10  # 等網路就緒

/usr/bin/python3 /Users/dujunyang/539/539_fetch.py
/usr/bin/python3 /Users/dujunyang/539/fantasy5_fetch.py
/usr/bin/python3 /Users/dujunyang/539/marksix_fetch.py
