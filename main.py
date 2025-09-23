import pyodbc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database_helper import DatabaseCursor, execute_query, UniqueConstraintError, DatabaseError

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

# --- API 端點 (已重構為使用 execute_query) ---

# 1. 獲取 CLASSDEPTSHORT 的資料
@app.get("/classdeptshort")
async def get_class_depts():
    try:
        data = execute_query("SELECT CLASS, DEPTSHORT FROM CLASSDEPTSHORT")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data: {e}")


# 2. 獲取 DEPLIST 的資料 (直接從資料表)
@app.get("/deptlist")
async def get_deplist():
    try:
        query = "SELECT ID, DEPTSHORT, DEPT, COLLEGE, COLLEGESHORT, AGENT, AGENTEXT, AGENTEMAIL, CAGENT, CAGENTEXT, CAGENTEMAIL FROM DEPTLIST"
        data = execute_query(query)
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch department list data: {e}")

# 3. 呼叫 sp_GetAll 預存程序
@app.get("/get_all_data")
async def get_all_data():
    try:
        data = execute_query("EXEC sp_GetAll")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")

# 4. 呼叫 sp_GetDataByClass 預存程序
@app.get("/get_class_details/{class_name}")
async def get_class_details(class_name: str):
    try:
        data = execute_query("EXEC sp_GetDataByClass ?", (class_name,))
        if not data:
            raise HTTPException(status_code=404, detail=f"No data found for class: {class_name}")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data for '{class_name}': {e}")

# 5. 呼叫 sp_GetDEPTLIST 預存程序
@app.get("/get_deptlist")
async def get_deptlist_sp():
    try:
        data = execute_query("EXEC sp_GetDEPTLIST")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch department list from stored procedure: {e}")

# 6. 新增系所 (Create)
@app.post("/add_dept")
async def add_dept(item: dict):
    # 檢查 DEPT 是否已存在 (這裡仍然需要直接使用 cursor，因為這是一個 pre-check)
    with DatabaseCursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM DEPTLIST WHERE DEPT = ?", (item.get("DEPT"),))
        if cursor.fetchone()[0] > 0:
            raise HTTPException(status_code=409, detail=f"Department '{item.get('DEPT')}' already exists.")

    # 執行實際的插入操作
    sql = """
        INSERT INTO DEPTLIST (
            COLLEGE, COLLEGESHORT, DEPTSHORT, DEPT, STYPE,
            AGENT, AGENTEXT, AGENTEMAIL, CAGENT, CAGENTEXT, CAGENTEMAIL
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values = (
        item.get("COLLEGE"), item.get("COLLEGESHORT"), item.get("DEPTSHORT"),
        item.get("DEPT"), item.get("STYPE"), item.get("AGENT"),
        item.get("AGENTEXT"), item.get("AGENTEMAIL"), item.get("CAGENT"),
        item.get("CAGENTEXT"), item.get("CAGENTEMAIL")
    )
    try:
        execute_query(sql, values)
        return {"message": "Department added successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to add department: {e}")

# 7. 更新系所 (Update)
@app.put("/update_dept")
async def update_dept(item: dict):
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
        item.get("COLLEGE"), item.get("COLLEGESHORT"), item.get("DEPTSHORT"),
        item.get("DEPT"), item.get("STYPE"), item.get("AGENT"),
        item.get("AGENTEXT"), item.get("AGENTEMAIL"), item.get("CAGENT"),
        item.get("CAGENTEXT"), item.get("CAGENTEMAIL"), item.get("ID")
    )
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
        return {"message": "Department updated successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update department: {e}")

# 8. 刪除系所 (Delete)
@app.delete("/delete_dept/{dept_id}")
async def delete_dept(dept_id: int):
    try:
        result = execute_query("DELETE FROM DEPTLIST WHERE ID = ?", (dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
        return {"message": "Department deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete department: {e}")

# 9. 取得所有課務承辦人
@app.get("/get_cagent")
async def get_cagent():
    try:
        data = execute_query("SELECT * FROM CURRIAGENT")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch curriculum agents: {e}")

# 10. 新增課務承辦人
@app.post("/add_cagent")
async def add_cagent(item: dict):
    required_fields = ["NAME", "EXT", "EMAIL"]
    if not all(field in item and item.get(field) for field in required_fields):
        raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

    sql = "INSERT INTO CURRIAGENT (NAME, EXT, EMAIL) VALUES (?, ?, ?)"
    values = (item.get("NAME"), item.get("EXT"), item.get("EMAIL"))
    try:
        execute_query(sql, values)
        return {"message": "Curriculum agent added successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to add curriculum agent: {e}")

# 11. 更新課務承辦人
@app.put("/update_cagent/{cagent_id}")
async def update_cagent(cagent_id: int, item: dict):
    item_upper = {k.upper(): v for k, v in item.items()}

    required_fields = ["NAME", "EXT", "EMAIL"]
    if not all(field in item_upper and item_upper.get(field) for field in required_fields):
        raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

    sql = "UPDATE CURRIAGENT SET NAME = ?, EXT = ?, EMAIL = ? WHERE ID = ?"
    values = (item_upper.get("NAME"), item_upper.get("EXT"), item_upper.get("EMAIL"), cagent_id)
    try:
        execute_query(sql, values)
        return {"message": "Curriculum agent updated successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update curriculum agent: {e}")

# 12. 刪除課務承辦人
@app.delete("/delete_cagent/{cagent_id}")
async def delete_cagent(cagent_id: int):
    try:
        result = execute_query("DELETE FROM CURRIAGENT WHERE ID = ?", (cagent_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail="Curriculum agent not found.")
        return {"message": "Curriculum agent deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete curriculum agent: {e}")

# 13. 取得所有班級-系所簡稱對照
@app.get("/get_class_deptshort")
async def get_class_deptshort():
    try:
        data = execute_query("SELECT * FROM CLASSDEPTSHORT")
        return data
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class department short data: {e}")

# 14. 新增班級-系所簡稱對照 (Create)
@app.post("/add_class_deptshort")
async def add_class_deptshort(item: dict):
    sql = "INSERT INTO CLASSDEPTSHORT (CLASS, DEPTSHORT) VALUES (?, ?)"
    values = (item.get("CLASS"), item.get("DEPTSHORT"))
    try:
        execute_query(sql, values)
        return {"message": "Class department short added successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"Failed to add class department short: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to add class department short: {e}")

# 15. 更新班級-系所簡稱對照 (Update)
@app.put("/update_class_deptshort")
async def update_class_deptshort(item: dict):
    if "ID" not in item:
        raise HTTPException(status_code=400, detail="ID field is required for update.")

    sql = "UPDATE CLASSDEPTSHORT SET CLASS = ?, DEPTSHORT = ? WHERE ID = ?"
    values = (item.get("CLASS"), item.get("DEPTSHORT"), item.get("ID"))
    try:
        result = execute_query(sql, values)
        if result == 0:
            raise HTTPException(status_code=404, detail="Class department short not found.")
        return {"message": "Class department short updated successfully."}
    except UniqueConstraintError as e:
        raise HTTPException(status_code=409, detail=f"The combination of CLASS and DEPTSHORT already exists: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update class department short: {e}")

# 16. 刪除班級-系所簡稱對照 (Delete)
@app.delete("/delete_class_deptshort/{class_dept_id}")
async def delete_class_deptshort(class_dept_id: int):
    try:
        result = execute_query("DELETE FROM CLASSDEPTSHORT WHERE ID = ?", (class_dept_id,))
        if result == 0:
            raise HTTPException(status_code=404, detail="Class department short not found.")
        return {"message": "Class department short deleted successfully."}
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete class department short: {e}")
