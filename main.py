import time
import tempfile
import os
import shutil
from starlette.responses import FileResponse
from fastapi import FastAPI, HTTPException, Request, Response, Body
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from pydantic import BaseModel
from typing import List, Optional, Literal

# 引入您提供的 MSSQL 資料庫輔助函數和例外
# Assumes database_helper.py is present and functional
from database_helper import execute_query, DatabaseError, UniqueConstraintError, DatabaseCursor

# 引入YT影片下載套件
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# --- IP 獲取輔助函式 (針對代理環境優化) ---
def get_client_ip(request: Request) -> str:
    """
    獲取客戶端 IP，優先檢查反向代理（如 ngrok）設定的標準標頭。
    """
    # 1. 檢查 X-Forwarded-For 標頭 (ngrok 會使用此標頭)
    # X-Forwarded-For 格式可能是 "client_ip, proxy1_ip, proxy2_ip"，我們取第一個
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    
    # 2. 檢查 X-Real-IP 標頭 (某些代理會使用此標頭)
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip
    
    # 3. 最終 fallback 到 Starlette 提供的 IP (適用於沒有代理的情況)
    return request.client.host if request.client else "Unknown"


# --- 1. 定義 Custom Middleware (IP 監控) ---
class ClientIPMiddleware(BaseHTTPMiddleware):
    """
    自定義中介軟體，用於記錄客戶端的 IP 位址、請求路徑和處理時間。
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 使用優化後的函式獲取真實 IP
        client_ip = get_client_ip(request)

        start_time = time.time()
        
        # 顯示請求 IP、方法和路徑
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] IP: {client_ip} | METHOD: {request.method} | PATH: {request.url.path}")

        # 將 IP 儲存在請求的 state 中
        request.state.client_ip = client_ip

        # 繼續處理請求
        response = await call_next(request)

        # 請求處理完畢，計算耗時並記錄
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        print(f"IP: {client_ip} 的請求已完成，耗時: {process_time:.4f}s")
        return response

# 初始化 FastAPI 應用
app = FastAPI(title="Dept Management API")

# 允許所有來源進行 CORS 跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. 啟用 IP 監控中介軟體 ---
# 確保這個中介軟體在所有路由處理之前運行
app.add_middleware(ClientIPMiddleware)

# --- 資料模型 (Pydantic) ---
# YT下載請求模型
class DownloadRequest(BaseModel):
    """定義客戶端傳入的請求體結構"""
    url: str
    # 限定格式只能是 'mp3' 或 'mp4'
    format: Literal["mp3", "mp4"]

# 基礎系所資訊
class Dept(BaseModel):
    COLLEGE: str
    COLLEGE_S: str
    DEPT: str
    DEPT_S: str
    STYPE: str
    CAGENT_ID: int

# 新增系所及更新系所使用的模型：繼承自 Dept
class DeptWithAgent(Dept):
    AGENT_NAME: str
    AGENT_EXT: str
    AGENT_EMAIL: str

# 課務組承辦人基礎資訊
class CAgent(BaseModel):
    NAME: str
    EXT: str
    EMAIL: str

# 班級-系所簡稱對照表模型
class MAP_CLS_DEPT(BaseModel):
    CLASS: str
    DEPT_S: str

# --- API 端點 ---
# 測試GET功能
@app.get("/get_test", summary="測試GET")
async def get_test():
    print("get test成功")
    return "get test 成功了"
# 測試POST功能
@app.post("/post_test", summary="測試POST")
async def post_test(item: DownloadRequest):
    print("url: ", item.url)
    print("format: ", item.format)
    
    return "post成功囉"

# --- DEPTS ---
# 1. 讀取系所表(含承辦人及課務組承辦人資料)
@app.get("/get_depts", summary="讀取所有系所資料及承辦人資訊")
async def get_depts():
    try:
        sql = """
SELECT
    d.ID, COLLEGE, COLLEGE_S, DEPT, DEPT_S, STYPE, 
    AGENT_NAME, AGENT_EXT, AGENT_EMAIL,
    ca.ID as CAGENT_ID, ca.NAME as CAGENT_NAME, ca.EXT as CAGENT_EXT, ca.EMAIL as CAGENT_EMAIL
FROM
    DEPTS AS d
LEFT JOIN
    CAGENTS AS ca ON d.CAGENT_ID = ca.ID;
"""
        data = execute_query(sql)
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch departments: {e}")

# 2. 新增系所到DEPTS(含承辦人及課務組承辦人資料)
@app.post("/create_dept", summary="新增系所資料")
async def create_dept(item: DeptWithAgent):
    """
    建立新的系所資料，使用標準 INSERT 語句，不回傳 ID。
    """
    sql = """
        INSERT INTO DEPTS (COLLEGE, COLLEGE_S, DEPT, DEPT_S, STYPE, AGENT_NAME, AGENT_EXT, AGENT_EMAIL, CAGENT_ID)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    values = (item.COLLEGE, item.COLLEGE_S, item.DEPT, item.DEPT_S, item.STYPE, item.AGENT_NAME, item.AGENT_EXT, item.AGENT_EMAIL, item.CAGENT_ID)
    
    try:
        execute_query(sql, values)
        return {"message": "Department added successfully."}

    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to create department: 唯一約束衝突 (可能系所名稱或簡稱已存在)")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create department: 資料庫錯誤: {e}")

# 3. 修改dept資料
@app.put("/update_dept/{dept_id}", summary="修改指定 ID 的系所資料")
async def update_dept(dept_id: int, item: DeptWithAgent):
    sql = """
        UPDATE DEPTS SET
        COLLEGE = ?, COLLEGE_S = ?, DEPT = ?, DEPT_S = ?, STYPE = ?, AGENT_NAME = ?, AGENT_EXT = ?, AGENT_EMAIL = ?, CAGENT_ID = ?
        WHERE ID = ?
    """
    values = (item.COLLEGE, item.COLLEGE_S, item.DEPT, item.DEPT_S, item.STYPE, item.AGENT_NAME, item.AGENT_EXT, item.AGENT_EMAIL, item.CAGENT_ID, dept_id)
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Department with ID {dept_id} not found.")
        return {"message": "Department updated successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to update department: 唯一約束衝突")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update department: {e}")

# 4. 刪除dept
@app.delete("/delete_dept/{dept_id}", summary="刪除指定 ID 的系所資料")
async def delete_dept(dept_id: int):
    try:
        # 確保參數以 tuple 形式傳遞
        result = execute_query("DELETE FROM DEPTS WHERE ID = ?", (dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Department with ID {dept_id} not found.")
        return {"message": "Department deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete department: {e}")

# --- CAGENTS ---
# 5. 查詢課務組承辦人資料
@app.get("/get_cagents", summary="查詢所有課務組承辦人資料")
async def get_cagents():
    try:
        sql = "SELECT * FROM CAGENTS"
        data = execute_query(sql)
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch C Agents: {e}")

# 6. 新增課務組承辦人CAGENTS (使用 CAgent)
@app.post("/create_cagent", summary="新增課務組承辦人資料")
async def create_cagent(item: CAgent):
    sql = """
        INSERT INTO CAGENTS (NAME, EXT, EMAIL)
        VALUES (?, ?, ?);
    """
    values = (item.NAME, item.EXT, item.EMAIL)
    
    try:
        execute_query(sql, values)
        return {"message": "Curri agent added successfully."}

    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to create Curri agent: 唯一約束衝突 (可能姓名或 Email 已存在)")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Curri agent: 資料庫錯誤: {e}")

# 7. 修改課務組承辦人 (使用 CAgent)
@app.put("/update_cagent/{cagent_id}", summary="修改指定 ID 的課務組承辦人資料")
async def update_cagent(cagent_id: int, item: CAgent):
    sql = """
        UPDATE CAGENTS SET
        NAME = ?, EXT = ?, EMAIL = ?
        WHERE ID = ?
    """
    values = (item.NAME, item.EXT, item.EMAIL, cagent_id)
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Curri agent with ID {cagent_id} not found.")
        return {"message": "Curri agent updated successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to update Curri agent: 唯一約束衝突")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update Curri agent: {e}")

# 8. 刪除課務組承辦人
@app.delete("/delete_cagent/{cagent_id}", summary="刪除指定 ID 的課務組承辦人資料")
async def delete_cagent(cagent_id: int):
    try:
        result = execute_query("DELETE FROM CAGENTS WHERE ID = ?", (cagent_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Curri agent with ID {cagent_id} not found.")
        return {"message": "Curri agent deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete Curri agent: {e}")


# 9. 呼叫 sp_GetAll 預存程序 for ClassConverter
@app.get("/get_all_data")
async def get_all_data():
    try:
        data = execute_query("EXEC sp_GetAll")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")

# --- MAP_CLS_DEPT ---
# 10. 查詢班級-系所簡稱對照表
@app.get("/get_map_cls_dept", summary="查詢所有班級-系所簡稱對照資料")
async def get_map_cls_dept():
    try:
        sql = "SELECT * FROM MAP_CLS_DEPT"
        data = execute_query(sql)
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class-dept mapping: {e}")

# 11. 新增班級-系所簡稱
@app.post("/create_map_cls_dept", summary="新增班級-系所簡稱對照")
async def create_map_cls_dept(item: MAP_CLS_DEPT):
    sql = """
        INSERT INTO MAP_CLS_DEPT (CLASS, DEPT_S)
        VALUES (?, ?);
    """
    values = (item.CLASS, item.DEPT_S)
    
    try:
        execute_query(sql, values)
        return {"message": "Class-dept_short added successfully."}

    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to create class-dept_short: 唯一約束衝突 (班級與簡稱組合可能已存在)")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create class-dept_short: 資料庫錯誤: {e}")

# 12. 修改班級-系所簡稱
@app.put("/update_map_cls_dept/{map_cls_dept_id}", summary="修改指定 ID 的班級-系所簡稱對照")
async def update_map_cls_dept(map_cls_dept_id: int, item: MAP_CLS_DEPT):
    sql = """
        UPDATE MAP_CLS_DEPT SET
        CLASS = ?, DEPT_S = ?
        WHERE ID = ?
    """
    values = (item.CLASS, item.DEPT_S, map_cls_dept_id)
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Class-dept_short with ID {map_cls_dept_id} not found.")
        return {"message": "class-dept_short updated successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to update class-dept_short: 唯一約束衝突")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update class-dept_short: {e}")

# 13. 刪除班級-系所簡稱
@app.delete("/delete_map_cls_dept/{map_cls_dept_id}", summary="刪除指定 ID 的班級-系所簡稱對照")
async def delete_map_cls_dept(map_cls_dept_id: int):
    try:
        result = execute_query("DELETE FROM MAP_CLS_DEPT WHERE ID = ?", (map_cls_dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Class-dept_short with ID {map_cls_dept_id} not found.")
        return {"message": "class-dept_short deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete class-dept_short: {e}")

# 14. YT影片下載
@app.post("/download")
def start_download(request: DownloadRequest = Body(...)):
    """
    接收 YouTube 網址和格式，在伺服器端下載文件，並將其傳回給客戶端。
    
    由於 yt-dlp 是一個阻塞的 I/O 操作，FastAPI 會自動在背景線程中執行此同步函數，
    確保主事件迴圈不被阻塞。
    """
    
    url = request.url
    target_format = request.format
    temp_dir = None
    final_filepath = None
    
    print(f"接收到下載請求 - 網址: {url}, 格式: {target_format.upper()}")

    # 1. 創建一個臨時目錄來存放下載和轉碼過程中的文件
    try:
        temp_dir = tempfile.mkdtemp()
        
        # 根據目標格式設定 yt-dlp 選項
        if target_format == 'mp3':
            ydl_opts = {
                # 選擇最佳音訊
                'format': 'bestaudio/best',
                # 輸出模板: 在臨時目錄中，使用標題作為檔名，yt-dlp 會自動處理轉碼後的副檔名
                'outtmpl': os.path.join(temp_dir, '%(title)s'),
                'noplaylist': True,
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }],
            }
            # 預期的最終副檔名
            expected_ext = '.mp3'
            
        elif target_format == 'mp4':
            ydl_opts = {
                # 選擇最佳的影片和音訊
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                # 合併後轉為 MP4
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'quiet': True,
            }
            # 預期的最終副檔名
            expected_ext = '.mp4'

        # 2. 執行 yt-dlp 下載和轉碼
        with YoutubeDL(ydl_opts) as ydl:
            # 獲取資訊 (不下載) 以預測檔名
            try:
                info_dict = ydl.extract_info(url, download=False)
            except Exception as e:
                # 處理 yt-dlp 無法解析網址的錯誤
                print(f"yt-dlp 解析錯誤: {e}")
                raise HTTPException(status_code=400, detail="無法解析影片網址或影片不存在。")

            # 使用 yt-dlp 的 prepare_filename 方法來獲取經過清理和處理的檔名
            base_filename = ydl.prepare_filename(info_dict)
            
            # 根據輸出模板和目標格式，準確預測最終文件的路徑
            if target_format == 'mp3':
                 # MP3 會先下載一個原始檔 (例如 .m4a)，然後轉碼為 .mp3
                final_filename = os.path.basename(os.path.splitext(base_filename)[0]) + expected_ext
            else: # MP4
                # MP4 會合併兩個流 (影片+音訊)，最終使用 outtmpl 的副檔名
                final_filename = os.path.basename(base_filename) 

            final_filepath = os.path.join(temp_dir, final_filename)
            
            print(f"預計檔名: {final_filename}")

            # 執行下載和後處理 (轉碼)
            ydl.download([url])

        # 3. 檢查文件是否成功生成
        if not os.path.exists(final_filepath):
            raise HTTPException(status_code=500, detail="文件生成失敗，請檢查伺服器日誌或 FFmpeg 安裝。")
            
        # 4. 準備 FileResponse
        # Filename 參數用於設定下載時顯示的檔名
        # background 參數確保在文件傳輸完成後執行清理工作
        
        print(f"文件大小: {os.path.getsize(final_filepath) / (1024*1024):.2f} MB")
        print("開始串流回覆給客戶端...")

        # 使用 FileResponse 進行串流並設定 Content-Disposition 讓瀏覽器立即下載
        response = FileResponse(
            path=final_filepath,
            filename=final_filename,  # 這是瀏覽器看到和儲存的檔名
            media_type=f'application/{target_format}',
            
            # --- 這是強制瀏覽器下載的關鍵 ---
            headers={
                # attachment 告訴瀏覽器這是一個要下載的文件
                'Content-Disposition': f'attachment; filename="{final_filename}"',
            }
        )
        
        return response

    except DownloadError as e:
        print(f"yt-dlp 內部下載錯誤: {e}")
        raise HTTPException(status_code=500, detail="下載或轉碼過程中發生錯誤。")
        
    except Exception as e:
        print(f"伺服器處理錯誤: {e}")
        raise HTTPException(status_code=500, detail=f"伺服器內部錯誤: {e}")
        
    finally:
        # 5. 清理臨時目錄 (無論成功或失敗都必須執行)
        if temp_dir and os.path.exists(temp_dir):
            # 由於 FileResponse 會在文件傳輸完成後自動執行清理，
            # 我們不能在 return 之後立即刪除，但對於這種簡單的同步請求，
            # 簡單的 finally block 可以在 FileResponse 內部處理完成後被調用。
            # 更安全的做法是使用 FastAPI 的 BackgroundTasks，但為了簡單性，
            # 且 FileResponse 的處理通常是 I/O 密集型且最後才關閉文件描述符，
            # 我們將清理邏輯放在一個獨立的函數並確保它在傳輸後運行 (在實際生產環境中，會使用 BackgroundTasks)。
            
            # **注意**: 在這個簡單的同步函數中，FastAPI 會在 `FileResponse` 完成響應後，
            # 才真正結束這個請求的上下文。然而，為了確保文件在傳輸後被刪除，
            # 最佳實踐是在 `FileResponse` 完成後使用 `BackgroundTasks`。
            
            # 由於我們只生成單一文件，我們可以讓 `FileResponse` 執行完畢，然後依賴
            # FastAPI 處理線程的銷毀。
            
            pass # 這裡不進行清理，我們需要將清理工作移至 BackgroundTasks 或讓 FileResponse 的 `cleanup_callback` 處理。

# --- 額外增加：手動清理函式 ---
# 由於 FileResponse 的生命週期和同步函數的 Finally 塊可能會導致競爭條件，
# 讓 FileResponse 在完成後自行處理清理會更安全。
# 我們將修改 FileResponse 讓它執行清理。

@app.post("/download_final")
async def start_download_final(request: DownloadRequest = Body(...)):
    """
    更新後的端點，使用 BackgroundTasks 確保文件在客戶端接收後被清理。
    """
    
    url = request.url
    target_format = request.format
    print("已接收到客戶端請求")
    print("url = ", url)
    print("format = ", target_format)


    temp_dir = None
    final_filepath = None
    
    print(f"接收到下載請求 - 網址: {url}, 格式: {target_format.upper()}")

    # 1. 創建一個臨時目錄
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 根據目標格式設定 yt-dlp 選項
        if target_format == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, '%(title)s'),
                'noplaylist': True,
                'quiet': True,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            }
            expected_ext = '.mp3'
            
        elif target_format == 'mp4':
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'quiet': True,
            }
            expected_ext = '.mp4'
        
        # 2. 執行 yt-dlp
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            base_filename = ydl.prepare_filename(info_dict)
            
            if target_format == 'mp3':
                final_filename = os.path.basename(os.path.splitext(base_filename)[0]) + expected_ext
            else:
                final_filename = os.path.basename(base_filename) 

            final_filepath = os.path.join(temp_dir, final_filename)
            
            print(f"預計檔名: {final_filename}")

            ydl.download([url])
            
        if not os.path.exists(final_filepath):
            raise HTTPException(status_code=500, detail="文件生成失敗。")

        # 3. 準備 FileResponse
        print(f"文件大小: {os.path.getsize(final_filepath) / (1024*1024):.2f} MB")
        print("開始串流回覆給客戶端並準備背景清理...")

        # 自定義 FileResponse 類別來添加清理邏輯
        class CleanUpFileResponse(FileResponse):
            def __init__(self, path: str, temp_dir: str, **kwargs):
                super().__init__(path=path, **kwargs)
                self.temp_dir = temp_dir
            
            # 在響應完成後，這個方法會被調用 (這是 FileResponse 內部處理的)
            async def close(self):
                await super().close()
                if os.path.exists(self.path):
                    os.remove(self.path)
                if os.path.exists(self.temp_dir):
                    shutil.rmtree(self.temp_dir)
                print(f"✅ 背景清理完成。已刪除臨時目錄: {self.temp_dir}")
        
        # 4. 回傳帶有清理機制的 Response
        return CleanUpFileResponse(
            path=final_filepath,
            temp_dir=temp_dir,
            filename=final_filename,
            media_type=f'application/{target_format}',
            headers={'Content-Disposition': f'attachment; filename="{final_filename}"'},
        )

    except (DownloadError, HTTPException) as e:
        # 如果發生錯誤，立即清理臨時文件
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        # 重新拋出錯誤讓 FastAPI 處理
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"下載或解析錯誤: {e}")
        
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        print(f"伺服器發生未預期的錯誤: {e}")
        raise HTTPException(status_code=500, detail="伺服器內部發生未知錯誤。")
