@echo off
title OilHybrid A.I. -- Service Mode
cd /d %~dp0

echo Starting OilHybrid A.I. in service mode (Task Scheduler)...

echo Cleaning up any existing OilHybrid processes...
powershell -NoProfile -Command "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*dashboard_oil.py*' -or $_.CommandLine -like '*watchdog_oil.py*' -or $_.CommandLine -like '*main_oilhybrid.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" > nul 2>&1
ping -n 3 127.0.0.1 > nul

start /B python dashboard_oil.py

ping -n 11 127.0.0.1 > nul

start /B python watchdog_oil.py

echo OilHybrid A.I. launched in background -- dashboard + watchdog running.
exit /b 0
