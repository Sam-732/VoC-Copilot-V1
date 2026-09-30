@echo off
rem Daily VoC Copilot job. Safe to run by hand or from Task Scheduler.
rem Runs from this file's folder so relative paths (reviews.db, logs\) resolve.
rem ingest -> assign -> rank -> dashboard
cd /d "%~dp0"
python daily_ingest.py
rem 0 = ok, 2 = ok but anomalous (still assign what arrived), 1 = failed (skip the rest)
if %ERRORLEVEL% EQU 1 exit /b 1
set INGEST_RC=%ERRORLEVEL%
python assign.py >> logs\assign.log 2>&1
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python rank.py >> logs\assign.log 2>&1
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python dashboard_v2.py >> logs\assign.log 2>&1
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
exit /b %INGEST_RC%
