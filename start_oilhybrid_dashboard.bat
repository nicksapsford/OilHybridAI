@echo off
title OilHybrid A.I. Dashboard - Port 5045
cd /d C:\Users\abc\Desktop\OilHybridAI
start /min "OilHybrid A.I. Dashboard" cmd /c C:\Users\abc\AppData\Local\Programs\Python\Python313\python.exe dashboard_oil.py
timeout /t 5 /nobreak >nul
start http://localhost:5045
