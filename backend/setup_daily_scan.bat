@echo off
REM Setup Windows Task Scheduler for daily scans at 6 AM

echo Creating logs directory...
mkdir "C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search\logs" 2>nul

echo.
echo Creating scheduled task: FederalContractScanner
echo This will run daily at 6:00 AM
echo.

schtasks /create /tn "FederalContractScanner" /tr "C:\Users\bmbre\OneDrive\Desktop\Projects\SAM_Opportunity_Search\run_daily_scan.bat" /sc daily /st 06:00 /f

echo.
echo Done! Task scheduled.
echo.
echo To view/modify: Open Task Scheduler and look for "FederalContractScanner"
echo To run now: schtasks /run /tn "FederalContractScanner"
echo To delete: schtasks /delete /tn "FederalContractScanner" /f
echo.
pause
