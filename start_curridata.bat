@echo off
title Curridata FastAPI Server & NGROK Launcher

:: ----------------------------------------------------------------------
:: --- 設定變數 ---
:: ----------------------------------------------------------------------
set SERVER_PORT=8000
set NGROK_EXE=ngrok
:: ----------------------------------------------------------------------

echo ======================================================
echo 🚀 Curridata FastAPI Server & NGROK 自動啟動器
echo ======================================================
echo.

:: --- [1/2] 啟動 FastAPI 伺服器 (在新視窗中) ---
echo [1/2] 正在背景啟動 FastAPI 伺服器 (uvicorn main:app)...
:: 'cd' 到專案目錄，確保 uvicorn 能找到 main.py 模組
cd /d "%~dp0"
start "FastAPI Server" uvicorn main:app --host 0.0.0.0 --port %SERVER_PORT%

:: 為了確保伺服器有足夠時間啟動，暫停 3 秒
timeout /t 3 /nobreak > nul

:: --- [2/2] 啟動 NGROK (在當前視窗中) ---
echo.
echo [2/2] 正在啟動 NGROK http %SERVER_PORT%...
echo 請勿關閉此視窗，否則 NGROK 連線會中斷。
echo ======================================================
echo.

:: NGROK 在當前視窗執行
%NGROK_EXE% http %SERVER_PORT%

:: NGROK 結束後，批次檔會繼續執行
echo.
echo NGROK 連線已關閉。
pause