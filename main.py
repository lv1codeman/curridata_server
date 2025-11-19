# 引入您提供的 MSSQL 資料庫輔助函數和例外
from database_helper import execute_query, DatabaseError, UniqueConstraintError, DatabaseCursor
import time
import tempfile
import os
import shutil
import uuid
from urllib.parse import quote
import json 
# 修正點：引入 asyncio 
import asyncio
from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException, Request, Response, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from pydantic import BaseModel
from typing import List, Optional, Literal, Any, Dict

# 引入YT影片下載套件
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# --- 檔案下載後清理的自定義 Response ---
class FinalCleanUpFileResponse(FileResponse):
    """
    擴展 FileResponse，在檔案發送完成後，嘗試刪除檔案及其臨時目錄。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            # 執行原始 FileResponse 的發送邏輯
            await super().__call__(scope, receive, send)
        finally:
            # 檔案傳輸完成後進行清理
            file_to_remove = self.path
            temp_dir = os.path.dirname(file_to_remove)
            
            # 1. 嘗試刪除檔案本身
            if os.path.exists(file_to_remove):
                os.remove(file_to_remove)
                print(f"🗑️ 已刪除下載文件: {file_to_remove}")
            
            # 2. 嘗試刪除臨時目錄 (如果它是空的)
            if os.path.exists(temp_dir) and temp_dir != '/': # 確保不是根目錄
                try:
                    # rmdir 只刪除空目錄
                    os.rmdir(temp_dir) 
                    print(f"🗑️ 已刪除空臨時目錄: {temp_dir}")
                except OSError:
                    # 如果目錄不為空，則忽略 rmdir 錯誤
                    pass

# --- IP 獲取輔助函式 (針對代理環境優化) ---
def get_client_ip(request: Request) -> str:
    """
    獲取客戶端 IP，優先檢查反向代理（如 ngrok）設定的標準標頭。
    """
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip
    return request.client.host if request.client else "Unknown"

# --- 1. 定義 Custom Middleware (IP 監控) ---
class ClientIPMiddleware(BaseHTTPMiddleware):
    """
    自定義中介軟體，用於記錄客戶端的 IP 位址、請求路徑和處理時間。
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = get_client_ip(request)
        start_time = time.time()
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] IP: {client_ip} | METHOD: {request.method} | PATH: {request.url.path}")

        request.state.client_ip = client_ip

        response = await call_next(request)

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        print(f"IP: {client_ip} 的請求已完成，耗時: {process_time:.4f}s")
        return response

# 初始化 FastAPI 應用
app = FastAPI(title="Curri Data API")

# 允許所有來源進行 CORS 跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. 啟用 IP 監控中介軟體 ---
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

# --- 資料庫初始化函式 (確保 YT_DOWNLOAD_JOBS 表存在) ---
def initialize_database():
    # print("檢查並初始化 YT_DOWNLOAD_JOBS 表...")
    # SQL Server specific syntax
    # 注意: final_filepath 設為 NVARCHAR(255) 應足夠容納臨時路徑
    sql = """
    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='YT_DOWNLOAD_JOBS' and xtype='U')
    CREATE TABLE YT_DOWNLOAD_JOBS (
        ID INT IDENTITY(1,1) PRIMARY KEY,
        job_id NVARCHAR(50) UNIQUE NOT NULL,
        client_ip NVARCHAR(50),
        url NVARCHAR(2048) NOT NULL,
        format NVARCHAR(10) NOT NULL,
        status NVARCHAR(20) NOT NULL, -- PENDING, PROCESSING, COMPLETED, FAILED
        progress INT NOT NULL DEFAULT 0,
        final_filepath NVARCHAR(255),
        start_time DATETIME,
        end_time DATETIME,
        created_at DATETIME DEFAULT GETDATE()
    );
    """
    try:
        # 使用同步執行
        execute_query(sql)
        # print("YT_DOWNLOAD_JOBS 表格準備就緒。")
    except Exception as e:
        # 這裡不應中斷應用程式，但必須警告使用者
        print(f"⚠️ 無法初始化 YT_DOWNLOAD_JOBS 表格，輪詢功能將無法運作: {e}")

# 在應用程式啟動時執行資料庫初始化
initialize_database()

# --- 輪詢架構的背景任務執行函式 ---
def download_and_update_db(job_id: str, url: str, target_format: str):
    """
    實際執行 yt-dlp 下載和轉碼的背景任務。
    它使用 progress_hooks 將進度更新寫回資料庫。
    """
    temp_dir = tempfile.mkdtemp()
    final_filepath = None
    
    # 1. yt-dlp 進度 Hook 函式
    def hook(d):
        try:
            status_map = {
                'downloading': 'PROCESSING',
                'finished': 'PROCESSING', # 轉碼中也視為 Processing
                'error': 'FAILED'
            }
            current_status = status_map.get(d['status'], 'PROCESSING')
            
            progress_percent = 0
            if current_status == 'PROCESSING':
                if d.get('total_bytes'):
                    # 下載進度 (佔 1% - 90%)
                    progress_percent = int((d.get('downloaded_bytes', 0) / d['total_bytes']) * 90)
                elif d['status'] == 'finished':
                    # 下載完成，進入後處理階段，進度設為 95%
                    progress_percent = 95
                else:
                    # 預設值，例如剛開始或無法計算時
                    progress_percent = 10 
            
            # 寫入資料庫 (同步執行)
            execute_query(
                "UPDATE YT_DOWNLOAD_JOBS SET status=?, progress=? WHERE job_id=?", 
                (current_status, progress_percent, job_id)
            )

        except Exception as hook_e:
            print(f"⚠️ 進度更新錯誤 (Job {job_id}): {hook_e}")

    # 2. 主要下載邏輯
    try:
        # 更新狀態為 PROCESSING (進度 10%) (同步執行)
        execute_query("UPDATE YT_DOWNLOAD_JOBS SET status='PROCESSING', start_time=GETDATE(), progress=10 WHERE job_id=?", (job_id,))
        
        # 根據目標格式設定 yt-dlp 選項
        if target_format == 'mp3':
            ydl_opts = {
                'format': 'bestaudio/best',
                # outtmpl 在後續會被精確設定，這裡使用簡單的 title 佔位
                'outtmpl': os.path.join(temp_dir, '%(title)s'), 
                'noplaylist': True,
                'quiet': True,
                'progress_hooks': [hook], # 啟用進度 Hook
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            }
            expected_ext = '.mp3'
        elif target_format == 'mp4':
            # MP4 配置 (已修正，移除了冗餘的 postprocessors)
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(temp_dir, '%(title)s'), 
                'noplaylist': True,
                'quiet': True,
                'progress_hooks': [hook], # 啟用進度 Hook
            }
            expected_ext = '.mp4' 
        
        with YoutubeDL(ydl_opts) as ydl:
            # 獲取資訊
            info_dict = ydl.extract_info(url, download=False)
            
            # 1. 處理檔名：確保檔名乾淨且只包含一個擴展名 (供瀏覽器和 DB 使用)
            base_title = info_dict.get('title', 'download_file')
            # 移除任何不適合檔案名的字符
            base_title = "".join([c for c in base_title if c.isalnum() or c in (' ', '_', '-')]).rstrip()
            
            # 這是我們期望的最終檔名 (含單一擴展名)
            final_filename_for_browser = base_title + expected_ext
            
            # 2. 決定 YTDLP 的輸出路徑模板 (outtmpl)
            if target_format == 'mp3':
                # 🎯 修正點：MP3 使用 post-processor， outtmpl 不應包含 .mp3，讓 post-processor 添加。
                ydl_outtmpl_path = os.path.join(temp_dir, base_title) 
                # 預期的最終路徑 (包含 .mp3)
                final_filepath_temp = os.path.join(temp_dir, final_filename_for_browser)
            else: # MP4
                # MP4 使用 merge，outtmpl 應包含 .mp4 (這樣會產生 MyTitle.mp4)
                ydl_outtmpl_path = os.path.join(temp_dir, final_filename_for_browser)
                # 預期的最終路徑
                final_filepath_temp = ydl_outtmpl_path
            
            # 將正確的 outtmpl 設置回選項
            ydl_opts['outtmpl'] = ydl_outtmpl_path 
            
            print(f"Job {job_id} 預期瀏覽器檔名: {final_filename_for_browser}, YTDLP outtmpl: {ydl_outtmpl_path}")

            # 重新初始化 YDL 並執行下載和後處理
            with YoutubeDL(ydl_opts) as final_ydl:
                final_ydl.download([url])
            
            # 確保 final_filepath 是實際的檔案路徑
            if os.path.exists(final_filepath_temp):
                final_filepath = final_filepath_temp
            
        if not final_filepath or not os.path.exists(final_filepath):
             # 重新檢查目錄內容，以防檔名預測錯誤
             found_files = [f for f in os.listdir(temp_dir) if f.endswith(expected_ext)]
             if found_files:
                 # 如果找到了，使用找到的第一個檔案
                 final_filename = found_files[0]
                 final_filepath = os.path.join(temp_dir, final_filename)
                 print(f"⚠️ 檔名預測失敗，但找到了檔案: {final_filepath}")
             else:
                 raise Exception("文件生成失敗，請檢查 yt-dlp 執行日誌。")

        # 成功完成後更新資料庫 (同步執行)
        # 這裡將使用正確的 final_filepath 存入資料庫
        execute_query(
            "UPDATE YT_DOWNLOAD_JOBS SET status='COMPLETED', progress=100, final_filepath=?, end_time=GETDATE() WHERE job_id=?", 
            (final_filepath, job_id)
        )
        print(f"✅ Job {job_id} 成功完成。檔案: {final_filepath}")

    except Exception as e:
        # 失敗時更新資料庫狀態 (同步執行)
        error_message = f"下載失敗: {str(e)}"
        execute_query(
            "UPDATE YT_DOWNLOAD_JOBS SET status='FAILED', progress=0, end_time=GETDATE(), final_filepath='ERROR' WHERE job_id=?", 
            (job_id,)
        )
        print(f"❌ Job {job_id} 失敗: {error_message}")
        
        # 失敗後立即清理臨時目錄
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

# --- 輪詢架構 API 端點 (取代 /download 與 /download_final) ---

# 14. 提交 YouTube 下載任務
@app.post("/submit_download_job", summary="提交 YouTube 下載任務 (非同步輪詢第一步)")
async def submit_download_job(request: DownloadRequest, background_tasks: BackgroundTasks, req: Request):
    """
    客戶端呼叫此 API 提交任務，伺服器立即返回 Job ID 並在背景啟動下載。
    """
    client_ip = get_client_ip(req)
    job_id = str(uuid.uuid4())

    try:
        # 1. 記錄初始任務狀態到資料庫 (Status: PENDING)
        insert_sql = """
            INSERT INTO YT_DOWNLOAD_JOBS (job_id, client_ip, url, format, status, progress)
            VALUES (?, ?, ?, ?, 'PENDING', 0);
        """
        # 使用 asyncio.to_thread 確保 execute_query 在單獨的執行緒中執行
        await asyncio.to_thread(execute_query, insert_sql, (job_id, client_ip, request.url, request.format))

        # 2. 將實際的下載工作加入背景任務
        background_tasks.add_task(download_and_update_db, job_id, request.url, request.format)

        return {"job_id": job_id, "message": "下載任務已提交，請使用 job_id 輪詢狀態。"}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"提交任務失敗: 資料庫錯誤: {e}")

# 15. 查詢下載任務狀態
@app.get("/download_status/{job_id}", summary="查詢下載任務狀態和進度 (非同步輪詢第二步)")
async def get_download_status(job_id: str):
    """
    客戶端使用 Job ID 輪詢任務狀態和進度。
    返回: status (PENDING/PROCESSING/COMPLETED/FAILED), progress (0-100)
    """
    try:
        sql = "SELECT status, progress FROM YT_DOWNLOAD_JOBS WHERE job_id = ?"
        
        # 使用 fetch_one=True，預期返回字典或 None
        data = await asyncio.to_thread(execute_query, sql, (job_id,), fetch_one=True)
        
        if not data:
            # 如果資料為 None 或空，則表示 Job ID 不存在
            raise HTTPException(status_code=404, detail=f"Job ID {job_id} 未找到。")

        # 修正點：使用欄位名稱 'status' 和 'progress' 作為字典鍵來存取結果
        return {"status": data['status'], "progress": data['progress']} 
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"查詢狀態失敗: {e}")
    except KeyError as e:
        # 捕獲 KeyError，如果資料庫返回的字典缺少預期的鍵
        raise HTTPException(status_code=500, detail=f"查詢狀態失敗: 資料結構錯誤，無法使用鍵 {e} 存取結果。")


# 16. 獲取最終下載文件
@app.get("/download_file/{job_id}", summary="獲取最終下載文件 (非同步輪詢第三步)")
async def download_file(job_id: str):
    
    sql_query = "SELECT final_filepath, status FROM YT_DOWNLOAD_JOBS WHERE job_id = ?"
    
    # 使用 fetch_one=True，預期返回字典
    job_details: Optional[Dict[str, Any]] = await asyncio.to_thread(execute_query, sql_query, (job_id,), fetch_one=True)

    if not job_details:
        raise HTTPException(status_code=404, detail="工作 ID 未找到。")
    
    # 修正點：統一使用字典鍵存取
    file_path = job_details.get('final_filepath')
    current_status = job_details.get('status', 'UNKNOWN')
    
    if current_status != 'COMPLETED':
        # 如果狀態不是完成，則不能下載
        raise HTTPException(status_code=400, detail=f"檔案尚未準備好，目前狀態: {current_status}")

    if not file_path or file_path == 'ERROR':
        raise HTTPException(status_code=404, detail="下載任務已完成但未記錄有效檔案路徑或已失敗。")
    
    if not os.path.exists(file_path):
        # 如果檔案不存在 (可能已被清理或下載失敗)
        raise HTTPException(status_code=404, detail="檔案已完成下載但伺服器上找不到對應文件 (可能已被清理)。")


    # 從路徑中解析出檔案名稱
    original_filename = os.path.basename(file_path)
    
    # 手動建構 Content-Disposition 標頭以支援中文
    # 1. 將原始檔名轉換為 ASCII 安全版本
    ascii_filename = original_filename.encode('ascii', 'replace').decode('ascii')
    
    # 2. 將原始檔名進行 URL 編碼 (用於 filename* 部分)
    quoted_filename_utf8 = quote(original_filename)

    # 3. 建構 RFC 5987 標準的 Content-Disposition 標頭
    content_disposition_header = (
        f'attachment; '
        f'filename="{ascii_filename}"; ' # ASCII fallback
        f"filename*=utf-8''{quoted_filename_utf8}" # UTF-8 規範名稱
    )
    
    response_headers = {
        'Content-Disposition': content_disposition_header,
        # 其他您可能需要的標頭
    }
    
    # 4. 回傳帶有修正標頭的 FinalCleanUpFileResponse
    return FinalCleanUpFileResponse(
        path=file_path,
        headers=response_headers,
        media_type="application/octet-stream" # 這是通用下載類型
    )

# --- 以下為不變動的既有 API 端點 ---

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
        data = await asyncio.to_thread(execute_query, sql)
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
        await asyncio.to_thread(execute_query, sql, values)
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
        # execute_query(sql, values) 返回的是受影響的行數
        result = await asyncio.to_thread(execute_query, sql, values)
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
        result = await asyncio.to_thread(execute_query, "DELETE FROM DEPTS WHERE ID = ?", (dept_id,))
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
        data = await asyncio.to_thread(execute_query, sql)
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
        await asyncio.to_thread(execute_query, sql, values)
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
        result = await asyncio.to_thread(execute_query, sql, values)
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
        result = await asyncio.to_thread(execute_query, "DELETE FROM CAGENTS WHERE ID = ?", (cagent_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Curri agent with ID {cagent_id} not found.")
        return {"message": "Curri agent deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete Curri agent: {e}")


# 9. 呼叫 sp_GetAll 預存程序 for ClassConverter
@app.get("/get_all_data")
async def get_all_data():
    try:
        data = await asyncio.to_thread(execute_query, "EXEC sp_GetAll")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")

# --- MAP_CLS_DEPT ---
# 10. 查詢班級-系所簡稱對照表
@app.get("/get_map_cls_dept", summary="查詢所有班級-系所簡稱對照資料")
async def get_map_cls_dept():
    try:
        sql = "SELECT * FROM MAP_CLS_DEPT"
        data = await asyncio.to_thread(execute_query, sql)
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
        await asyncio.to_thread(execute_query, sql, values)
        return {"message": "Class-dept_short added successfully."}

    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to create class-dept_short: 唯一約束衝突 (班級與簡稱組合可能已存在)")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to create class-dept_short: 資料庫錯誤: {e}")

# 12. 修改班級-系所簡稱
@app.put("/update_map_cls_dept/{map_cls_dept_id}", summary="修改指定 ID 的班級-系所簡稱對照")
async def update_map_cls_dept(map_cls_dept_id: int, item: MAP_CLS_DEPT): # 修正：這裡的 MAP_CLS_CLS_DEPT 應該是 MAP_CLS_DEPT
    sql = """
        UPDATE MAP_CLS_DEPT SET
        CLASS = ?, DEPT_S = ?
        WHERE ID = ?
    """
    values = (item.CLASS, item.DEPT_S, map_cls_dept_id)
    try:
        result = await asyncio.to_thread(execute_query, sql, values)
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
        result = await asyncio.to_thread(execute_query, "DELETE FROM MAP_CLS_DEPT WHERE ID = ?", (map_cls_dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail=f"Class-dept_short with ID {map_cls_dept_id} not found.")
        return {"message": "class-dept_short deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete class-dept_short: {e}")

print(f"curridata_server已啟動，等候客戶端訪問中...")