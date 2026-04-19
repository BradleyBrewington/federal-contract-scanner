@echo off
REM Daily Federal Contract Opportunity Scan
REM Run this via Windows Task Scheduler at 6 AM daily

cd /d "C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search"
call python src/main.py --scan >> logs\scan_%date:~-4,4%%date:~-10,2%%date:~-7,2%.log 2>&1
