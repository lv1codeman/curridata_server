import pyodbc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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

# 建立資料庫連線
def get_db_connection():
    try:
        connection_string = 'DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-0O8RKB2;DATABASE=CURRIDATA;Trusted_Connection=yes;'
        conn = pyodbc.connect(connection_string)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {e}")

# --- API 端點 (整合所有功能) ---

# 1. 獲取 CLASSDEPTSHORT 的資料
@app.get("/classdeptshort")
async def get_class_depts():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT CLASS, DEPTSHORT FROM CLASSDEPTSHORT")
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data: {e}")
    finally:
        if conn:
            conn.close()

# 2. 獲取 DEPLIST 的資料
@app.get("/deptlist")
async def get_deplist():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ID, DEPTSHORT, DEPT, COLLEGE, COLLEGESHORT, AGENT, AGENTEXT, AGENTEMAIL, CAGENT, CAGENTEXT, CAGENTEMAIL FROM DEPTLIST"
        )
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch department list data: {e}")
    finally:
        if conn:
            conn.close()

# 3. 呼叫 sp_GetAll 預存程序
@app.get("/get_all_data")
async def get_all_data():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("EXEC sp_GetAll")
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")
    finally:
        if conn:
            conn.close()

# 4. 呼叫 sp_GetDataByClass 預存程序
@app.get("/get_class_details/{class_name}")
async def get_class_details(class_name: str):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("EXEC sp_GetDataByClass ?", (class_name,))
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch class data: {e}")
    finally:
        if conn:
            conn.close()

# 5. 呼叫 sp_GetDEPTLIST 預存程序
@app.get("/get_deptlist")
async def get_deptlist():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("EXEC sp_GetDEPTLIST")
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch all data from stored procedure: {e}")
    finally:
        if conn:
            conn.close()

# 6. 新增系所 (Create)
@app.post("/add_dept")
async def add_dept(item: dict):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

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
        conn.commit()

        return {"message": "Department added successfully."}
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to add department: {e}")
    finally:
        if conn:
            conn.close()

# 7. 更新系所 (Update)
@app.put("/update_dept")
async def update_dept(item: dict):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
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
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Department not found.")

        return {"message": "Department updated successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update department: {e}")
    finally:
        if conn:
            conn.close()

# 8. 刪除系所 (Delete)
@app.delete("/delete_dept/{dept_id}")
async def delete_dept(dept_id: int):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        sql = "DELETE FROM DEPTLIST WHERE ID = ?"
        
        cursor.execute(sql, (dept_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Department not found.")
            
        return {"message": "Department deleted successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete department: {e}")
    finally:
        if conn:
            conn.close()

# 9. 取得所有課務承辦人
@app.get("/get_cagent")
async def get_cagent():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM CURRIAGENT")
        rows = cursor.fetchall()
        
        columns = [column[0] for column in cursor.description]
        result = [dict(zip(columns, row)) for row in rows]
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch curriculum agents: {e}")
    finally:
        if conn:
            conn.close()

# 10. 新增課務承辦人
@app.post("/add_cagent")
async def add_cagent(item: dict):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        required_fields = ["NAME", "EXT", "EMAIL"]
        if not all(field in item and item.get(field) for field in required_fields):
            raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

        sql = "INSERT INTO CURRIAGENT (NAME, EXT, EMAIL) VALUES (?, ?, ?)"
        values = (item.get("NAME"), item.get("EXT"), item.get("EMAIL"))
        cursor.execute(sql, values)
        conn.commit()
        return {"message": "Curriculum agent added successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add curriculum agent: {e}")
    finally:
        if conn:
            conn.close()

# 11. 更新課務承辦人
@app.put("/update_cagent/{cagent_id}")
async def update_cagent(cagent_id: int, item: dict):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 統一將接收到的鍵值轉換為大寫，以匹配資料庫
        # 這讓後端更具彈性，無論前端傳送大寫或小寫都沒問題
        item_upper = {k.upper(): v for k, v in item.items()}

        required_fields = ["NAME", "EXT", "EMAIL"]
        if not all(field in item_upper and item_upper.get(field) for field in required_fields):
            raise HTTPException(status_code=400, detail="Missing or empty value for one or more required fields.")

        # 從轉換後的字典中獲取資料
        sql = "UPDATE CURRIAGENT SET NAME = ?, EXT = ?, EMAIL = ? WHERE ID = ?"
        values = (item_upper.get("NAME"), item_upper.get("EXT"), item_upper.get("EMAIL"), cagent_id)
        
        cursor.execute(sql, values)
        conn.commit()
        return {"message": "Curriculum agent updated successfully."}
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update curriculum agent: {e}")
    finally:
        if conn:
            conn.close()

# 12. 刪除課務承辦人
@app.delete("/delete_cagent/{cagent_id}")
async def delete_cagent(cagent_id: int):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM CURRIAGENT WHERE ID = ?", (cagent_id,))
        conn.commit()
        return {"message": "Curriculum agent deleted successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete curriculum agent: {e}")
    finally:
        if conn:
            conn.close()

# 13. 取得所有CLASSDEPTSHORT
@app.get("/get_class_deptshort")
async def get_cagent():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM CLASSDEPTSHORT")
        rows = cursor.fetchall()
        
        columns = [column[0] for column in cursor.description]
        result = [dict(zip(columns, row)) for row in rows]
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch curriculum agents: {e}")
    finally:
        if conn:
            conn.close()