import pyodbc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database_helper import DatabaseCursor # 引入我們定義的上下文管理器

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

# --- API 端點 (整合所有功能) ---

# 1. 獲取 CLASSDEPTSHORT 的資料
@app.get("/classdeptshort")
async def get_class_depts():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("SELECT CLASS, DEPTSHORT FROM CLASSDEPTSHORT")
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data: {e}")

# 2. 獲取 DEPLIST 的資料
@app.get("/deptlist")
async def get_deplist():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute(
                "SELECT ID, DEPTSHORT, DEPT, COLLEGE, COLLEGESHORT, AGENT, AGENTEXT, AGENTEMAIL, CAGENT, CAGENTEXT, CAGENTEMAIL FROM DEPTLIST"
            )
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch department list data: {e}")

# 3. 呼叫 sp_GetAll 預存程序
@app.get("/get_all_data")
async def get_all_data():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("EXEC sp_GetAll")
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")

# 4. 呼叫 sp_GetDataByClass 預存程序
@app.get("/get_class_details/{class_name}")
async def get_class_details(class_name: str):
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("EXEC sp_GetDataByClass ?", (class_name,))
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data: {e}")

# 5. 呼叫 sp_GetDEPTLIST 預存程序
@app.get("/get_deptlist")
async def get_deptlist():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("EXEC sp_GetDEPTLIST")
            columns = [column[0] for column in cursor.description]
            data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")

# 6. 新增系所 (Create)
@app.post("/add_dept")
async def add_dept(item: dict):
    try:
        with DatabaseCursor() as cursor:
            required_fields = ["COLLEGE", "COLLEGESHORT", "DEPTSHORT", "DEPT", "STYPE", "AGENT", "AGENTEXT", "AGENTEMAIL", "CAGENT", "CAGENTEXT", "CAGENTEMAIL"]
            if not all(field in item and item.get(field) for field in required_fields):
                raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

            # 檢查 DEPT 是否已存在
            cursor.execute("SELECT COUNT(*) FROM DEPTLIST WHERE DEPT = ?", (item.get("DEPT"),))
            if cursor.fetchone()[0] > 0:
                raise HTTPException(status_code=409, detail=f"Department '{item.get('DEPT')}' already exists.")

            sql = """
                INSERT INTO DEPTLIST (
                    COLLEGE, COLLEGESHORT, DEPTSHORT, DEPT, STYPE,
                    AGENT, AGENTEXT, AGENTEMAIL, CAGENT, CAGENTEXT, CAGENTEMAIL
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            values = (
                item.get("COLLEGE"),
                item.get("COLLEGESHORT"),
                item.get("DEPTSHORT"),
                item.get("DEPT"),
                item.get("STYPE"),
                item.get("AGENT"),
                item.get("AGENTEXT"),
                item.get("AGENTEMAIL"),
                item.get("CAGENT"),
                item.get("CAGENTEXT"),
                item.get("CAGENTEMAIL")
            )
            
            cursor.execute(sql, values)
        
        return {"message": "Department added successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to add department: {e}")

# 7. 更新系所 (Update)
@app.put("/update_dept")
async def update_dept(item: dict):
    try:
        with DatabaseCursor() as cursor:
            # 使用 ID 來識別要更新的資料
            if "ID" not in item:
                raise HTTPException(status_code=400, detail="ID field is required for update.")

            sql = """
                UPDATE DEPTLIST SET
                    COLLEGE = ?, COLLEGESHORT = ?, DEPTSHORT = ?, DEPT = ?, STYPE = ?,
                    AGENT = ?, AGENTEXT = ?, AGENTEMAIL = ?, CAGENT = ?,
                    CAGENTEXT = ?, CAGENTEMAIL = ?
                WHERE ID = ?
            """
            values = (
                item.get("COLLEGE"),
                item.get("COLLEGESHORT"),
                item.get("DEPTSHORT"),
                item.get("DEPT"),
                item.get("STYPE"),
                item.get("AGENT"),
                item.get("AGENTEXT"),
                item.get("AGENTEMAIL"),
                item.get("CAGENT"),
                item.get("CAGENTEXT"),
                item.get("CAGENTEMAIL"),
                item.get("ID")  # 條件值使用 ID
            )

            cursor.execute(sql, values)
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Department not found.")
        
        return {"message": "Department updated successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to update department: {e}")

# 8. 刪除系所 (Delete)
@app.delete("/delete_dept/{dept_id}")
async def delete_dept(dept_id: int):
    try:
        with DatabaseCursor() as cursor:
            sql = "DELETE FROM DEPTLIST WHERE ID = ?"
            cursor.execute(sql, (dept_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Department not found.")
        return {"message": "Department deleted successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to delete department: {e}")

# 9. 取得所有課務承辦人
@app.get("/get_cagent")
async def get_cagent():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("SELECT * FROM CURRIAGENT")
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch curriculum agents: {e}")

# 10. 新增課務承辦人
@app.post("/add_cagent")
async def add_cagent(item: dict):
    try:
        with DatabaseCursor() as cursor:
            required_fields = ["NAME", "EXT", "EMAIL"]
            if not all(field in item and item.get(field) for field in required_fields):
                raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

            sql = "INSERT INTO CURRIAGENT (NAME, EXT, EMAIL) VALUES (?, ?, ?)"
            values = (item.get("NAME"), item.get("EXT"), item.get("EMAIL"))
            cursor.execute(sql, values)
        return {"message": "Curriculum agent added successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to add curriculum agent: {e}")

# 11. 更新課務承辦人
@app.put("/update_cagent/{cagent_id}")
async def update_cagent(cagent_id: int, item: dict):
    try:
        with DatabaseCursor() as cursor:
            item_upper = {k.upper(): v for k, v in item.items()}

            required_fields = ["NAME", "EXT", "EMAIL"]
            if not all(field in item_upper and item_upper.get(field) for field in required_fields):
                raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

            sql = "UPDATE CURRIAGENT SET NAME = ?, EXT = ?, EMAIL = ? WHERE ID = ?"
            values = (item_upper.get("NAME"), item_upper.get("EXT"), item_upper.get("EMAIL"), cagent_id)
            cursor.execute(sql, values)
        return {"message": "Curriculum agent updated successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to update curriculum agent: {e}")

# 12. 刪除課務承辦人
@app.delete("/delete_cagent/{cagent_id}")
async def delete_cagent(cagent_id: int):
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("DELETE FROM CURRIAGENT WHERE ID = ?", (cagent_id,))
        return {"message": "Curriculum agent deleted successfully."}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to delete curriculum agent: {e}")

# 13. 取得所有CLASSDEPTSHORT
@app.get("/get_class_deptshort")
async def get_cagent():
    try:
        with DatabaseCursor() as cursor:
            cursor.execute("SELECT * FROM CLASSDEPTSHORT")
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch curriculum agents: {e}")
