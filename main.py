import time
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from pydantic import BaseModel
from typing import List, Optional

# 引入您提供的 MSSQL 資料庫輔助函數和例外
# Assumes database_helper.py is present and functional
from database_helper import execute_query, DatabaseError, UniqueConstraintError, DatabaseCursor

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
@app.get("/get_all_data", summary="呼叫 sp_GetAll 預存程序")
async def get_all_data():
    try:
        data = execute_query("EXEC sp_GetAll")
        if data is None:
            # 即使 sp_GetAll 執行成功但沒有回傳資料，也應該避免回傳 None
            return []
            
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
