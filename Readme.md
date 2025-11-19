# 啟動

## 批次啟動

### 執行 start_curridata.bat

第 19 行的 `cd /d "%~dp0"`代表使用當前目錄執行後續指令，
所以建議批次檔不要移動到其他路徑，用捷徑方式執行即可。

## 手動逐步啟動

1.  開啟本程式：按 F5 啟動，因為有在.vscode/launch.json 設定  
    或輸入指令 `uvicorn main:app --host 0.0.0.0 --port 8000`
2.  開啟 ngrok：開啟 cmd 輸入`ngrok http 8000`

# database_helper.py

管理資料庫連線和游標的上下文管理器(context manager)
