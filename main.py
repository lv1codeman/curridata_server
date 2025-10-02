from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
# 引入你提供的 MSSQL 資料庫輔助函數和例外
from database_helper import execute_query, DatabaseError, UniqueConstraintError, DatabaseCursor

# 初始化 FastAPI 應用
app = FastAPI()

# 允許所有來源進行 CORS 跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 資料模型 (Pydantic) ---

class DeptBase(BaseModel):
    COLLEGE: str
    COLLEGE_S: str
    DEPT: str
    DEPT_S: str
    STYPE: str
    CAGENT_ID: int

class DeptCreate(DeptBase):
    AGENT_NAME: str
    AGENT_EXT: str
    AGENT_EMAIL: str

class DeptUpdate(DeptBase):
    ID: int

class AgentBase(BaseModel):
    NAME: str
    EXT: str
    EMAIL: str

class AgentCreate(AgentBase):
    pass

class AgentUpdate(AgentBase):
    ID: int

class CAgentBase(BaseModel):
    NAME: str
    EXT: str
    EMAIL: str

class CAgentCreate(CAgentBase):
    pass

class CAgentUpdate(CAgentBase):
    ID: int

class DAListLink(BaseModel):
    DEPT_ID: int
    AGENT_ID: int
    
class DAListDelete(DAListLink):
    pass

# --- API 端點 ---
# 如果有API用到多個TABLE的增刪修改
# 應該用DatabaseCursor將所有操作視為一個transaction
# 確保每個步驟都一起成功或一起失敗
# 例如：create_dept() 需要新增AGENTS、DEPTS

# 1. 讀取系所表(含承辦人及課務組承辦人資料)
@app.get("/get_depts")
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

# 1. 新增系所到DEPTS(含承辦人及課務組承辦人資料)
@app.post("/create_dept")
async def create_dept(item: DeptCreate):
    """
    建立新的系所與承辦人資料。
    會先檢查承辦人是否已存在，若不存在才新增，確保資料不重複。
    """
    sql = """
            INSERT INTO DEPTS (COLLEGE, COLLEGE_S, DEPT, DEPT_S, STYPE, AGENT_NAME, AGENT_EXT, AGENT_EMAIL, CAGENT_ID)
            OUTPUT INSERTED.ID
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
    values = (item.COLLEGE, item.COLLEGE_S, item.DEPT, item.DEPT_S, item.STYPE, item.AGENT_NAME, item.AGENT_EXT, item.AGENT_EMAIL, item.CAGENT_ID)
    
    try:
        execute_query(sql, values)
        return {"message": "Department added successfully."}

    except UniqueConstraintError as e:
        # 如果發生唯一約束錯誤，例如系所名稱重複
        raise HTTPException(status_code=409, detail=f"Failed to create department: {e}")
    except DatabaseError as e:
        # 處理所有其他資料庫相關的錯誤
        raise HTTPException(status_code=500, detail=f"Failed to create department: {e}")


@app.put("/update_dept/{dept_id}")
async def update_dept(dept_id: int, item: DeptCreate):
    sql = """
        UPDATE DEPTS SET
        COLLEGE = ?, COLLEGE_S = ?, DEPT = ?, DEPT_S = ?, STYPE = ?, AGENT_NAME = ?, AGENT_EXT = ?, AGENT_EMAIL = ?, CAGENT_ID = ?
        WHERE ID = ?
    """
    values = (item.COLLEGE, item.COLLEGE_S, item.DEPT, item.DEPT_S, item.STYPE, item.AGENT_NAME, item.AGENT_EXT, item.AGENT_EMAIL, item.CAGENT_ID, dept_id)
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
        return {"message": "Department updated successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to update department: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update department: {e}")

@app.delete("/delete_dept/{dept_id}")
async def delete_dept(dept_id: int):
    try:
        result = execute_query("DELETE FROM DEPTS WHERE ID = ?", (dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
        return {"message": "Department deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete department: {e}")

# . 取得課務組承辦人資料(用於新增系所時選擇課務承辦人後自動帶出資料)
@app.get("/get_cagents")
async def get_cagents():
    try:
        sql = "SELECT * FROM CAGENTS"
        data = execute_query(sql)
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch departments: {e}")
